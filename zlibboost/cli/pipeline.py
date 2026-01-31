from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple
import os

from zlibboost.parsers import UnifiedTclParser
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.arc_generation.auto_arc_generator import AutoArcGenerator
from zlibboost.simulation.generators.factory import SpiceGeneratorFactory
from zlibboost.simulation import runner as simulation_runner
from zlibboost.output.json import LibraryJsonExporter
from zlibboost.output.liberty.json2lib import Json2Liberty
from zlibboost.core.config.base import ConfigManager
from zlibboost.core.logger import LogManager
from zlibboost.core.exceptions import ConfigError, CommandParseError, ConfigurationError
from zlibboost.simulation.preprocessors import preprocess_ngspice_decks


logger = LogManager().get_logger(__name__)


@dataclass
class PipelineConfig:
    config_files: List[str]
    timing_files: List[str]
    out_dir: str | None
    auto_arc: bool = True
    overrides: Dict[str, str] | None = None
    simulate: bool = True
    simulate_engine: str | None = "spectre"


def _set_driver_waveform_env(raw_value: Any) -> None:
    """Propagate driver waveform selection into the environment for waveform handlers."""

    if raw_value is None:
        os.environ.setdefault("DRIVER_WAVEFORM_TYPE", "1")
        return

    value = str(raw_value).strip()
    if not value:
        os.environ.setdefault("DRIVER_WAVEFORM_TYPE", "1")
        return

    os.environ["DRIVER_WAVEFORM_TYPE"] = value


def _clean_template_value(raw_value: str | os.PathLike[str]) -> str:
    """Return a normalized template path token without surrounding quotes/braces."""

    cleaned = str(raw_value).strip()
    if not cleaned:
        return ""
    if cleaned.startswith("{") and cleaned.endswith("}"):
        cleaned = cleaned[1:-1].strip()
    if cleaned.startswith("'") and cleaned.endswith("'"):
        cleaned = cleaned[1:-1].strip()
    if cleaned.startswith('"') and cleaned.endswith('"'):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _resolve_template_file(raw_value: str, config_path: Path) -> str:
    """Resolve template_file path relative to the config file location."""

    normalized = _clean_template_value(raw_value)
    template_path = Path(normalized)
    if not template_path.is_absolute():
        template_path = (config_path.parent / template_path).resolve()
    return str(template_path)


def parse_files_and_build_library(cfg: PipelineConfig) -> Tuple[UnifiedTclParser, CellLibraryDB, Dict[str, str]]:
    """Parse config/timing TCL files and return parser, library_db, reserved_vars.

    - Uses a single UnifiedTclParser instance to accumulate state across files.
    - Merges reserved_vars from all config files in order.
    """
    parser = UnifiedTclParser(engine_name="cli")
    merged_reserved: Dict[str, str] = {}
    autodetected_template_value: str | None = None
    autodetected_template_config: Path | None = None

    # Parse config files first to collect reserved variables
    for path in cfg.config_files or []:
        logger.info(f"Parsing config TCL: {path}")
        config_path = Path(path).expanduser()
        previous_reserved = dict(parser.get_reserved_vars())
        parser.parse_config_file(str(config_path))
        current_reserved = dict(parser.get_reserved_vars())
        merged_reserved.update(current_reserved)

        prev_template = previous_reserved.get("template_file")
        new_template = current_reserved.get("template_file")
        if new_template and new_template != prev_template:
            autodetected_template_value = new_template
            autodetected_template_config = config_path.resolve()

    _set_driver_waveform_env(merged_reserved.get("driver_waveform"))

    timing_files = list(cfg.timing_files or [])
    if not timing_files and autodetected_template_value and autodetected_template_config:
        resolved_template = _resolve_template_file(
            autodetected_template_value,
            autodetected_template_config,
        )
        logger.info(
            "Timing files not provided via CLI; using template_file from config: %s",
            resolved_template,
        )
        timing_files = [resolved_template]

    if not timing_files:
        raise ConfigurationError(
            "No timing TCL files provided. Ensure template_file is defined in the config."
        )

    # Parse timing files next (accumulates into the same library_db)
    for path in timing_files:
        logger.info(f"Parsing timing TCL: {path}")
        parser.parse_file(path, file_type="auto")

    return parser, parser.get_library_db(), merged_reserved


