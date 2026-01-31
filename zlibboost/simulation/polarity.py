"""Utilities for reasoning about pin polarity in simulation generators.

This module centralizes logic that converts logical condition bits into
physical expectations (voltage level, polarity) based on `PinInfo`
metadata. Generators can use these helpers instead of duplicating
`get_outpositive_pins`/`get_outnegative_pins` lookups.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from zlibboost.database.models.cell import Cell, PinInfo


_SIMPLE_INVERSION_PATTERN = re.compile(
    r"^[!~]\s*\(?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)?\s*$"
)


def _infer_pin_is_negative(pin: PinInfo) -> bool:
    """Return effective inversion polarity for a pin.

    In the refactor codebase we store negative polarity explicitly for many pin
    categories (e.g. active-low reset). Some libraries also express inverted
    *output* pins via a simple function like ``QN=!D`` without setting
    ``PinInfo.is_negative``. Legacy deck generation treated those as
    outnegative pins; the simulation generators rely on this polarity to
    precondition sequential outputs (e.g. QN) correctly.

    We only infer polarity for trivial one-input inversions to avoid
    accidentally flipping complex combinational outputs.
    """

    if pin.is_negative:
        return True

    function_obj = getattr(pin, "function", None)
    expr: str | None = None
    if function_obj is None:
        return False

    if isinstance(function_obj, str):
        expr = function_obj
    else:
        expr = getattr(function_obj, "original_expr", None)

    if not expr:
        return False

    return _SIMPLE_INVERSION_PATTERN.match(expr.strip()) is not None


@dataclass(frozen=True)
class PinPolarity:
    """Wrapper exposing polarity helpers for a specific pin."""

    pin: PinInfo

    @property
    def name(self) -> str:
        return self.pin.name

    @property
    def is_negative(self) -> bool:
        return _infer_pin_is_negative(self.pin)

    def expects_high(self, logical_state: str) -> bool:
        """Return whether the physical voltage should be high for this logic bit."""
        if logical_state not in {"0", "1"}:
            raise ValueError(f"Unsupported logical state '{logical_state}' for pin {self.name}")
        logical_high = logical_state == "1"
        return logical_high != self.is_negative

    def logical_to_voltage(self, logical_state: str, v_high: float, v_low: float) -> float:
        """Map the logical state string to an analog voltage."""
        return v_high if self.expects_high(logical_state) else v_low


def resolve_output_pin(cell: Cell, pin_name: str) -> Optional[PinPolarity]:
    """Return polarity wrapper when the pin is an output, otherwise ``None``."""
    pin_info = cell.pins.get(pin_name)
    if not pin_info or pin_info.direction != "output":
        return None
    return PinPolarity(pin=pin_info)
