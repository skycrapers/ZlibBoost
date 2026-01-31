"""Delay timing measurement parsers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .base import MeasurementParser, MeasurementPayload
from .hspice_common import parse_hspice_measurement_table


class DelaySpectreParser(MeasurementParser):
    """Parse Spectre delay/transition measurement outputs."""

    SUPPORTED_ENGINES = ("spectre",)

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, object],
    ) -> MeasurementPayload:
        if not measurement_path.exists():
            raise FileNotFoundError(f"Spectre measurement file not found: {measurement_path}")

        lines = measurement_path.read_text().splitlines()
        delays: List[float] = []
        transition0: List[float] = []
        transition1: List[float] = []
        switching_power: List[float] = []
        rise_cap: List[float] = []
        fall_cap: List[float] = []
        input_rise_cap: List[float] = []
        input_fall_cap: List[float] = []

        per_pin_caps: Dict[str, Dict[str, List[float]]] = {}

        for raw_line in lines:
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            lhs, rhs = line.split("=", 1)
            raw_key = lhs.strip()
            key = raw_key.lower()
            try:
                value = float(rhs.strip())
            except ValueError:
                continue

            if key == "zlibboostdelay":
                delays.append(value * 1e9)
            elif key == "zlibboosttransition0":
                transition0.append(value)
            elif key == "zlibboosttransition1":
                transition1.append(value)
            elif key == "switchingpower":
                switching_power.append(value * 1e12)
            elif key == "risecap":
                rise_cap.append(abs(value) * 1e12)
            elif key == "fallcap":
                fall_cap.append(abs(value) * 1e12)
            elif key == "inputrisecap":
                input_rise_cap.append(abs(value) * 1e12)
            elif key == "inputfallcap":
                input_fall_cap.append(abs(value) * 1e12)
            elif key.startswith("inputrisecap_"):
                pin = raw_key.split("_", 1)[1]
                bucket = per_pin_caps.setdefault(pin, {"rise": [], "fall": []})
                bucket["rise"].append(abs(value) * 1e12)
            elif key.startswith("inputfallcap_"):
                pin = raw_key.split("_", 1)[1]
                bucket = per_pin_caps.setdefault(pin, {"rise": [], "fall": []})
                bucket["fall"].append(abs(value) * 1e12)

        table_type = str(metadata.get("table_type", "")) if metadata else ""
        transition_scale = self._resolve_transition_scale(table_type, metadata)
        transitions: List[float] = []
        paired_count = min(len(transition0), len(transition1))
        for idx in range(paired_count):
            delta = transition1[idx] - transition0[idx]
            transitions.append(abs(delta) * 1e9 * transition_scale)

        metrics: Dict[str, object] = {}
        if delays:
            metrics["delay"] = delays
        if transitions:
            metrics["transition"] = transitions
        if switching_power:
            metrics["switching_power"] = switching_power
        if rise_cap:
            metrics["rise_cap"] = rise_cap
        if fall_cap:
            metrics["fall_cap"] = fall_cap
        if input_rise_cap:
            metrics["input_rise_cap"] = input_rise_cap
        if input_fall_cap:
            metrics["input_fall_cap"] = input_fall_cap
        if per_pin_caps:
            metrics["input_caps"] = per_pin_caps

        artifacts = {
            "measurement_file": str(measurement_path),
        }
        payload_metadata: Dict[str, object] = {
            "line_count": len(lines),
            "deck": str(deck_path),
        }
        if metadata:
            payload_metadata.update(metadata)

        return MeasurementPayload(
            metrics=metrics,
            artifacts=artifacts,
            metadata=payload_metadata,
        )

    @staticmethod
    def _resolve_transition_scale(table_type: str, metadata: Dict[str, object] | None) -> float:
        metadata = metadata or {}
        scale_rise = float(metadata.get("scale_rise", 1.0))
        scale_fall = float(metadata.get("scale_fall", 1.0))
        table_type_lower = table_type.lower()
        if "rise" in table_type_lower:
            return scale_rise
        if "fall" in table_type_lower:
            return scale_fall
        return scale_rise


class DelayHspiceParser(MeasurementParser):
    """Parse HSPICE/Ngspice delay/transition measurement outputs."""

    SUPPORTED_ENGINES = ("hspice", "ngspice")

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, object],
    ) -> MeasurementPayload:
        rows, line_count = parse_hspice_measurement_table(measurement_path)
        if not rows:
            artifacts = {"measurement_file": str(measurement_path)}
            payload_metadata: Dict[str, object] = {
                "deck": str(deck_path),
                "line_count": line_count,
            }
            if metadata:
                payload_metadata.update(metadata)
            return MeasurementPayload(metrics={}, artifacts=artifacts, metadata=payload_metadata)

        table_type = str(metadata.get("table_type", "")) if metadata else ""
        transition_scale = DelaySpectreParser._resolve_transition_scale(table_type, metadata)

        def _collect(
            target_rows: List[Dict[str, float]],
            keys: tuple[str, ...],
            scale: float = 1.0,
            absolute: bool = False,
        ) -> List[float]:
            collected: List[float] = []
            for row in target_rows:
                for key in keys:
                    if key in row:
                        value = row[key]
                        if absolute:
                            value = abs(value)
                        collected.append(value * scale)
                        break
            return collected

        delays = _collect(rows, ("zlibboostdelay",), scale=1e9)
        transition0 = _collect(rows, ("zlibboosttransition0",))
        transition1 = _collect(rows, ("zlibboosttransition1",))
        switching_power = _collect(rows, ("switchingpower",), scale=1e12)
        rise_cap = _collect(rows, ("risecap",), scale=1e12, absolute=True)
        fall_cap = _collect(rows, ("fallcap",), scale=1e12, absolute=True)
        input_rise_cap = _collect(
            rows, ("inputrisecap", "inputrisecap_d"), scale=1e12, absolute=True
        )
        input_fall_cap = _collect(
            rows, ("inputfallcap", "inputfallcap_d"), scale=1e12, absolute=True
        )

        transitions: List[float] = []
        paired = min(len(transition0), len(transition1))
        for idx in range(paired):
            delta = transition1[idx] - transition0[idx]
            transitions.append(abs(delta) * 1e9 * transition_scale)

        per_pin_caps: Dict[str, Dict[str, List[float]]] = {}
        for row in rows:
            for key, value in row.items():
                if key.startswith("inputrisecap_") and key not in {"inputrisecap_d"}:
                    pin = key.split("_", 1)[1]
                    bucket = per_pin_caps.setdefault(pin, {"rise": [], "fall": []})
                    bucket["rise"].append(abs(value) * 1e12)
                elif key.startswith("inputfallcap_") and key not in {"inputfallcap_d"}:
                    pin = key.split("_", 1)[1]
                    bucket = per_pin_caps.setdefault(pin, {"rise": [], "fall": []})
                    bucket["fall"].append(abs(value) * 1e12)

        metrics: Dict[str, object] = {}
        if delays:
            metrics["delay"] = delays
        if transitions:
            metrics["transition"] = transitions
        if switching_power:
            metrics["switching_power"] = switching_power
        if rise_cap:
            metrics["rise_cap"] = rise_cap
        if fall_cap:
            metrics["fall_cap"] = fall_cap
        if input_rise_cap:
            metrics["input_rise_cap"] = input_rise_cap
        if input_fall_cap:
            metrics["input_fall_cap"] = input_fall_cap
        if per_pin_caps:
            metrics["input_caps"] = per_pin_caps

        artifacts = {"measurement_file": str(measurement_path)}
        payload_metadata: Dict[str, object] = {
            "deck": str(deck_path),
            "line_count": line_count,
        }
        if metadata:
            payload_metadata.update(metadata)

        return MeasurementPayload(
            metrics=metrics,
            artifacts=artifacts,
            metadata=payload_metadata,
        )