def _soft_validate_and_merge_params(reserved: Dict[str, str], overrides: Dict[str, str] | None) -> Dict[str, str]:
    """Soft-validate and merge parameters using ConfigManager defaults and per-parameter validation.

    Avoids full configuration validation that enforces required path existence
    not strictly needed for deck generation. We still convert types and apply
    defaults to measurement parameters.
    """
    cm = ConfigManager()

    # Start from defaults to ensure measurement thresholds and basic params exist
    params: Dict[str, str] = cm.get_all_parameters()

    # Merge reserved vars from TCL, then CLI overrides (CLI has higher priority)
    for source in (reserved or {}, overrides or {}):
        for k, v in source.items():
            try:
                # Convert each parameter individually
                converted = cm.validator.validate_parameter(k, v)
                params[k] = converted
            except Exception:
                # For unknown keys or conversion errors, keep raw string value
                params[k] = v

    # Inject generator-expected keys derived from common names
    if "modelfiles" in params:
        params.setdefault("lib_dir", params["modelfiles"])  # model/libs root
    if "spicefiles" in params:
        params.setdefault("cell_deck_dir", params["spicefiles"])  # cell netlists root

    # Default spicefiles_format if missing
    if "spicefiles_format" not in params:
        sim = str(params.get("spice_simulator", "hspice")).lower()
        params["spicefiles_format"] = "scs" if sim == "spectre" else "sp"

    return params


def apply_config_to_library(reserved: Dict[str, str], cfg: PipelineConfig, db: CellLibraryDB) -> None:
    """Apply merged configuration into CellLibraryDB.config_params.

    Uses soft validation (per-parameter) and injects keys required by generators.
    """
    merged_params = _soft_validate_and_merge_params(reserved, cfg.overrides)

    # If out_dir provided, ensure report_path present for downstream consumers
    if cfg.out_dir:
        merged_params["report_path"] = cfg.out_dir

    db.update_config(merged_params)
    _set_driver_waveform_env(merged_params.get("driver_waveform"))
    logger.info("Configuration merged into library_db (soft validation)")


def maybe_generate_auto_arcs(db: CellLibraryDB, enable: bool) -> int:
    """Generate timing arcs automatically for all processable cells if enabled."""
    if not enable:
        return 0
    gen = AutoArcGenerator(db)
    count = gen.generate_arcs_for_all_cells()
    logger.info(f"Auto arc generation completed for {count} cells")
    return count


def _resolve_output_directory(db: CellLibraryDB, override: str | None) -> Path:
    """Determine the output directory for deck generation.

    Preference order:
    1. Explicit override passed into PipelineConfig.
    2. Config parameter `extsim_deck_dir` (legacy deck path).
    3. Config parameter `report_path` (general report directory).
    """

    candidates = (
        override,
        db.get_config_param("extsim_deck_dir"),
        db.get_config_param("report_path"),
    )

    for candidate in candidates:
        if candidate:
            return Path(candidate)

    raise ConfigurationError(
        "Output directory is not specified. Use --out or set extsim_deck_dir/report_path in config TCL"
    )


def generate_spice_decks(
    db: CellLibraryDB, out_dir: str | None
) -> tuple[Dict[str, List[str]], str]:
    """Generate SPICE decks for the entire library using the factory.

    - Resolves output directory from CLI overrides or configuration.
    - Ensures get_spice_params() is callable by consumers (will raise if missing).
    """

    resolved_path = _resolve_output_directory(db, out_dir)
    resolved_path.mkdir(parents=True, exist_ok=True)

    # This will raise ConfigurationError if essential params missing
    db.get_spice_params()
    logger.info(f"Generating SPICE decks into: {resolved_path}")
    files = SpiceGeneratorFactory.generate_files_for_library(db, str(resolved_path))
    return files, str(resolved_path)


