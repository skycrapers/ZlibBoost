"""Delay simulation result writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional

from zlibboost.core.exceptions import ConfigurationError
from zlibboost.core.logger import get_logger
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.database.models.timing_arc import TableType, TimingArc
from zlibboost.simulation.jobs.job import SimulationResult

from .base import ResultWriter

logger = get_logger(__name__)


class DelayResultWriter(ResultWriter):
    """Persist delay/transition measurements into the library database."""

    SIM_TYPES = ("delay",)

    def __init__(self, library_db: CellLibraryDB | None = None) -> None:
        self._library_db = library_db

    def attach_library(self, library_db: CellLibraryDB) -> None:
        self._library_db = library_db

    def write(self, result: SimulationResult) -> None:
        if self._library_db is None:
            raise ConfigurationError("DelayResultWriter requires a CellLibraryDB instance")

        if result.job.arc is None:
            logger.warning(
                "SimulationResult %s has no associated TimingArc; skipping delay writeback",
                result.job.job_id,
            )
            return

        metrics = result.data.get("metrics") or {}
        if not metrics:
            logger.warning(
                "SimulationResult %s has no metrics; skipping delay writeback",
                result.job.job_id,
            )
            return

        cell = self._library_db.get_cell(result.job.cell_name)
        delay_template_name = cell.delay_template
        power_template_name = cell.power_template
        if not delay_template_name or delay_template_name not in self._library_db.templates:
            raise ConfigurationError(
                f"Cell '{cell.name}' does not define delay_template required for delay arcs"
            )

        delay_template = self._library_db.templates[delay_template_name]
        power_template = (
            self._library_db.templates[power_template_name]
            if power_template_name and power_template_name in self._library_db.templates
            else None
        )

        arc = result.job.arc
        delay_values = metrics.get("delay")
        if delay_values:
            arc.set_delay_values(
                self._reshape_matrix(delay_values, delay_template.index_1, delay_template.index_2)
            )

        transition_values = metrics.get("transition")
        if transition_values:
            transition_matrix = self._reshape_matrix(
                transition_values, delay_template.index_1, delay_template.index_2
            )
            arc.set_transition_values(transition_matrix)
            self._propagate_transition_values(cell, arc, transition_matrix)

        switching_power = metrics.get("switching_power")
        if switching_power and power_template is not None:
            power_matrix = self._reshape_matrix(
                switching_power, power_template.index_1, power_template.index_2
            )
            self._populate_power_arc(cell, arc, power_matrix)

        self._update_capacitances(cell, arc.related_pin, metrics)

        artifacts = result.data.get("artifacts") or {}
        measurement_file = artifacts.get("measurement_file")
        if measurement_file:
            arc.simulation_metadata["measurement_file"] = measurement_file
        arc.simulation_metadata["engine"] = result.engine
        arc.simulation_metadata["sim_type"] = result.job.sim_type

        self._append_results_log(result, cell_dir=result.job.output_dir)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _reshape_matrix(
        values: Iterable[float],
        index_1: List[float],
        index_2: List[float],
    ) -> List[List[float]]:
        flat = list(float(v) for v in values)
        rows = len(index_1)
        cols = len(index_2)
        if rows == 0 or cols == 0:
            raise ConfigurationError("Delay template indices cannot be empty")
        total = rows * cols
        if len(flat) < total:
            padded = flat + [flat[-1]] * (total - len(flat))
        else:
            padded = flat[:total]
        matrix = []
        for row in range(rows):
            start = row * cols
            matrix.append(padded[start : start + cols])
        return matrix

    def _update_capacitances(
        self,
        cell,
        related_pin: str,
        metrics: dict,
    ) -> None:
        if related_pin not in cell.pins:
            return

        pin = cell.pins[related_pin]
        rise_cap = self._as_float_list(metrics.get("rise_cap"))
        fall_cap = self._as_float_list(metrics.get("fall_cap"))
        input_rise = self._as_float_list(metrics.get("input_rise_cap"))
        input_fall = self._as_float_list(metrics.get("input_fall_cap"))

        if rise_cap:
            pin.metadata["rise_capacitance_range"] = [min(rise_cap), max(rise_cap)]
            pin.metadata["rise_capacitance"] = max(rise_cap)
        if fall_cap:
            pin.metadata["fall_capacitance_range"] = [min(fall_cap), max(fall_cap)]
            pin.metadata["fall_capacitance"] = max(fall_cap)
        if input_rise or input_fall:
            combined = (input_rise or []) + (input_fall or [])
            if combined:
                pin.capacitance = max(combined)

        extra_caps = metrics.get("input_caps") or {}
        for pin_name, cap_info in extra_caps.items():
            resolved_name = self._resolve_measure_pin(cell, pin_name)
            if resolved_name is None or resolved_name == related_pin:
                continue
            target_pin = cell.pins[resolved_name]
            rise_values = self._as_float_list(cap_info.get("rise"))
            fall_values = self._as_float_list(cap_info.get("fall"))
            if rise_values:
                target_pin.metadata["rise_capacitance_range"] = [min(rise_values), max(rise_values)]
                target_pin.metadata["rise_capacitance"] = max(rise_values)
            if fall_values:
                target_pin.metadata["fall_capacitance_range"] = [min(fall_values), max(fall_values)]
                target_pin.metadata["fall_capacitance"] = max(fall_values)
            combined = (rise_values or []) + (fall_values or [])
            if combined:
                target_pin.capacitance = max(combined)

    @staticmethod
    def _resolve_measure_pin(cell, label: str) -> str | None:
        """Map measurement label back to a real pin name (case-insensitive)."""

        if label in cell.pins:
            return label

        candidates = [label.upper(), label.lower()]
        for candidate in candidates:
            if candidate in cell.pins:
                return candidate

        def sanitize(value: str) -> str:
            return "".join(ch if ch.isalnum() else "_" for ch in value).lower()

        normalized = sanitize(label)
        for pin_name in cell.pins:
            if sanitize(pin_name) == normalized:
                return pin_name
        return None

    @staticmethod
    def _as_float_list(values: Optional[Iterable[float]]) -> List[float]:
        if values is None:
            return []
        return [float(v) for v in values]

    def _append_results_log(self, result: SimulationResult, cell_dir: Path) -> None:
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

    def _populate_power_arc(self, cell, delay_arc, matrix: List[List[float]]) -> None:
        target_pin = delay_arc.pin
        related_pin = delay_arc.related_pin
        if not target_pin or target_pin not in cell.pins or not related_pin:
            return

        power_table_type = self._resolve_power_table_type(delay_arc.table_type)
        if power_table_type is None:
            return

        power_arc = self._find_power_arc(
            cell,
            target_pin,
            related_pin,
            power_table_type,
            delay_arc.condition_dict,
        )
        if power_arc is None:
            logger.warning(
                "No switching power arc found for cell=%s output=%s related=%s type=%s; skipping writeback",
                cell.name,
                target_pin,
                related_pin,
                power_table_type,
            )
            return

        power_arc.set_power_values(matrix)

    @staticmethod
    def _resolve_power_table_type(table_type: Optional[str]) -> Optional[str]:
        if table_type is None:
            return None
        table_type_lower = table_type.lower()
        if table_type_lower in {
            TableType.CELL_RISE.value,
            TableType.RISE_TRANSITION.value,
        }:
            return TableType.RISE_POWER.value
        if table_type_lower in {
            TableType.CELL_FALL.value,
            TableType.FALL_TRANSITION.value,
        }:
            return TableType.FALL_POWER.value
        return None

    @staticmethod
    def _find_power_arc(
        cell,
        pin: str,
        related_pin: str,
        table_type: str,
        condition: Optional[dict],
    ) -> Optional[TimingArc]:
        candidates = [
            arc
            for arc in cell.timing_arcs
            if arc.pin == pin and arc.related_pin == related_pin and arc.table_type == table_type
        ]
        if not candidates:
            return None
        if condition:
            for arc in candidates:
                if arc.condition_dict == condition:
                    return arc
        return candidates[0]

    def _propagate_transition_values(
        self,
        cell,
        delay_arc: TimingArc,
        matrix: List[List[float]],
    ) -> None:
        """
        Copy transition matrices to any derived rise/fall transition arcs.

        Sequential arc extractors may have created explicit transition arcs in
        addition to the primary cell_{rise,fall} arc. We do not run separate
        simulations for those arcs, so propagate results here to keep the data
        model consistent with legacy outputs.
        """

        if delay_arc.table_type == TableType.CELL_RISE.value:
            target_table_type = TableType.RISE_TRANSITION.value
        elif delay_arc.table_type == TableType.CELL_FALL.value:
            target_table_type = TableType.FALL_TRANSITION.value
        else:
            return

        related_pin = delay_arc.related_pin
        pin = delay_arc.pin
        if not related_pin or not pin:
            return

        candidates = [
            arc
            for arc in cell.timing_arcs
            if arc.pin == pin
            and arc.related_pin == related_pin
            and arc.table_type == target_table_type
        ]
        if not candidates:
            return

        for arc in candidates:
            if arc.condition_dict != delay_arc.condition_dict:
                continue
            arc.set_transition_values(matrix)
            arc.metadata.setdefault("derived_from", delay_arc.table_type)
