"""Hidden power simulation result writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional

from zlibboost.core.exceptions import ConfigurationError
from zlibboost.core.logger import get_logger
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.simulation.jobs.job import SimulationResult

from .base import ResultWriter

logger = get_logger(__name__)


class HiddenResultWriter(ResultWriter):
    """Persist hidden power measurements into the library database."""

    SIM_TYPES = ("hidden",)

    def __init__(self, library_db: CellLibraryDB | None = None) -> None:
        self._library_db = library_db

    def attach_library(self, library_db: CellLibraryDB) -> None:
        """Inject the library database when not provided at construction."""

        self._library_db = library_db

    def write(self, result: SimulationResult) -> None:
        """Write hidden power metrics back to the timing arc."""

        if self._library_db is None:
            raise ConfigurationError("HiddenResultWriter requires a CellLibraryDB instance")

        if result.job.arc is None:
            logger.warning(
                "SimulationResult %s has no associated TimingArc; skipping hidden writeback",
                result.job.job_id,
            )
            return

        metrics = result.data.get("metrics") or {}
        hidden_values = metrics.get("hidden_power")
        if not hidden_values:
            logger.warning(
                "SimulationResult %s has no hidden_power metrics; skipping writeback",
                result.job.job_id,
            )
            return

        cell = self._library_db.get_cell(result.job.cell_name)
        template_name = cell.power_template
        if not template_name:
            raise ConfigurationError(
                f"Cell '{cell.name}' does not define power_template required for hidden arcs"
            )
        template = self._library_db.get_template(template_name)

        power_matrix, derived_template = self._build_power_matrix(
            hidden_values, template.index_1, template.index_2, template.name
        )
        arc = result.job.arc
        arc.set_power_values(power_matrix)

        if derived_template:
            arc.metadata.setdefault("power_template_override", derived_template)

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
    def _build_power_matrix(
        self,
        values: Iterable[float],
        index_1: List[float],
        index_2: List[float],
        base_template: str,
    ) -> tuple[List[List[float]], Optional[str]]:
        """Shape metrics into the power template matrix."""

        values_list = list(values)
        rows = len(index_1)
        cols = len(index_2)
        if rows == 0 or cols == 0:
            raise ConfigurationError("Power template indices cannot be empty for hidden arcs")

        total_required = rows * cols
        matrix = [[0.0 for _ in range(cols)] for _ in range(rows)]
        derived_name: Optional[str] = None

        if not values_list:
            return matrix, derived_name

        if len(values_list) >= total_required:
            for idx, value in enumerate(values_list[:total_required]):
                row = idx // cols
                col = idx % cols
                matrix[row][col] = value
            return matrix, derived_name

        if len(values_list) == rows:
            matrix = [[value] for value in values_list]
            derived_name = self._build_flat_template_name(base_template, rows)
            return matrix, derived_name

        if len(values_list) == cols:
            for col, value in enumerate(values_list):
                matrix[0][col] = value
            return matrix, derived_name

        # Fallback: sequentially fill the first column until values are exhausted.
        for row, value in enumerate(values_list[:rows]):
            matrix[row][0] = value
        return matrix, derived_name

    @staticmethod
    def _build_flat_template_name(base: str, rows: int) -> str:
        import re

        match = re.match(r"^(.*)_([0-9]+)x([0-9]+)(_.+)?$", base)
        if match:
            prefix = match.group(1)
            suffix = match.group(4) or ""
            return f"{prefix}_{rows}x1{suffix}"

        fallback = re.match(r"^(.*)_([0-9]+)$", base)
        if fallback:
            prefix = fallback.group(1)
            suffix = fallback.group(2)
            return f"{prefix}_{rows}x1_{suffix}"

        return f"{base}_{rows}x1"

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
