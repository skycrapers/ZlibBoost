"""Leakage power measurement parsers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .base import MeasurementParser, MeasurementPayload
from .hspice_common import parse_hspice_measurement_table


class LeakageSpectreParser(MeasurementParser):
    """Parse Spectre leakage power measurement outputs."""

    SUPPORTED_ENGINES = ("spectre",)

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, object],
    ) -> MeasurementPayload:
        """Extract leakage power metrics from a Spectre .measure file."""

        if not measurement_path.exists():
            raise FileNotFoundError(
                f"Spectre measurement file not found: {measurement_path}"
            )

        lines = measurement_path.read_text().splitlines()
        leakage_power_values: List[float] = []
        total_leakage_current = None

        for line in lines:
            stripped = line.strip()
            if not stripped or "=" not in stripped:
                continue
            lhs, rhs = stripped.split("=", 1)
            key = lhs.strip().lower()
            try:
                value = float(rhs.strip())
            except ValueError:
                continue

            if "leakagepower" in key:
                # Normalise to nW for compatibility with legacy exporter expectations.
                leakage_power_values.append(value * 1e9)
            elif "totalleakagecurrent" in key:
                total_leakage_current = abs(value)

        artifacts = {
            "measurement_file": str(measurement_path),
        }
        payload_metadata: Dict[str, object] = {
            "line_count": len(lines),
            "deck": str(deck_path),
        }
        if metadata:
            payload_metadata.update(metadata)

        metrics: Dict[str, object] = {}
        if leakage_power_values:
            metrics["leakage_power"] = leakage_power_values[0] if len(leakage_power_values) == 1 else leakage_power_values
        if total_leakage_current is not None:
            # Expose total leakage current in microamps for downstream auditing.
            metrics["total_leakage_current_ua"] = total_leakage_current * 1e6

        return MeasurementPayload(
            metrics=metrics,
            artifacts=artifacts,
            metadata=payload_metadata,
        )


class LeakageHspiceParser(MeasurementParser):
    """Parse HSPICE/Ngspice leakage power measurement outputs."""

    SUPPORTED_ENGINES = ("hspice", "ngspice")

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, object],
    ) -> MeasurementPayload:
        rows, line_count = parse_hspice_measurement_table(measurement_path)
        leakage_values = [row["leakagepower"] for row in rows if "leakagepower" in row]
        currents = [abs(row["totalleakagecurrent"]) for row in rows if "totalleakagecurrent" in row]

        metrics: Dict[str, object] = {}
        if leakage_values:
            scaled = [value * 1e9 for value in leakage_values]
            metrics["leakage_power"] = scaled[0] if len(scaled) == 1 else scaled
        if currents:
            metrics["total_leakage_current_ua"] = currents[0] * 1e6

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
