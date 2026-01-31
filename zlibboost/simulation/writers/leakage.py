"""Leakage power simulation result writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from zlibboost.core.exceptions import ConfigurationError
from zlibboost.core.logger import get_logger
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.simulation.jobs.job import SimulationResult

from .base import ResultWriter

logger = get_logger(__name__)


class LeakageResultWriter(ResultWriter):
    """Persist leakage power measurements into the library database."""

    SIM_TYPES = ("leakage",)

    def __init__(self, library_db: CellLibraryDB | None = None) -> None:
        self._library_db = library_db

    def attach_library(self, library_db: CellLibraryDB) -> None:
        """Inject the library database when not provided at construction."""

        self._library_db = library_db

    def write(self, result: SimulationResult) -> None:
        """Write leakage power metric back to the timing arc."""

        if self._library_db is None:
            raise ConfigurationError("LeakageResultWriter requires a CellLibraryDB instance")

        if result.job.arc is None:
            logger.warning(
                "SimulationResult %s has no associated TimingArc; skipping leakage writeback",
                result.job.job_id,
            )
            return

        leakage_value = self._extract_leakage_value(result.data.get("metrics") or {})
        if leakage_value is None:
            logger.warning(
                "SimulationResult %s has no leakage_power metric; skipping writeback",
                result.job.job_id,
            )
            return

        arc = result.job.arc
        arc.set_leakage_power(leakage_value)

        artifacts = result.data.get("artifacts") or {}
        measurement_file = artifacts.get("measurement_file")
        if measurement_file:
            arc.simulation_metadata["measurement_file"] = measurement_file
        arc.simulation_metadata["engine"] = result.engine
        arc.simulation_metadata["sim_type"] = result.job.sim_type

        self._append_results_log(result, cell_dir=result.job.output_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_leakage_value(metrics: dict) -> Optional[float]:
        """Normalise leakage value from metrics dict."""

        if "leakage_power" not in metrics:
            return None
        value = metrics["leakage_power"]
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            values = [float(v) for v in value]
            return values[0] if values else None
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.debug("Unable to interpret leakage_power metric %r", value)
            return None

    def _append_results_log(self, result: SimulationResult, cell_dir: Path) -> None:
        """Append result summary into results.jsonl for diagnostics."""

        cell_dir = Path(cell_dir)
        sim_dir = cell_dir / "simulation"
        sim_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = sim_dir / "results.jsonl"

        record = {
            "job_id": result.job.job_id,
            "engine": result.engine,
            "status": result.status,
            "sim_type": result.job.sim_type,
            "metrics": result.data.get("metrics", {}),
            "artifacts": result.data.get("artifacts", {}),
        }

        with jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
