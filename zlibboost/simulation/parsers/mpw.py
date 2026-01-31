"""MPW measurement parsers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from .base import MeasurementParser, MeasurementPayload
from .hspice_common import parse_hspice_measurement_table


class MpwSpectreParser(MeasurementParser):
    """Parse Spectre measurement outputs for MPW simulations."""

    SUPPORTED_ENGINES = ("spectre", "mock")

    _KEY_MAP = {
        "zlibboostdelay": "pulse_width",
        "degradedelay": "degradation",
        "glitch_peak_rise": "glitch_peak_rise",
        "glitch_peak_fall": "glitch_peak_fall",
        "half_tran_tend_q": "half_tran_voltage",
        "halftranq": "half_tran_voltage",
    }

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, object],
    ) -> MeasurementPayload:
        if not measurement_path.exists():
            raise FileNotFoundError(f"Spectre measurement file not found: {measurement_path}")

        metrics: Dict[str, float] = {}
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
                number = float(value.strip())
            except ValueError:
                continue
            if target in {"pulse_width", "degradation"}:
                metrics[target] = number * 1e9
            else:
                metrics[target] = number

        artifacts = {"measurement_file": str(measurement_path)}
        payload_metadata: Dict[str, object] = {"deck": str(deck_path), "line_count": len(raw_lines)}
        if metadata:
            payload_metadata.update(metadata)

        return MeasurementPayload(
            metrics=metrics,
            artifacts=artifacts,
            metadata=payload_metadata,
        )


class MpwHspiceParser(MeasurementParser):
    """Parse HSPICE/Ngspice measurement outputs for MPW simulations."""

    SUPPORTED_ENGINES = ("hspice", "ngspice")

    _KEY_MAP = MpwSpectreParser._KEY_MAP

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, object],
    ) -> MeasurementPayload:
        rows, line_count = parse_hspice_measurement_table(measurement_path)
        metrics: Dict[str, float] = {}

        for row in rows:
            for key, target in self._KEY_MAP.items():
                if key not in row:
                    continue
                value = row[key]
                if target in {"pulse_width", "degradation"}:
                    metrics[target] = value * 1e9
                else:
                    metrics[target] = value
            if metrics:
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
