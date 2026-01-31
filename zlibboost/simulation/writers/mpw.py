"""MPW simulation result writer."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List
import re

from zlibboost.core.exceptions import ConfigurationError
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.database.models.timing_arc import TimingArc
from zlibboost.simulation.jobs.job import SimulationResult

from .base import ResultWriter

logger = logging.getLogger(__name__)


class MpwResultWriter(ResultWriter):
    """Persist minimum pulse width measurements back into the library database."""

    SIM_TYPES = ("mpw",)
    _INDEX_PATTERN = re.compile(r"_i1_(\d+)", re.IGNORECASE)

    def __init__(self, library_db: CellLibraryDB | None = None) -> None:
        self._library_db = library_db

    def attach_library(self, library_db: CellLibraryDB) -> None:
        self._library_db = library_db

    def write(self, result: SimulationResult) -> None:
        if self._library_db is None:
            raise ConfigurationError("MpwResultWriter requires a CellLibraryDB instance")

        arc = result.job.arc
        if arc is None:
            logger.warning(
                "SimulationResult %s has no associated TimingArc; skipping MPW writeback",
                result.job.job_id,
            )
            return

        metrics = result.data.get("metrics") or {}
        value = metrics.get("pulse_width")
        if value is None:
            logger.warning(
                "SimulationResult %s has no pulse_width metric; skipping MPW writeback",
                result.job.job_id,
            )
            return
        bound_seconds = (result.data.get("metadata") or {}).get("mpw_search_bound")
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            logger.warning("Invalid MPW pulse width for %s: %s", result.job.job_id, value)
            return
        if bound_seconds:
            try:
                bound_ns = float(bound_seconds) * 1e9
            except (TypeError, ValueError):
                bound_ns = None
            if bound_ns and numeric_value >= 0.999 * bound_ns:
                numeric_value = 0.0
        value = numeric_value

        i1 = self._resolve_index(metrics, "i1") or self._infer_index(
            (result.job.metadata or {}).get("arc_id")
        )
        if i1 is None:
            logger.warning(
                "SimulationResult %s missing MPW index; skipping writeback",
                result.job.job_id,
            )
            return

        cell = self._library_db.get_cell(result.job.cell_name)
        template_name = cell.constraint_template
        if not template_name or template_name not in self._library_db.templates:
            raise ConfigurationError(
                f"Cell '{cell.name}' does not define constraint_template required for MPW arcs"
            )
        template = self._library_db.templates[template_name]
        rows = len(template.index_1)

        vector = self._ensure_vector(arc, rows)
        if not (0 <= i1 < len(vector)):
            logger.warning(
                "MPW index out of bounds for arc %s: i1=%s",
                arc.pin,
                i1,
            )
            return

        vector[i1] = float(value)
        arc.set_mpw_values(vector)

        artifacts = result.data.get("artifacts") or {}
        measurement_file = artifacts.get("measurement_file")
        if measurement_file:
            arc.simulation_metadata["measurement_file"] = measurement_file
        arc.simulation_metadata["engine"] = result.engine
        arc.simulation_metadata["sim_type"] = result.job.sim_type

        optimization = (result.data.get("metadata") or {}).get("optimization")
        if optimization:
            arc.simulation_metadata["optimization"] = optimization

        self._append_results_log(result, result.job.output_dir)

    @staticmethod
    def _resolve_index(metrics: dict, key: str) -> int | None:
        raw = metrics.get(key)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _infer_index(cls, arc_id: str | None) -> int | None:
        if not arc_id:
            return None
        match = cls._INDEX_PATTERN.search(arc_id)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (IndexError, ValueError):
            return None

    def _ensure_vector(self, arc: TimingArc, rows: int) -> List[float]:
        if arc.mpw_values and len(arc.mpw_values) >= rows:
            vector = list(arc.mpw_values)
        else:
            vector = [0.0 for _ in range(rows)]
        while len(vector) < rows:
            vector.append(0.0)
        return vector

    def _append_results_log(self, result: SimulationResult, output_dir: Path) -> None:
        sim_dir = Path(output_dir) / "simulation"
        sim_dir.mkdir(parents=True, exist_ok=True)
        log_path = sim_dir / "results.jsonl"

        record = {
            "job_id": result.job.job_id,
            "engine": result.engine,
            "status": result.status,
            "sim_type": result.job.sim_type,
            "metrics": result.data.get("metrics", {}),
            "artifacts": result.data.get("artifacts", {}),
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
