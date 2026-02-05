"""
Library database exporter for legacy JSON format.

This module provides a high-level OOP structure for converting the modern
`CellLibraryDB` data model into the legacy JSON schema expected by the
`Json2Liberty` converter. The concrete serialization routines will be
implemented in subsequent increments; for now we establish the interfaces and
core scaffolding so that tests and future work can plug in the real logic.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import copy
import json
import logging
import math
import re

from zlibboost.database.library_db import CellLibraryDB
from zlibboost.database.models.cell import Cell, PinInfo, PinCategory
from zlibboost.database.models.timing_arc import TableType, TimingType

logger = logging.getLogger(__name__)


@dataclass
class ExporterConfig:
    """
    Configuration to control JSON export behaviour.

    Attributes:
        pretty: Whether to pretty-print the intermediate JSON file.
        indent: Indentation level when pretty printing is enabled.
    """

    pretty: bool = True
    indent: int = 4


class JsonCleaner:
    """Utility helpers to post-process the generated JSON structure."""

    @staticmethod
    def remove_empty(data: Any) -> Any:
        """
        Recursively remove empty dictionaries, lists, or None values.

        This mirrors the behaviour in `legacy/spice/result_analyzer.py` and
        ensures the resulting JSON does not contain redundant placeholders.
        """
        if isinstance(data, dict):
            return {
                key: JsonCleaner.remove_empty(value)
                for key, value in data.items()
                if value not in (None, {}, [], "")
            }
        if isinstance(data, list):
            return [
                JsonCleaner.remove_empty(item)
                for item in data
                if item not in (None, {}, [], "")
            ]
        return data

    @staticmethod
    def compress_lists(json_string: str) -> str:
        """
        Compact array representations to match legacy formatting.

        The legacy pipeline removes whitespace within square brackets after the
        JSON file is written. We reproduce that behaviour here so downstream
        diffs stay minimal.
        """
        pattern = re.compile(r"(\[[^\[\]]*?\])")
        return pattern.sub(lambda match: match.group(0).replace("\n", "").replace(" ", ""), json_string)


class TemplateSerializer:
    """Convert Template objects into legacy JSON nodes."""

    def __init__(self) -> None:
        self._derived_power_templates: Dict[str, str] = {}
        self._derived_constraint_templates: Dict[str, str] = {}
        self._template_specs: Dict[str, Dict[str, Any]] = {}

    def build_template_nodes(self, library_db: CellLibraryDB) -> Dict[str, Dict[str, Any]]:
        """
        Serialize templates grouped by type.

        Returns:
            Mapping with keys `lu_table_templates` and `power_lut_templates`.
        """
        lu_table_templates: Dict[str, Dict[str, Any]] = {}
        power_lut_templates: Dict[str, Dict[str, Any]] = {}

        for template in library_db.templates.values():
            template_node = {
                "index_1": list(template.index_1),
                "index_2": list(template.index_2),
            }

            if template.template_type == "delay":
                template_node["variable_1"] = "input_net_transition"
                template_node["variable_2"] = "total_output_net_capacitance"
                lu_table_templates[template.name] = template_node
                self._template_specs[template.name] = {
                    "index_1": list(template.index_1),
                    "index_2": list(template.index_2),
                    "variable_1": "input_net_transition",
                    "variable_2": "total_output_net_capacitance",
                }
            elif template.template_type == "constraint":
                template_node["variable_1"] = "constrained_pin_transition"
                if template.index_2:
                    template_node["variable_2"] = "related_pin_transition"
                else:
                    template_node.pop("index_2", None)

                derived_from = template.metadata.get("derived_from")
                if derived_from:
                    spec = {
                        "index_1": list(template.index_1),
                        "index_2": list(template.index_2),
                        "variable_1": "constrained_pin_transition",
                    }
                    if template.index_2:
                        spec["variable_2"] = "related_pin_transition"
                    lu_table_templates[template.name] = template_node
                    self._template_specs[template.name] = spec
                    self._derived_constraint_templates[derived_from] = template.name
                    continue

                lu_table_templates[template.name] = template_node
                spec = {
                    "index_1": list(template.index_1),
                    "index_2": list(template.index_2),
                    "variable_1": "constrained_pin_transition",
                }
                if template.index_2:
                    spec["variable_2"] = "related_pin_transition"
                self._template_specs[template.name] = spec

                derived_name = template.metadata.get("derived_flat_template")
                if derived_name:
                    self._derived_constraint_templates[template.name] = derived_name
            elif template.template_type == "power":
                template_node["variable_1"] = "input_transition_time"
                self._template_specs[template.name] = {
                    "index_1": list(template.index_1),
                    "index_2": list(template.index_2),
                    "variable_1": "input_transition_time",
                    "variable_2": "total_output_net_capacitance" if template.index_2 else None,
                }

                derived_from = template.metadata.get("derived_from")
                if derived_from:
                    template_node["index_1"] = list(template.index_1)
                    power_lut_templates[template.name] = template_node
                    self._derived_power_templates[derived_from] = template.name
                    continue

                template_node["index_1"] = list(template.index_1)

                if template.index_2:
                    template_node["variable_2"] = "total_output_net_capacitance"
                    template_node["index_2"] = list(template.index_2)

                power_lut_templates[template.name] = template_node

                derived_name = template.metadata.get("derived_flat_template")
                if derived_name:
                    self._derived_power_templates[template.name] = derived_name

        self._maybe_add_mpw_constraint_template(library_db, lu_table_templates)

        return {
            "lu_table_templates": lu_table_templates,
            "power_lut_templates": power_lut_templates,
        }

    def _maybe_add_mpw_constraint_template(
        self,
        library_db: CellLibraryDB,
        lu_table_templates: Dict[str, Dict[str, Any]],
    ) -> None:
        """Emit Liberate-style MPW 1-D template when a 3-point constraint grid exists."""

        mpw_name = "mpw_constraint_template_3x3"
        if mpw_name in lu_table_templates:
            return

        base_constraint = library_db.templates.get("constraint_template_3x3")
        if not base_constraint:
            return
        if base_constraint.template_type != "constraint":
            return
        if not base_constraint.index_1 or len(base_constraint.index_1) != 3:
            return

        lu_table_templates[mpw_name] = {
            "variable_1": "constrained_pin_transition",
            "index_1": list(base_constraint.index_1),
        }
        self._template_specs[mpw_name] = {
            "index_1": list(base_constraint.index_1),
            "index_2": [],
            "variable_1": "constrained_pin_transition",
            "variable_2": None,
        }

    def get_flat_power_template(self, base_name: str) -> Optional[str]:
        return self._derived_power_templates.get(base_name)

    def get_flat_constraint_template(self, base_name: str) -> Optional[str]:
        return self._derived_constraint_templates.get(base_name)

    def get_template_spec(self, name: str) -> Optional[Dict[str, Any]]:
        return self._template_specs.get(name)

    @staticmethod
    def _build_derived_power_template_name(base_name: str, rows: int) -> str:
        import re

        match = re.match(r"^(.*)_([0-9]+)x([0-9]+)(_.+)?$", base_name)
        if match:
            prefix = match.group(1)
            suffix = match.group(4) or ""
            return f"{prefix}_{rows}x1{suffix}"

        fallback_match = re.match(r"^(.*)_([0-9]+)$", base_name)
        if fallback_match:
            prefix = fallback_match.group(1)
            suffix = fallback_match.group(2)
            return f"{prefix}_{rows}x1_{suffix}"

        return f"{base_name}_{rows}x1"


class CellSerializer:
    """Convert Cell objects into legacy JSON nodes."""

    _SIMPLE_INVERSION_PATTERN = re.compile(
        r"^[!~]\s*\(?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)?\s*$"
    )

    def __init__(self, template_serializer: TemplateSerializer | None = None) -> None:
        self._template_serializer = template_serializer or TemplateSerializer()
        self._timing_table_cache: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}

    @staticmethod
    def _normalize_state_variable_name(name: str) -> str:
        """Return the base (non-complement) name for a sequential state variable."""
        candidate = str(name or "").strip()
        if candidate.endswith("_N"):
            candidate = candidate[:-2]
        return candidate

    def _resolve_state_variables(self, cell: Cell) -> Tuple[str, str]:
        """
        Return the (state, state_complement) variable names for Liberty sequential groups.

        Liberty requires two variables in ff()/latch(): one for the stored state and one
        for its complement. We keep the internal state pin name when available (e.g.
        Q_state) and derive the complement as <state>_N (e.g. Q_state_N). When no internal
        pin exists (e.g. latch cells that do not model state explicitly), fall back to
        <primary_output>_state.
        """
        internal_pins = [pin for pin in cell.get_internal_pins() if pin]
        if internal_pins:
            state = self._normalize_state_variable_name(internal_pins[0])
        else:
            outputs = list(cell.get_output_pins())
            primary_output = "Q" if "Q" in outputs else (outputs[0] if outputs else "state")
            state = f"{primary_output}_state"
        return state, f"{state}_N"

    @classmethod
    def _serialize_sequential_output_function(cls, cell: Cell, expr: str) -> str:
        """
        Normalize sequential output functions to reference explicit state variables.

        When a cell models internal state pins (e.g. Q_state), downstream Liberty should
        reference that state variable and its explicit complement (<state>_N) instead of
        using negation in-place.
        """
        if not expr:
            return ""

        # Only normalize for sequential cells; combinational outputs should keep their original expressions.
        if not cell.is_sequential:
            return expr

        internal_state_pins = [pin for pin in cell.get_internal_pins() if pin]
        if not internal_state_pins:
            return expr

        state_pin = internal_state_pins[0]
        normalized = expr.strip()
        if normalized == state_pin or normalized == f"({state_pin})":
            return state_pin

        state_n = f"{state_pin}_N"
        if normalized == state_n or normalized == f"({state_n})":
            return state_n

        match = cls._SIMPLE_INVERSION_PATTERN.match(normalized)
        if match and match.group(1) == state_pin:
            return state_n
        return expr

    @staticmethod
    def _serialize_async_timing_type(cell: Cell, related_pin: str, default: str = "clear") -> str:
        """
        Liberty expects async set/reset arcs to use timing_type {clear,preset}.

        Internally we store both as TimingType.ASYNC; choose the proper Liberty
        string based on pin categories.
        """
        if related_pin in set(cell.get_reset_pins()):
            return "clear"
        if related_pin in set(cell.get_set_pins()):
            return "preset"
        # Backward-compatible fallback (legacy json2lib did async->clear blindly).
        return default

    @staticmethod
    def _constraint_candidate_stats(arc) -> Tuple[bool, int, int, Tuple[Tuple[str, str], ...]]:
        """
        Score a constraint-arc candidate for export grouping.

        Constraint arc extraction can produce multiple arc variants that share the
        same Liberty-visible grouping key (pin/related/timing_type/when) but differ
        in internal/output conditions. Prefer variants whose optimizer converged.
        """
        optimization = (getattr(arc, "simulation_metadata", {}) or {}).get("optimization") or {}
        converged = bool(optimization.get("converged"))

        matrix = getattr(arc, "constraint_values", None) or []
        finite_count = 0
        for row in matrix:
            if not isinstance(row, list):
                continue
            for value in row:
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(numeric):
                    continue
                finite_count += 1

        outputs = getattr(arc, "output_condition_dict", {}) or {}
        output_key = tuple(sorted((str(pin), str(val)) for pin, val in outputs.items()))
        return (converged, finite_count, len(output_key), output_key)

    @classmethod
    def _is_better_constraint_candidate(
        cls,
        new_stats: Tuple[bool, int, int, Tuple[Tuple[str, str], ...]],
        old_stats: Tuple[bool, int, int, Tuple[Tuple[str, str], ...]] | None,
    ) -> bool:
        if old_stats is None:
            return True
        new_converged, new_finite, new_output_count, new_key = new_stats
        old_converged, old_finite, old_output_count, old_key = old_stats

        if new_converged != old_converged:
            return new_converged and not old_converged
        if new_finite != old_finite:
            return new_finite > old_finite
        if new_output_count != old_output_count:
            return new_output_count > old_output_count
        # Deterministic fallback: prefer lexicographically smaller output conditions.
        return new_key < old_key

    def _select_best_constraint_payload(
        self,
        timing_entry: Dict[str, Any],
        arc,
        table_payload: Dict[str, Any],
    ) -> None:
        selection = timing_entry.setdefault("_constraint_selection", {})
        stats = self._constraint_candidate_stats(arc)
        table_key = arc.table_type

        current = selection.get(table_key)
        current_stats = None if current is None else current.get("stats")
        if self._is_better_constraint_candidate(stats, current_stats):
            selection[table_key] = {
                "stats": stats,
                "payload": table_payload,
            }

    def build_cell_nodes(self, library_db: CellLibraryDB) -> Dict[str, Any]:
        """
        Serialize every cell in the library database.

        Returns:
            Dictionary keyed by cell name with legacy-compliant payloads.
        """
        cell_nodes: Dict[str, Any] = {}
        for cell_name, cell in library_db.cells.items():
            cell_nodes[cell_name] = self._serialize_cell(cell, library_db)
        return cell_nodes

    def _serialize_cell(self, cell: Cell, library_db: CellLibraryDB) -> Dict[str, Any]:
        cell_node: Dict[str, Any] = {
            "area": cell.metadata.get("area"),
            "cell_leakage_power": cell.metadata.get("cell_leakage_power"),
            "pg_pins": {},
            "leakage_powers": [],
            "pins": {},
        }

        # Serialize pins up-front to provide containers for timing/power data.
        for pin_name, pin in cell.pins.items():
            if pin.direction == "internal" or pin.has_category(PinCategory.INTERNAL):
                continue
            cell_node["pins"][pin_name] = self._serialize_pin(cell, pin)

        # Populate timing/internal power/leakage using arcs
        self._populate_arc_data(cell, library_db, cell_node)

        latch_payload = self._build_latch_payload(cell)
        if latch_payload:
            state_var, state_var_n = self._resolve_state_variables(cell)
            cell_node[f"latch({state_var},{state_var_n})"] = latch_payload
        else:
            state_var, state_var_n = self._resolve_state_variables(cell)
            ff_payload = self._build_ff_payload(cell, state_var)
            if ff_payload:
                cell_node[f"ff({state_var},{state_var_n})"] = ff_payload

        return cell_node

    def _build_latch_payload(self, cell: Cell) -> Optional[Dict[str, str]]:
        """Build legacy latch payload from cell pin categories."""
        if not cell.is_latch:
            return None

        clock_pins = list(cell.get_clock_pins())
        clock_negative_pins = list(cell.get_clock_negative_pins())
        if clock_pins or clock_negative_pins:
            return None

        data_pins = list(cell.get_data_pins())
        enable_pins = list(cell.get_enable_pins())
        async_pins = set(cell.get_async_pins())
        reset_pins = set(cell.get_reset_pins())
        set_pins = set(cell.get_set_pins())

        data_pin = data_pins[0] if data_pins else None
        enable_pin = enable_pins[0] if enable_pins else None
        if data_pin is None or enable_pin is None:
            return None

        clear_pins = list(async_pins & reset_pins)
        preset_pins = list(async_pins & set_pins)

        latch_payload: Dict[str, str] = {
            "data_in": data_pin,
        }

        enable_expr = enable_pin
        if enable_pin in cell.pins and cell.pins[enable_pin].is_negative:
            enable_expr = f"!{enable_pin}"
        latch_payload["enable"] = enable_expr

        if clear_pins:
            latch_payload["clear"] = f"!{clear_pins[0]}"
        if preset_pins:
            latch_payload["preset"] = f"!{preset_pins[0]}"
        if clear_pins and preset_pins:
            latch_payload["clear_preset_var1"] = "H"
            latch_payload["clear_preset_var2"] = "L"

        return latch_payload

    def _build_ff_payload(self, cell: Cell, state_var: str) -> Optional[Dict[str, str]]:
        """Build legacy ff/latch payload from cell pin categories."""
        if not (cell.is_sequential or cell.has_async_pins):
            return None

        clock_pins = list(cell.get_clock_pins())
        clock_negative_pins = list(cell.get_clock_negative_pins())
        sync_pins = set(cell.get_sync_pins())
        async_pins = set(cell.get_async_pins())
        reset_pins = set(cell.get_reset_pins())
        set_pins = set(cell.get_set_pins())
        data_pins = list(cell.get_data_pins())
        scan_enable_pins = list(cell.get_scan_enable_pins())
        scan_in_pins = list(cell.get_scan_in_pins())
        enable_pins = list(cell.get_enable_pins())

        clear_sync_pins = list(sync_pins & reset_pins)
        preset_sync_pins = list(sync_pins & set_pins)
        clear_pins = list(async_pins & reset_pins)
        preset_pins = list(async_pins & set_pins)

        data_pin = data_pins[0] if data_pins else None
        scan_enable_pin = scan_enable_pins[0] if scan_enable_pins else None
        scan_in_pin = scan_in_pins[0] if scan_in_pins else None
        enable_pin = enable_pins[0] if enable_pins else None
        preset_sync_pin = preset_sync_pins[0] if preset_sync_pins else None
        clear_sync_pin = clear_sync_pins[0] if clear_sync_pins else None

        if data_pin is None and scan_in_pin is None:
            return None

        ff_payload: Dict[str, str] = {}
        if clear_pins:
            ff_payload["clear"] = f"(!{clear_pins[0]})"
        if preset_pins:
            ff_payload["preset"] = f"(!{preset_pins[0]})"

        if clock_pins:
            ff_payload["clocked_on"] = clock_pins[0]
        elif clock_negative_pins:
            ff_payload["clocked_on"] = clock_negative_pins[0]
        elif enable_pin:
            ff_payload["clocked_on"] = enable_pin

        next_state_expr = data_pin
        if preset_sync_pin:
            next_state_expr = f"(!{preset_sync_pin} + {data_pin})"
        if clear_sync_pin:
            next_state_expr = f"({data_pin} * {clear_sync_pin})"
        if preset_sync_pin and clear_sync_pin:
            next_state_expr = f"((!{preset_sync_pin} + {data_pin}) * {clear_sync_pin})"
        if enable_pin:
            next_state_expr = f"(({enable_pin} * {data_pin}) + (!{enable_pin} * {state_var}))"
        if enable_pin and clear_sync_pin:
            next_state_expr = f"(({enable_pin} * {data_pin}) + (!{enable_pin} * {state_var}) * {clear_sync_pin})"
        if scan_enable_pin:
            next_state_expr = f"(({scan_in_pin} * {scan_enable_pin}) + (!{scan_enable_pin} * {data_pin}))"
        if scan_enable_pin and preset_sync_pin:
            next_state_expr = f"(({scan_in_pin} * {scan_enable_pin}) + (!{scan_enable_pin} * (!{preset_sync_pin} + {data_pin})))"
        if scan_enable_pin and clear_sync_pin:
            next_state_expr = f"(({scan_enable_pin} * {scan_in_pin}) +(!{scan_enable_pin}*({data_pin} * {clear_sync_pin})))"
        if scan_enable_pin and preset_sync_pin and clear_sync_pin:
            next_state_expr = f"(({scan_enable_pin} * {scan_in_pin}) + (!{scan_enable_pin}*((!{preset_sync_pin} + {data_pin}) * {clear_sync_pin})))"
        if enable_pin and scan_enable_pin:
            next_state_expr = (
                f"(({scan_in_pin} * {scan_enable_pin}) + (!{scan_enable_pin} * (({enable_pin} * {data_pin}) + (!{enable_pin} * {state_var}))))"
            )
        if enable_pin and scan_enable_pin and clear_sync_pin:
            next_state_expr = (
                f"(({scan_in_pin} * {scan_enable_pin}) + (!{scan_enable_pin} * (({enable_pin} * {data_pin}) + (!{enable_pin} * {state_var})) * {clear_sync_pin}))"
            )

        if next_state_expr:
            ff_payload["next_state"] = next_state_expr

        if ff_payload.get("clear") or ff_payload.get("preset"):
            ff_payload["clear_preset_var1"] = "L"
            ff_payload["clear_preset_var2"] = "L"

        return ff_payload

    def _serialize_pin(self, cell: Cell, pin: PinInfo) -> Dict[str, Any]:
        function_str = ""
        if pin.direction in {"output", "inout", "internal"}:
            func = cell.get_function(pin.name)
            if func:
                function_str = func.original_expr

        if pin.direction in {"output", "inout"} and function_str:
            function_str = self._serialize_sequential_output_function(cell, function_str)

        pin_node: Dict[str, Any] = {
            "direction": pin.direction,
            "function": function_str,
            "capacitance": pin.capacitance,
            "rise_capacitance": pin.metadata.get("rise_capacitance"),
            "rise_capacitance_range": pin.metadata.get("rise_capacitance_range", []),
            "fall_capacitance": pin.metadata.get("fall_capacitance"),
            "fall_capacitance_range": pin.metadata.get("fall_capacitance_range", []),
            "timing": [],
            "internal_power": [],
        }

        if pin.max_capacitance is not None:
            pin_node["capacitance"] = pin.max_capacitance

        return pin_node

    def _populate_arc_data(self, cell: Cell, library_db: CellLibraryDB, cell_node: Dict[str, Any]) -> None:
        timing_groups: Dict[
            Tuple[str, str, str, str],
            Dict[str, Any]
        ] = {}
        power_groups: Dict[
            Tuple[str, str, str],
            Dict[str, Any]
        ] = {}
        leakage_entries: List[Dict[str, Any]] = []

        pins_payload = cell_node["pins"]
        clock_pins = set(cell.get_clock_pins())
        control_pins = clock_pins | set(cell.get_enable_pins()) | set(cell.get_async_pins())
        reset_pins = set(cell.get_reset_pins())
        set_pins = set(cell.get_set_pins())

        for arc in cell.timing_arcs:
            if (
                arc.timing_type == TimingType.MIN_PULSE_WIDTH.value
                and arc.pin not in control_pins
            ):
                continue
            # Skip arcs that do not map to a real pin payload (e.g., '-' placeholders)
            if arc.pin not in pins_payload or arc.pin == "-":
                if arc.table_type == TableType.LEAKAGE_POWER.value:
                    leakage_entries.append(self._serialize_leakage_power(cell, arc))
                continue

            if arc.table_type in {TableType.RISE_POWER.value, TableType.FALL_POWER.value}:
                # Hidden power arcs (input pin power) do not have a related pin, but may need
                # a `when` condition for sequential/output-state-dependent cases.
                is_hidden_power = (
                    arc.timing_type == "hidden"
                    or arc.related_pin in ("", "-", None)
                )
                if is_hidden_power:
                    related_pin = ""
                    when_str = self._format_when(
                        arc.condition_string(cell=cell, include_outputs=True, include_internal=False)
                    )
                else:
                    when_str = self._format_when(arc.condition_string(cell=cell))
                    related_pin = arc.related_pin

                pg_pin = (arc.metadata or {}).get("related_pg_pin", "")
                key = (arc.pin, related_pin, when_str, pg_pin)
                power_entry = power_groups.setdefault(
                    key,
                    {
                        "related_pin": related_pin,
                        "when": when_str,
                        "related_pg_pin": pg_pin,
                    },
                )
                table_key = "rise_power" if arc.table_type == TableType.RISE_POWER.value else "fall_power"
                override_template = arc.metadata.get("power_template_override") if arc.metadata else None
                template_name = override_template or cell.power_template
                table_data = self._build_table(
                    template_name,
                    arc.power_values,
                    library_db,
                )
                if table_data:
                    power_entry[table_key] = table_data
                continue

            if arc.table_type == TableType.LEAKAGE_POWER.value:
                leakage_entries.append(self._serialize_leakage_power(cell, arc))
                continue

            is_min_pulse = arc.timing_type == TimingType.MIN_PULSE_WIDTH.value
            export_timing_type = arc.timing_type
            if arc.timing_type == TimingType.ASYNC.value:
                # Map to Liberty-visible timing_type ("clear"/"preset") based on the control pin.
                if arc.related_pin in reset_pins:
                    export_timing_type = "clear"
                elif arc.related_pin in set_pins:
                    export_timing_type = "preset"
                else:
                    export_timing_type = "clear"
            # MPW arcs store their conditions in condition_dict (arc.condition is empty).
            formatted_when = (
                self._format_when(arc.condition_string(cell=cell))
                if is_min_pulse
                else self._format_when(arc.condition)
            )
            # 对于 rising_edge/falling_edge (时钟触发的 delay)，不使用 when 条件分组
            # 因为 CLK->Q 的延迟与 D 引脚状态无关，应合并为一个 timing 块
            is_clock_edge = arc.timing_type in ('rising_edge', 'falling_edge')
            group_when = "" if is_clock_edge else (formatted_when or "")
            key = (arc.pin, arc.related_pin, export_timing_type, group_when)
            if key not in timing_groups:
                entry = {
                    "related_pin": arc.related_pin,
                    "timing_type": export_timing_type,
                }
                if not is_clock_edge and group_when:
                    entry["when"] = formatted_when
                timing_groups[key] = entry
            timing_entry = timing_groups[key]
            if is_clock_edge:
                timing_entry.pop("when", None)
            elif formatted_when:
                timing_entry.setdefault("when", formatted_when)

            table_payload = self._build_timing_table(cell, arc, library_db)
            if table_payload:
                if is_min_pulse:
                    candidates = timing_entry.setdefault("_mpw_candidates", defaultdict(list))
                    for constraint_key in (
                        TableType.RISE_CONSTRAINT.value,
                        TableType.FALL_CONSTRAINT.value,
                    ):
                        if constraint_key in table_payload:
                            values = table_payload[constraint_key].get("values")
                            if values:
                                candidates[constraint_key].append(list(values))
                    timing_entry.update(table_payload)
                elif arc.table_type in {TableType.RISE_CONSTRAINT.value, TableType.FALL_CONSTRAINT.value}:
                    # Multiple constraint variants can collide in the same Liberty timing() group.
                    # Choose the best candidate instead of last-write-wins.
                    self._select_best_constraint_payload(timing_entry, arc, table_payload)
                else:
                    timing_entry.update(table_payload)

        # Attach grouped timing/power entries back to pins
        for key in sorted(
            timing_groups.keys(),
            key=lambda k: (k[0], k[1] or "", k[2] or "", k[3] or ""),
        ):
            pin_name = key[0]
            entry = timing_groups[key]
            if "_constraint_selection" in entry:
                selection = entry.pop("_constraint_selection", {}) or {}
                for picked in selection.values():
                    payload = picked.get("payload")
                    if payload:
                        entry.update(payload)
            if (
                entry.get("timing_type") == TimingType.MIN_PULSE_WIDTH.value
                and "_mpw_candidates" in entry
            ):
                candidates = entry.pop("_mpw_candidates", None) or {}
                shared_best = self._merge_mpw_vectors(
                    [vec for vectors in candidates.values() for vec in vectors]
                )
                for table_key, vectors in candidates.items():
                    if table_key not in entry:
                        continue
                    merged = self._merge_mpw_vectors(vectors)
                    if not merged:
                        entry.pop(table_key, None)
                        continue
                    if shared_best:
                        merged = [
                            value if value > 0 else shared_best[idx]
                            for idx, value in enumerate(merged)
                        ]
                    if not any(value > 1e-4 for value in merged):
                        entry.pop(table_key, None)
                        continue
                    entry[table_key]["values"] = merged
            self._resolve_timing_placeholders(entry)
            if self._has_timing_payload(entry):
                pins_payload[pin_name]["timing"].append(entry)

        self._append_default_mpw_entries(pins_payload)

        for key in sorted(power_groups.keys(), key=lambda k: (k[0], k[1] or "", k[2] or "", k[3] or "")):
            pin_name = key[0]
            entry = power_groups[key]
            if self._has_power_payload(entry):
                pins_payload[pin_name]["internal_power"].append(entry)

        for pin_name, pin_payload in pins_payload.items():
            self._finalize_timing_entries(cell, pin_name, pin_payload)
            self._finalize_internal_power_entries(pin_payload)

        if leakage_entries:
            leakage_entries.sort(key=lambda entry: entry.get("when", ""))
            cell_node["leakage_powers"] = leakage_entries
            values = [leak["value"] for leak in leakage_entries if leak["value"] is not None]
            if values:
                cell_node["cell_leakage_power"] = sum(values) / len(values)

    def _build_timing_table(self, cell: Cell, arc, library_db: CellLibraryDB) -> Dict[str, Any]:
        table_type = arc.table_type
        template_name = None
        values = None

        payload: Dict[str, Any] = {}

        if table_type in {TableType.CELL_RISE.value, TableType.CELL_FALL.value}:
            template_name = cell.delay_template
            values = arc.delay_values
        elif table_type in {TableType.RISE_TRANSITION.value, TableType.FALL_TRANSITION.value}:
            template_name = cell.delay_template
            values = arc.transition_values
        elif table_type in {TableType.RISE_CONSTRAINT.value, TableType.FALL_CONSTRAINT.value}:
            if arc.timing_type == TimingType.MIN_PULSE_WIDTH.value:
                template_name = self._resolve_mpw_template(cell, library_db)
                values = arc.mpw_values
            else:
                template_name = cell.constraint_template
                values = arc.constraint_values
        else:
            return {}

        if not template_name:
            return {}
        if (
            template_name not in library_db.templates
            and self._template_serializer.get_template_spec(template_name) is None
        ):
            return {}

        table_key = table_type
        table_payload = {}
        fallback_key = (
            arc.pin,
            arc.related_pin,
            arc.timing_type,
            table_type,
            arc.related_transition or "",
            arc.pin_transition or "",
        )

        table = self._build_table(template_name, values, library_db)
        if table:
            if "values" in table:
                self._cache_timing_table(fallback_key, table)
            table_payload[table_key] = table
        else:
            cached = self._timing_table_cache.get(fallback_key)
            if cached:
                table_payload[table_key] = copy.deepcopy(cached)

        if table_type == TableType.CELL_RISE.value and arc.transition_values:
            transition_table = self._build_table(template_name, arc.transition_values, library_db)
            if transition_table:
                self._cache_timing_table(
                    (arc.pin, arc.related_pin, arc.timing_type, TableType.RISE_TRANSITION.value, arc.related_transition or "", arc.pin_transition or ""),
                    transition_table,
                )
                table_payload[TableType.RISE_TRANSITION.value] = transition_table
        elif table_type == TableType.CELL_FALL.value and arc.transition_values:
            transition_table = self._build_table(template_name, arc.transition_values, library_db)
            if transition_table:
                self._cache_timing_table(
                    (arc.pin, arc.related_pin, arc.timing_type, TableType.FALL_TRANSITION.value, arc.related_transition or "", arc.pin_transition or ""),
                    transition_table,
                )
                table_payload[TableType.FALL_TRANSITION.value] = transition_table

        return table_payload

    def _build_table(
        self,
        template_name: Optional[str],
        values: Optional[Any],
        library_db: CellLibraryDB,
    ) -> Optional[Dict[str, Any]]:
        template = library_db.templates.get(template_name)
        if not template:
            template = self._template_serializer.get_template_spec(template_name)
        if not template:
            return None

        index_1 = list(template.index_1 if hasattr(template, "index_1") else template.get("index_1", []))
        index_2 = list(template.index_2 if hasattr(template, "index_2") else template.get("index_2", []))

        def _flatten_scalar_rows(matrix: List[List[float]]) -> List[float] | None:
            flattened: List[float] = []
            for row in matrix:
                if isinstance(row, list) and len(row) == 1:
                    flattened.append(row[0])
                else:
                    return None
            return flattened

        serializable: Dict[str, Any] = {"template": template_name, "index_1": index_1}
        if index_2:
            serializable["index_2"] = index_2

        # Export structural placeholders even when values are missing. Unit tests and the
        # legacy JSON schema expect timing/power tables to exist once an arc exists.
        if values is None or (isinstance(values, list) and not values):
            return serializable

        sanitized_values = self._sanitize_table_values(values)
        if sanitized_values is None:
            return None

        if isinstance(sanitized_values, list) and sanitized_values and isinstance(sanitized_values[0], list):
            flattened = _flatten_scalar_rows(sanitized_values)
            if flattened is not None:
                derived = self._template_serializer.get_flat_power_template(template_name)
                if not derived:
                    derived = self._template_serializer.get_flat_constraint_template(template_name)
                serializable["template"] = derived or template_name
                serializable.pop("index_2", None)
                serializable["values"] = flattened
            else:
                serializable["values"] = sanitized_values
        else:
            serializable["values"] = sanitized_values  # type: ignore[assignment]

        return serializable

    def _resolve_mpw_template(self, cell: Cell, library_db: CellLibraryDB) -> Optional[str]:
        mpw_name = "mpw_constraint_template_3x3"
        if library_db.templates.get(mpw_name) is not None:
            return mpw_name
        if self._template_serializer.get_template_spec(mpw_name) is not None:
            return mpw_name

        base = cell.constraint_template
        if not base:
            return None
        derived = self._template_serializer.get_flat_constraint_template(base)
        if derived and (
            derived in library_db.templates
            or self._template_serializer.get_template_spec(derived) is not None
        ):
            return derived
        return base

    @staticmethod
    def _mpw_values_to_matrix(values: Optional[List[float]]) -> Optional[List[List[float]]]:
        if not values:
            return None
        return [[float(item)] for item in values]

    def _serialize_leakage_power(self, cell: Cell, arc) -> Dict[str, Any]:
        return {
            "when": self._format_when(
                arc.condition_string(cell=cell, include_outputs=True, include_internal=False)
            ),
            "value": arc.leakage_power,
            "related_pg_pin": arc.metadata.get("related_pg_pin", ""),
        }

    @staticmethod
    def _coerce_numeric(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        return number

    @classmethod
    def _sanitize_table_values(cls, values: Any) -> Optional[Any]:
        if values is None:
            return None

        if isinstance(values, list):
            if not values:
                return None
            first = values[0]
            if isinstance(first, list):
                sanitized_matrix: List[List[float]] = []
                has_data = False
                for row in values:
                    if not isinstance(row, list):
                        return None
                    sanitized_row: List[float] = []
                    for item in row:
                        number = cls._coerce_numeric(item)
                        if number is None:
                            return None
                        sanitized_row.append(number)
                        has_data = True
                    sanitized_matrix.append(sanitized_row)
                return sanitized_matrix if has_data else None
            else:
                sanitized_list: List[float] = []
                has_data = False
                for item in values:
                    number = cls._coerce_numeric(item)
                    if number is None:
                        return None
                    sanitized_list.append(number)
                    has_data = True
                return sanitized_list if has_data else None

        number = cls._coerce_numeric(values)
        return number if number is not None else None

    @classmethod
    def _merge_mpw_vectors(cls, vectors: List[List[float]]) -> List[float]:
        if not vectors:
            return []

        length = max(len(vec) for vec in vectors)
        placeholder = 1e-4
        merged = [0.0] * length

        for vec in vectors:
            for idx, raw in enumerate(vec):
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if value <= placeholder:
                    continue
                merged[idx] = max(merged[idx], value)

        if not any(val > placeholder for val in merged):
            return []

        return merged

    def _append_default_mpw_entries(self, pins_payload: Dict[str, Any]) -> None:
        """Append an unconditioned MPW timing() entry as max over conditional cases."""

        def merge_max(vectors: List[List[float]]) -> List[float]:
            if not vectors:
                return []
            length = max(len(vec) for vec in vectors)
            merged = [0.0] * length
            for vec in vectors:
                for idx, raw in enumerate(vec):
                    try:
                        value = float(raw)
                    except (TypeError, ValueError):
                        continue
                    merged[idx] = max(merged[idx], value)
            return merged

        for pin_payload in pins_payload.values():
            timing_entries = pin_payload.get("timing") or []
            mpw_entries = [
                entry
                for entry in timing_entries
                if entry.get("timing_type") == TimingType.MIN_PULSE_WIDTH.value
            ]
            if not mpw_entries:
                continue

            grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for entry in mpw_entries:
                related_pin = entry.get("related_pin") or ""
                if related_pin:
                    grouped[related_pin].append(entry)

            for related_pin, entries in grouped.items():
                # Skip if a default (no-when) MPW timing block already exists.
                if any(not entry.get("when") for entry in entries):
                    continue

                conditional = [entry for entry in entries if entry.get("when")]
                if not conditional:
                    continue

                rise_tables = [
                    entry.get(TableType.RISE_CONSTRAINT.value)
                    for entry in conditional
                    if isinstance(entry.get(TableType.RISE_CONSTRAINT.value), dict)
                    and isinstance(entry[TableType.RISE_CONSTRAINT.value].get("values"), list)
                ]
                fall_tables = [
                    entry.get(TableType.FALL_CONSTRAINT.value)
                    for entry in conditional
                    if isinstance(entry.get(TableType.FALL_CONSTRAINT.value), dict)
                    and isinstance(entry[TableType.FALL_CONSTRAINT.value].get("values"), list)
                ]

                rise_vectors = [table.get("values") for table in rise_tables if isinstance(table, dict)]
                fall_vectors = [table.get("values") for table in fall_tables if isinstance(table, dict)]

                merged_rise = merge_max([vec for vec in rise_vectors if isinstance(vec, list)])
                merged_fall = merge_max([vec for vec in fall_vectors if isinstance(vec, list)])

                if not merged_rise and not merged_fall:
                    continue

                default_entry: Dict[str, Any] = {
                    "related_pin": related_pin,
                    "timing_type": TimingType.MIN_PULSE_WIDTH.value,
                }

                if merged_rise and rise_tables:
                    rise_table = copy.deepcopy(rise_tables[0])
                    rise_table["values"] = merged_rise
                    default_entry[TableType.RISE_CONSTRAINT.value] = rise_table

                if merged_fall and fall_tables:
                    fall_table = copy.deepcopy(fall_tables[0])
                    fall_table["values"] = merged_fall
                    default_entry[TableType.FALL_CONSTRAINT.value] = fall_table

                timing_entries.append(default_entry)

    @staticmethod
    def _enforce_monotonic_vector(values: List[float]) -> List[float]:
        epsilon = 1e-3
        cleaned: List[float] = []
        last: float | None = None
        for value in values:
            current = float(value)
            if current <= 0.0:
                current = epsilon if last is None else last + epsilon
            elif last is not None and current <= last:
                current = last + epsilon
            cleaned.append(current)
            last = current
        return cleaned

    @staticmethod
    def _table_has_values(table: Optional[Dict[str, Any]]) -> bool:
        if not table:
            return False
        values = table.get("values")
        if values is None:
            return False
        if isinstance(values, list):
            if not values:
                return False
            if isinstance(values[0], list):
                return any(row and any(v is not None for v in row) for row in values)
            return any(v is not None for v in values)
        return True

    def _has_timing_payload(self, entry: Dict[str, Any]) -> bool:
        timing_keys = (
            TableType.CELL_RISE.value,
            TableType.CELL_FALL.value,
            TableType.RISE_TRANSITION.value,
            TableType.FALL_TRANSITION.value,
            TableType.RISE_CONSTRAINT.value,
            TableType.FALL_CONSTRAINT.value,
        )
        return any(isinstance(entry.get(key), dict) for key in timing_keys)

    def _has_power_payload(self, entry: Dict[str, Any]) -> bool:
        return any(self._table_has_values(entry.get(key)) for key in ("rise_power", "fall_power"))

    def _cache_timing_table(self, key: Tuple[str, str, str, str, str], table: Dict[str, Any]) -> None:
        clone = {
            "template": table.get("template"),
            "index_1": list(table.get("index_1", [])),
            "index_2": list(table.get("index_2", [])),
        }
        values = table.get("values")
        if isinstance(values, list):
            if values and isinstance(values[0], list):
                clone["values"] = [list(row) for row in values]
            else:
                clone["values"] = list(values)
        elif values is not None:
            clone["values"] = values
        self._timing_table_cache[key] = clone

    def _resolve_timing_placeholders(self, entry: Dict[str, Any]) -> None:
        timing_keys = {
            TableType.CELL_RISE.value,
            TableType.CELL_FALL.value,
            TableType.RISE_TRANSITION.value,
            TableType.FALL_TRANSITION.value,
            TableType.RISE_CONSTRAINT.value,
            TableType.FALL_CONSTRAINT.value,
        }
        for key in timing_keys:
            table = entry.get(key)
            if not isinstance(table, dict):
                continue
            fallback_key = table.pop("_fallback_key", None)
            if fallback_key and fallback_key in self._timing_table_cache:
                entry[key] = copy.deepcopy(self._timing_table_cache[fallback_key])

    def _finalize_timing_entries(self, cell: Cell, pin_name: str, pin_payload: Dict[str, Any]) -> None:
        timing_entries = pin_payload.get("timing") or []
        if not timing_entries:
            return

        groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for entry in timing_entries:
            key = (entry.get("related_pin", ""), entry.get("timing_type", ""))
            groups[key].append(entry)

        timing_keys = (
            TableType.CELL_RISE.value,
            TableType.CELL_FALL.value,
            TableType.RISE_TRANSITION.value,
            TableType.FALL_TRANSITION.value,
            TableType.RISE_CONSTRAINT.value,
            TableType.FALL_CONSTRAINT.value,
        )

        for entries in groups.values():
            union_tables: Dict[str, Dict[str, Any]] = {}
            for entry in entries:
                for key in timing_keys:
                    table = entry.get(key)
                    if self._table_has_values(table):
                        union_tables[key] = copy.deepcopy(table)
            for entry in entries:
                for key in timing_keys:
                    if not self._table_has_values(entry.get(key)) and key in union_tables:
                        entry[key] = copy.deepcopy(union_tables[key])
                if (
                    entry.get("timing_type") in {TimingType.RISING_EDGE.value, TimingType.FALLING_EDGE.value}
                    and self._table_has_values(entry.get(TableType.CELL_RISE.value))
                    and self._table_has_values(entry.get(TableType.CELL_FALL.value))
                ):
                    entry.setdefault("timing_sense", "non_unate")

    def _finalize_internal_power_entries(self, pin_payload: Dict[str, Any]) -> None:
        power_entries = pin_payload.get("internal_power") or []
        if not power_entries:
            return

        global_union: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = defaultdict(dict)
        for entry in power_entries:
            gkey = (entry.get("related_pin", ""), entry.get("related_pg_pin", ""))
            for key in ("rise_power", "fall_power"):
                table = entry.get(key)
                if self._table_has_values(table):
                    global_union[gkey][key] = copy.deepcopy(table)

        groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
        for entry in power_entries:
            key = (
                entry.get("related_pin", ""),
                entry.get("when", ""),
                entry.get("related_pg_pin", ""),
            )
            groups[key].append(entry)

        for entries in groups.values():
            union_tables: Dict[str, Dict[str, Any]] = {}
            for entry in entries:
                for key in ("rise_power", "fall_power"):
                    table = entry.get(key)
                    if self._table_has_values(table):
                        union_tables[key] = copy.deepcopy(table)
            for entry in entries:
                global_key = (entry.get("related_pin", ""), entry.get("related_pg_pin", ""))
                for key in ("rise_power", "fall_power"):
                    if self._table_has_values(entry.get(key)):
                        continue
                    if key in union_tables:
                        entry[key] = copy.deepcopy(union_tables[key])
                    elif key in global_union.get(global_key, {}):
                        entry[key] = copy.deepcopy(global_union[global_key][key])

    @staticmethod
    def _format_when(condition: str) -> str:
        if not condition:
            return ""
        return f"({condition})"


class LibrarySerializer:
    """High-level serializer that orchestrates individual components."""

    def __init__(
        self,
        *,
        template_serializer: Optional[TemplateSerializer] = None,
        cell_serializer: Optional[CellSerializer] = None,
    ) -> None:
        self.template_serializer = template_serializer or TemplateSerializer()
        self.cell_serializer = cell_serializer or CellSerializer(self.template_serializer)

    def build_library_dict(self, library_db: CellLibraryDB) -> Dict[str, Any]:
        """
        Build the complete legacy library dictionary from the database.

        Returns:
            Dictionary that mirrors `legacy/library_structure.py`.
        """
        logger.debug("Starting library dictionary serialization for %s cells", len(library_db.cells))
        library_payload: Dict[str, Any] = self._serialize_metadata(library_db)
        templates = self.template_serializer.build_template_nodes(library_db)
        library_payload.update(templates)
        library_payload["cells"] = self.cell_serializer.build_cell_nodes(library_db)
        return {"library": library_payload}

    def _serialize_metadata(self, library_db: CellLibraryDB) -> Dict[str, Any]:
        """
        Serialize top-level metadata such as units and voltage maps.

        The initial implementation seeds default values; future iterations will
        merge runtime configuration from `library_db.config_params`.
        """
        # TODO: Replace placeholder defaults with values extracted from config params.
        config = getattr(library_db, "config_params", {})
        voltage = config.get("voltage")
        temperature = config.get("temp")
        process = config.get("process", 1)
        operating_conditions: Dict[str, Any] = {}

        if voltage is not None and temperature is not None:
            pvt_name = f"PVT_{voltage:.1f}V_{int(temperature)}C"
            operating_conditions[pvt_name] = {
                "process": process,
                "temperature": temperature,
                "voltage": voltage,
            }

        voltage_map = {
            "VDD": voltage,
            "VSS": 0,
            "GND": 0,
        }

        return {
            "name": "target_lib",
            "delay_model": "table_lookup",
            "capacitive_load_unit": "1,pf",
            "current_unit": "1mA",
            "leakage_power_unit": "1nW",
            "pulling_resistance_unit": "1kohm",
            "time_unit": "1ns",
            "voltage_unit": "1V",
            "operating_conditions": operating_conditions,
            "voltage_map": voltage_map,
        }


class LibraryJsonExporter:
    """
    Public façade responsible for exporting the library database to JSON.

    This class wires together the serializer and cleaner utilities, handles IO,
    and returns the path to the generated JSON payload.
    """

    def __init__(
        self,
        *,
        serializer: Optional[LibrarySerializer] = None,
        cleaner: Optional[JsonCleaner] = None,
        config: Optional[ExporterConfig] = None,
    ) -> None:
        self.serializer = serializer or LibrarySerializer()
        self.cleaner = cleaner or JsonCleaner()
        self.config = config or ExporterConfig()

    def export(self, library_db: CellLibraryDB, output_path: Path) -> Path:
        """
        Convert the provided database into the legacy JSON structure.

        Args:
            library_db: Populated cell library database.
            output_path: Destination file path for the JSON payload.

        Returns:
            Path to the written JSON file.
        """
        logger.info("Exporting CellLibraryDB to legacy JSON at %s", output_path)
        legacy_dict = self.serializer.build_library_dict(library_db)
        cleaned_dict = self.cleaner.remove_empty(legacy_dict)
        json_payload = self._dumps(cleaned_dict)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_payload)
        logger.debug("Wrote legacy JSON file with size %d bytes", output_path.stat().st_size)
        return output_path

    def _dumps(self, payload: Dict[str, Any]) -> str:
        """Serialize payload to JSON and apply legacy-compatible formatting."""
        json_text = json.dumps(payload, indent=self.config.indent if self.config.pretty else None)
        return self.cleaner.compress_lists(json_text)
