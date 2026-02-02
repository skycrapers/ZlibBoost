"""Shared helpers for parsing HSPICE measurement tables."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence, Tuple


def parse_hspice_measurement_table(measurement_path: Path) -> Tuple[List[Dict[str, float]], int]:
    """Parse an HSPICE .mt0 file into a list of column dictionaries."""

    if not measurement_path.exists():
        raise FileNotFoundError(f"HSPICE measurement file not found: {measurement_path}")

    raw_lines = measurement_path.read_text().splitlines()
    columns: List[str] = []
    data_tokens: List[str] = []
    data_started = False

    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("source="):
            continue
        if stripped.startswith("$DATA") or stripped.startswith(".TITLE"):
            continue

        parts = stripped.split()
        if not parts:
            continue

        if not data_started:
            # HSPICE can emit non-numeric sentinel tokens (e.g. "failed") in
            # the data row, so "all numbers" is not a reliable delimiter.
            # Instead, treat the first line that starts with a value as the
            # beginning of the data section.
            if parts and _is_value_token(parts[0]):
                data_started = True
                data_tokens.extend(parts)
            else:
                columns.extend(parts)
        else:
            data_tokens.extend(parts)

    if not columns or not data_tokens:
        return [], len(raw_lines)

    row_width = len(columns)
    rows: List[Dict[str, float]] = []
    for start in range(0, len(data_tokens), row_width):
        chunk = data_tokens[start : start + row_width]
        if len(chunk) < row_width:
            break
        row: Dict[str, float] = {}
        for name, token in zip(columns, chunk):
            key = name.strip().lower()
            try:
                row[key] = _parse_number(token)
            except ValueError:
                continue
        if row:
            rows.append(row)

    return rows, len(raw_lines)


def _parse_number(token: str) -> float:
    normalized = token.strip()
    if not normalized:
        raise ValueError("empty token")
    lower = normalized.lower()
    if lower in {"failed", "nan"}:
        return float("nan")
    normalized = normalized.replace("D", "E").replace("d", "e")
    return float(normalized)


def _all_numbers(tokens: Sequence[str]) -> bool:
    try:
        for token in tokens:
            _parse_number(token)
    except ValueError:
        return False
    return True


def _is_value_token(token: str) -> bool:
    """Return True when token looks like a data value rather than a column name."""
    try:
        _parse_number(token)
    except ValueError:
        return False
    return True
