"""Hidden power measurement parsers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .base import MeasurementParser, MeasurementPayload
from .hspice_common import parse_hspice_measurement_table


class HiddenSpectreParser(MeasurementParser):
    """Parse Spectre hidden power measurement outputs."""

    SUPPORTED_ENGINES = ("spectre",)

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, object],
    ) -> MeasurementPayload:
        """Extract hidden power metrics from a Spectre .measure file."""

        if not measurement_path.exists():
            raise FileNotFoundError(
                f"Spectre measurement file not found: {measurement_path}"
            )

        lines = measurement_path.read_text().splitlines()
        hidden_values: List[float] = []
        for line in lines:
            lower = line.strip().lower()
            if "hiddenpower" not in lower:
                continue
            if "=" not in line:
                continue
            _, rhs = line.split("=", 1)
            try:
                value = float(rhs.strip())
            except ValueError:
                continue
            hidden_values.append(value * 1e12) # Convert to pW

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
            metrics={"hidden_power": hidden_values},
            artifacts=artifacts,
            metadata=payload_metadata,
        )


class HiddenHspiceParser(MeasurementParser):
    """Parse HSPICE/Ngspice hidden power measurement outputs."""

    SUPPORTED_ENGINES = ("hspice", "ngspice")

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, object],
    ) -> MeasurementPayload:
        rows, line_count = parse_hspice_measurement_table(measurement_path)
        hidden_values = [
            row["hiddenpower"] * 1e12 for row in rows if "hiddenpower" in row
        ]

        artifacts = {"measurement_file": str(measurement_path)}
        payload_metadata: Dict[str, object] = {
            "deck": str(deck_path),
            "line_count": line_count,
        }
        if metadata:
            payload_metadata.update(metadata)

        return MeasurementPayload(
            metrics={"hidden_power": hidden_values},
            artifacts=artifacts,
            metadata=payload_metadata,
        )
