"""Constraint simulation result writer."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List
import math

from zlibboost.core.exceptions import ConfigurationError
from zlibboost.core.logger import get_logger
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.database.models.timing_arc import TimingArc
from zlibboost.simulation.jobs.job import SimulationResult

from .base import ResultWriter

logger = get_logger(__name__)


class ConstraintResultWriter(ResultWriter):
    """Persist setup/hold/recovery/removal constraint measurements."""

    SIM_TYPES = ("setup", "hold", "recovery", "removal")

    _INDEX_PATTERN = re.compile(r"_i1_(\d+)_i2_(\d+)", re.IGNORECASE)

    def __init__(self, library_db: CellLibraryDB | None = None) -> None:
        self._library_db = library_db

    def attach_library(self, library_db: CellLibraryDB) -> None:
        self._library_db = library_db

    def write(self, result: SimulationResult) -> None:
        if self._library_db is None:
            raise ConfigurationError("ConstraintResultWriter requires a CellLibraryDB instance")

        arc = result.job.arc
        if arc is None:
            logger.warning(
                "SimulationResult %s has no associated TimingArc; skipping constraint writeback",
                result.job.job_id,
            )
            return

        metrics = result.data.get("metrics") or {}
        value = metrics.get("constraint")
        if value is None:
            logger.warning(
                "SimulationResult %s has no constraint metric; skipping writeback",
                result.job.job_id,
            )
            return

        arc_identifier = (result.job.metadata or {}).get("arc_id")
        i1 = self._resolve_index(metrics, "i1") or self._infer_index(arc_identifier, 1)
        i2 = self._resolve_index(metrics, "i2") or self._infer_index(arc_identifier, 2)
        if i1 is None or i2 is None:
            logger.warning(
                "SimulationResult %s missing LUT indices; skipping writeback",
                result.job.job_id,
            )
            return

        cell = self._library_db.get_cell(result.job.cell_name)
        template_name = cell.constraint_template
        if not template_name or template_name not in self._library_db.templates:
            raise ConfigurationError(
                f"Cell '{cell.name}' does not define constraint_template required for constraint arcs"
            )
        template = self._library_db.templates[template_name]

        matrix = self._ensure_matrix(arc, len(template.index_1), len(template.index_2))

        if not (0 <= i1 < len(matrix)) or not (0 <= i2 < len(matrix[0])):
            logger.warning(
                "Constraint indices out of bounds for arc %s: (i1=%s, i2=%s)",
                arc.get_arc_key() if hasattr(arc, "get_arc_key") else arc.pin,
                i1,
                i2,
            )
            return

        matrix[i1][i2] = float(value)
        self._ensure_unique_entries(matrix)
        arc.set_constraint_values(matrix)

        artifacts = result.data.get("artifacts") or {}
        measurement_file = artifacts.get("measurement_file")
        if measurement_file:
            arc.simulation_metadata["measurement_file"] = measurement_file
        arc.simulation_metadata["engine"] = result.engine
        arc.simulation_metadata["sim_type"] = result.job.sim_type
        arc.simulation_metadata["optimization"] = {
            "time_shift": metrics.get("time_shift"),
            "iterations": metrics.get("optimization_iterations"),
            "target": metrics.get("optimization_target"),
            "converged": metrics.get("optimization_converged"),
        }

        self._append_results_log(result, result.job.output_dir)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_index(metrics: dict, key: str) -> int | None:
        raw = metrics.get(key)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _infer_index(self, arc_id: str | None, position: int) -> int | None:
        if not arc_id:
            return None
        match = self._INDEX_PATTERN.search(arc_id)
        if not match:
            return None
        try:
            return int(match.group(position))
        except (IndexError, ValueError):
            return None

    def _ensure_matrix(self, arc: TimingArc, rows: int, cols: int) -> List[List[float]]:
        if arc.constraint_values and len(arc.constraint_values) >= rows:
            # Ensure each row has correct column count
            for row in arc.constraint_values:
                if len(row) < cols:
                    row.extend([0.0] * (cols - len(row)))
            while len(arc.constraint_values) < rows:
                arc.constraint_values.append([0.0] * cols)
            return arc.constraint_values

        matrix = [[0.0 for _ in range(cols)] for _ in range(rows)]
        arc.constraint_values = matrix
        return matrix

    def _ensure_unique_entries(self, matrix: List[List[float]]) -> None:
        epsilon = 1e-6
        seen: List[float] = []
        for row_idx, row in enumerate(matrix):
            for col_idx, raw_value in enumerate(row):
                value = float(raw_value)
                offset = 0.0
                while any(math.isclose(value + offset, existing, rel_tol=1e-12, abs_tol=1e-12) for existing in seen):
                    offset += epsilon
                adjusted = round(value + offset, 6)
                row[col_idx] = adjusted
                seen.append(adjusted)

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
