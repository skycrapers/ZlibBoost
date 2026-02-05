"""Constraint timing measurement parsers."""

from __future__ import annotations

from pathlib import Path
import math
from typing import Dict, List

from .base import MeasurementParser, MeasurementPayload
from .hspice_common import parse_hspice_measurement_table


class ConstraintSpectreParser(MeasurementParser):
    """Parse Spectre setup/hold/recovery/removal measurement outputs."""

    SUPPORTED_ENGINES = ("spectre", "mock")

    _KEY_MAP = {
        "zlibboostdelay": "constraint",
        "degradedelay": "degradation",
        "degradedelayrise": "degradation_rise",
        "degradedelayfall": "degradation_fall",
        "glitch_peak_rise": "glitch_peak_rise",
        "glitch_peak_fall": "glitch_peak_fall",
        "half_tran_tend_q": "half_tran_tend_q",
        "final_q": "final_q",
    }

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, object],
    ) -> MeasurementPayload:
        if not measurement_path.exists():
            raise FileNotFoundError(f"Spectre measurement file not found: {measurement_path}")

        metrics: Dict[str, object] = {}
        raw_lines = measurement_path.read_text().splitlines()

        for raw_line in raw_lines:
            stripped = raw_line.strip()
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            normalized = key.strip().lower()
            target = self._KEY_MAP.get(normalized)
            if not target:
                continue
            try:
                numeric = float(value.strip())
            except ValueError:
                continue
            if target == "constraint":
                metrics[target] = numeric * 1e9
            elif target in {"degradation", "degradation_rise", "degradation_fall"}:
                metrics[target] = numeric * 1e9
            else:
                metrics[target] = numeric

        degradation = metrics.get("degradation")
        if degradation is None or (isinstance(degradation, float) and math.isnan(degradation)):
            for fallback_key in ("degradation_rise", "degradation_fall"):
                candidate = metrics.get(fallback_key)
                if candidate is None:
                    continue
                if isinstance(candidate, float) and math.isnan(candidate):
                    continue
                metrics["degradation"] = candidate
                break

        artifacts = {"measurement_file": str(measurement_path)}
        payload_metadata: Dict[str, object] = {"deck": str(deck_path), "line_count": len(raw_lines)}
        if metadata:
            payload_metadata.update(metadata)

        return MeasurementPayload(
            metrics=metrics,
            artifacts=artifacts,
            metadata=payload_metadata,
        )


class ConstraintHspiceParser(MeasurementParser):
    """Parse HSPICE/Ngspice setup/hold/recovery/removal measurement outputs."""

    SUPPORTED_ENGINES = ("hspice", "ngspice")

    _KEY_MAP = ConstraintSpectreParser._KEY_MAP

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, object],
    ) -> MeasurementPayload:
        rows, line_count = parse_hspice_measurement_table(measurement_path)
        metrics: Dict[str, object] = {}

        for row in rows:
            for key, target in self._KEY_MAP.items():
                if key not in row:
                    continue
                value = row[key]
                if target in {"constraint", "degradation", "degradation_rise", "degradation_fall"}:
                    metrics[target] = value * 1e9
                else:
                    metrics[target] = value
            if metrics:
                break

        degradation = metrics.get("degradation")
        if degradation is None or (isinstance(degradation, float) and math.isnan(degradation)):
            for fallback_key in ("degradation_rise", "degradation_fall"):
                candidate = metrics.get(fallback_key)
                if candidate is None:
                    continue
                if isinstance(candidate, float) and math.isnan(candidate):
                    continue
                metrics["degradation"] = candidate
                break

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
