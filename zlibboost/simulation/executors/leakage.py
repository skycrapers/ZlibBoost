"""Leakage power simulation executor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from zlibboost.simulation.parsers import (
    LeakageSpectreParser,
    LeakageHspiceParser,
    MeasurementParserRegistry,
    MeasurementPayload,
)

from .base import BaseSimulationExecutor


class LeakageSimulationExecutor(BaseSimulationExecutor):
    """Executor for leakage power characterization decks."""

    def __init__(
        self,
        parser_registry: MeasurementParserRegistry | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._parser_registry = parser_registry or MeasurementParserRegistry(
            [LeakageSpectreParser(), LeakageHspiceParser()]
        )

    def _prepare_environment(self, output_dir: Path) -> None:
        (output_dir / "simulation").mkdir(parents=True, exist_ok=True)

    def _resolve_engine_workdir(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        output_dir: Path,
    ) -> Path:
        arc_id = metadata.get("arc_id", deck_path.stem)
        sim_type = metadata.get("sim_type", "leakage")
        workdir = output_dir / sim_type / arc_id
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir

    def _collect_results(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        output_dir: Path,
        engine_dir: Path,
    ) -> Dict[str, Any]:
        measurement = self._locate_measurement(deck_path, engine_dir)
        arc_id = metadata.get("arc_id", deck_path.stem)

        if not measurement or not measurement.exists():
            return self._build_result_payload(
                metadata,
                arc_id,
                status="missing_measurement",
            )

        artifacts: Dict[str, Any] = {"measurement_file": str(measurement)}
        parser = self._parser_registry.get(self.engine)
        if parser is None:
            return self._build_result_payload(
                metadata,
                arc_id,
                artifacts=artifacts,
                status="completed",
                extra_metadata={"parser_status": "skipped"},
            )

        payload = parser.parse(deck_path, measurement, metadata)
        artifacts.update(payload.artifacts or {})
        if "measurement_file" not in artifacts:
            artifacts["measurement_file"] = str(measurement)

        return self._build_result_payload(
            metadata,
            arc_id,
            metrics=payload.metrics,
            artifacts=artifacts,
            status="completed",
            extra_metadata=payload.metadata,
        )

    def _write_artifacts(
        self,
        result: Dict[str, Any],
        output_dir: Path,
        engine_dir: Path,
    ) -> None:
        sim_dir = output_dir / "simulation"
        sim_dir.mkdir(parents=True, exist_ok=True)
        arc_id = result.get("arc_id", "arc")
        artifact_path = sim_dir / f"{arc_id}_leakage.json"
        artifact_path.write_text(json.dumps(result, indent=2))

    def _locate_measurement(self, deck_path: Path, engine_dir: Path) -> Path | None:
        suffix_map = {
            ".sp": [".measure", ".mt0"],
            ".scs": [".measure"],
        }
        suffixes = suffix_map.get(deck_path.suffix.lower())
        if not suffixes:
            return None
        ordered_suffixes = suffixes
        if self.engine == "hspice":
            ordered_suffixes = [".mt0"] + [s for s in suffixes if s != ".mt0"]
        elif self.engine == "ngspice":
            ordered_suffixes = [".mt0"] + [s for s in suffixes if s != ".mt0"]

        for suffix in ordered_suffixes:
            candidate = engine_dir / f"{deck_path.stem}{suffix}"
            if candidate.exists():
                return candidate
            deck_adjacent = deck_path.with_suffix(suffix)
            if deck_adjacent.exists():
                return deck_adjacent
        return None