def export_library_outputs(
    library_db: CellLibraryDB, fallback_dir: str | Path | None = None
) -> Dict[str, str]:
    """Export the populated library database to JSON and Liberty files.

    Preference order for export directory:
        1. `report_path` configuration parameter.
        2. Provided fallback directory (typically deck output directory).
    """

    target_dir = library_db.get_config_param("report_path") or fallback_dir
    if not target_dir:
        return {}

    export_dir = Path(target_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    exporter = LibraryJsonExporter()
    json_path = export_dir / "liberty_data.json"
    exporter.export(library_db, json_path)

    liberty_path = export_dir / "output.lib"
    Json2Liberty().convert(str(json_path), str(liberty_path))

    return {"json": str(json_path), "liberty": str(liberty_path)}


def run_pipeline(cfg: PipelineConfig) -> Dict:
    """Run the end-to-end flow: parse → merge config → (optional) auto arcs → deck generation."""
    try:
        parser, db, reserved = parse_files_and_build_library(cfg)
        apply_config_to_library(reserved, cfg, db)
        auto_cells = maybe_generate_auto_arcs(db, cfg.auto_arc)
        generated_files, resolved_out_dir = generate_spice_decks(db, cfg.out_dir)
        generator_engine = str(db.get_config_param("spice_simulator") or "").lower()
        if generator_engine == "ngspice":
            logger.info("Preprocessing generated decks for ngspice compatibility")
            preprocess_ngspice_decks(resolved_out_dir)
        simulation_summary: Dict[str, Any] | None = None
        if cfg.simulate:
            selected_engine = (
                cfg.simulate_engine
                or db.get_config_param("spice_simulator")
                or "spectre"
            )
            sim_out_dir = Path(
                db.get_config_param("simulate_out_dir") or resolved_out_dir
            )
            sim_out_dir.mkdir(parents=True, exist_ok=True)
            engine_name = selected_engine.lower()
            if engine_name == "mock":
                sim_types = None
            else:
                sim_types = {"hidden", "leakage", "delay", "setup", "hold", "recovery", "removal", "mpw"}
                override_types = _normalize_sim_type_input(
                    db.get_config_param("simulate_types")
                )
                if not override_types:
                    override_types = _normalize_sim_type_input(
                        os.environ.get("ZLIBBOOST_SIM_TYPES")
                    )
                if override_types:
                    sim_types = override_types
            try:
                simulation_summary = simulation_runner.run_for_library(
                    db,
                    output_dir=sim_out_dir,
                    engine=selected_engine,
                    generated_files=generated_files,
                    only_types=sim_types,
                )
            except ConfigurationError:
                logger.warning(
                    "No simulation jobs available for engine=%s with types=%s",
                    selected_engine,
                    sim_types,
                )
                simulation_summary = {
                    "engine": selected_engine,
                    "cells": {},
                    "job_count": 0,
                }
        exports: Dict[str, str] | None = None
        try:
            exports = export_library_outputs(db, fallback_dir=resolved_out_dir)
        except Exception as exc:  # pragma: no cover - logged for visibility
            logger.error("Library export failed: %s", exc, exc_info=True)
        return {
            "cells_auto_generated": auto_cells,
            "generated_files": generated_files,
            "simulation": simulation_summary,
            "stats": db.get_library_stats() if hasattr(db, "get_library_stats") else {},
            "exports": exports,
        }
    except (ConfigError, CommandParseError, ConfigurationError) as e:
        logger.error(f"Pipeline failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in pipeline: {e}")
        raise
def _normalize_sim_type_input(raw: Any) -> set[str]:
    if not raw:
        return set()
    if isinstance(raw, str):
        tokens = raw.replace(",", " ").split()
    elif isinstance(raw, (list, tuple, set)):
        tokens = [str(item) for item in raw]
    else:
        tokens = [str(raw)]
    return {token.strip().lower() for token in tokens if token and token.strip()}
