"""Minimum pulse width deck optimizer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict
import math
import re

from zlibboost.simulation.parsers.base import MeasurementPayload


@dataclass(slots=True)
class MpwOptimizationResult:
    """Summary of an MPW optimization run."""

    payload: MeasurementPayload
    best_width_ns: float
    iterations: int
    converged: bool


class MpwDeckOptimizer:
    """Binary-search optimizer that shrinks MPW deck pulse width until failure."""

    _WIDTH_PATTERN_TEMPLATE = r"(\.param {pin}_t{index}=)([^ \n]+)"

    def __init__(
        self,
        deck_path: Path,
        metadata: Dict[str, object],
        engine_dir: Path,
        run_callback: Callable[[Path, Dict[str, object], float], MeasurementPayload],
        *,
        tolerance: float = 0.05,
        degradation_tolerance: float = 0.1,
        max_iterations: int = 10,
    ) -> None:
        self._deck_path = Path(deck_path)
        self._metadata = dict(metadata)
        self._engine_dir = Path(engine_dir)
        self._run_callback = run_callback
        self._base_content = self._deck_path.read_text()
        self._pin = str(metadata.get("pin", "")).strip()
        if not self._pin:
            raise ValueError("MPW metadata missing 'pin' identifier for optimization")
        self._tolerance = max(float(tolerance), 1e-3)
        self._degradation_tolerance = max(float(degradation_tolerance), 1e-3)
        self._max_iterations = max(int(max_iterations), 1)

        self._base_width_s = self._extract_param(2)
        self._tail_delta_s = self._extract_param(3) - self._base_width_s
        self._base_filename = self._deck_path.stem
        self._reference_degradation_ns: float | None = None

    def run(self, initial_payload: MeasurementPayload) -> MpwOptimizationResult:
        """Perform binary search on pulse width, returning best successful payload."""

        initial_width_ns = float(initial_payload.metrics.get("pulse_width") or 0.0)
        initial_width_s = initial_width_ns * 1e-9 if initial_width_ns > 0 else self._base_width_s
        reference = self._extract_reference_degradation(initial_payload)
        has_reference = reference is not None

        lower_s = 0.0
        upper_s = initial_width_s
        best_payload = initial_payload
        best_width_s = initial_width_s
        converged = False
        iterations = 0

        for iteration in range(1, self._max_iterations + 1):
            iterations = iteration
            if upper_s <= 0.0 or (upper_s - lower_s) <= upper_s * self._tolerance:
                converged = True
                break

            candidate_s = (lower_s + upper_s) / 2.0
            payload = self._simulate_with_width(candidate_s)

            if reference is None:
                reference = self._extract_reference_degradation(payload)
                if reference is None:
                    upper_s = candidate_s
                    best_payload = payload
                    best_width_s = candidate_s
                    continue
                has_reference = True

            if self._is_success(payload, reference):
                upper_s = candidate_s
                best_payload = payload
                best_width_s = candidate_s
            else:
                lower_s = candidate_s

        best_payload.metrics["pulse_width"] = best_width_s * 1e9
        if not has_reference:
            initial_payload.metrics["pulse_width"] = initial_width_s * 1e9
            return MpwOptimizationResult(
                payload=initial_payload,
                best_width_ns=float(initial_payload.metrics["pulse_width"]),
                iterations=0,
                converged=False,
            )
        return MpwOptimizationResult(
            payload=best_payload,
            best_width_ns=float(best_payload.metrics["pulse_width"]),
            iterations=iterations,
            converged=converged and has_reference,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _simulate_with_width(self, width_seconds: float) -> MeasurementPayload:
        adjusted_path = self._write_adjusted_deck(width_seconds)
        payload = self._run_callback(adjusted_path, self._metadata, width_seconds)
        if "pulse_width" not in payload.metrics or not payload.metrics.get("pulse_width"):
            payload.metrics["pulse_width"] = width_seconds * 1e9
        return payload

    def _write_adjusted_deck(self, width_seconds: float) -> Path:
        width_seconds = max(width_seconds, 0.0)
        t2_value = width_seconds
        t3_value = width_seconds + self._tail_delta_s

        content = self._replace_param(2, t2_value, self._base_content)
        content = self._replace_param(3, t3_value, content)

        filename = f"{self._base_filename}_{width_seconds:.3e}.sp"
        deck_path = self._engine_dir / filename
        deck_path.write_text(content)
        return deck_path

    def _replace_param(self, index: int, value: float, content: str) -> str:
        pattern = re.compile(
            self._WIDTH_PATTERN_TEMPLATE.format(pin=re.escape(self._pin), index=index)
        )
        replacement = rf"\g<1>{value:.12g}"
        return pattern.sub(replacement, content, count=1)

    def _extract_param(self, index: int) -> float:
        pattern = re.compile(
            self._WIDTH_PATTERN_TEMPLATE.format(pin=re.escape(self._pin), index=index)
        )
        match = pattern.search(self._base_content)
        if not match:
            raise ValueError(f"Unable to locate parameter {self._pin}_t{index} in deck")
        return float(match.group(2))

    def _extract_reference_degradation(self, payload: MeasurementPayload) -> float | None:
        raw = payload.metrics.get("degradation")
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value <= 0.0:
            return None
        self._reference_degradation_ns = value
        return value

    def _is_success(self, payload: MeasurementPayload, reference_ns: float | None) -> bool:
        pulse = payload.metrics.get("pulse_width")
        if pulse is None or reference_ns is None:
            return False
        degradation = payload.metrics.get("degradation")
        if degradation is None:
            return False
        try:
            deg_value = float(degradation)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(deg_value) or deg_value <= 0.0:
            return False
        try:
            pulse_value = float(pulse)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(pulse_value) or pulse_value <= 0.0:
            return False
        if reference_ns <= 0:
            return True
        error = abs(deg_value - reference_ns) / reference_ns
        return error <= self._degradation_tolerance
