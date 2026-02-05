"""Constraint deck optimization utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

import math
import re

from zlibboost.simulation.parsers.base import MeasurementPayload


@dataclass(slots=True)
class OptimizationResult:
    """Summary of a constraint optimization run."""

    payload: MeasurementPayload
    best_shift: float
    iterations: int
    target: float
    converged: bool


class ConstraintDeckOptimizer:
    """Iteratively adjust constraint decks to match legacy constraint targets."""

    DEFAULT_TARGET_RATIO = 1.1
    # Use a larger default window so the first "safe" reference measurement
    # has a high chance of producing a valid DegradeDelay and the subsequent
    # bracket search can converge even for slower corners/cells.
    DEFAULT_REFERENCE_SHIFT = 10e-9
    DEFAULT_SEARCH_LO = -10e-9
    DEFAULT_SEARCH_HI = 10e-9
    DEFAULT_CACHE_TOLERANCE = 1e-13
    DEFAULT_WINDOW_RATIO = 0.02
    DEFAULT_INFINITY = 1e19

    def __init__(
        self,
        deck_path: Path,
        metadata: Dict[str, object],
        engine_dir: Path,
        run_callback: Callable[[Path, Dict[str, object], float], MeasurementPayload],
        *,
        target_ratio: float = DEFAULT_TARGET_RATIO,
        reference_shift: float = DEFAULT_REFERENCE_SHIFT,
        search_lo: float = DEFAULT_SEARCH_LO,
        search_hi: float = DEFAULT_SEARCH_HI,
        max_iterations: int = 60,
        cache_tolerance: float = DEFAULT_CACHE_TOLERANCE,
        window_ratio: float = DEFAULT_WINDOW_RATIO,
        deck_namer: Callable[[str], str] | None = None,
    ) -> None:
        self._deck_path = Path(deck_path)
        self._metadata = dict(metadata)
        self._engine_dir = Path(engine_dir)
        self._run_callback = run_callback
        self._target_ratio = float(target_ratio)
        self._reference_shift = float(reference_shift)
        self._search_lo = float(search_lo)
        self._search_hi = float(search_hi)
        self._max_iterations = int(max_iterations)
        self._cache_tolerance = float(cache_tolerance)
        self._window_ratio = float(window_ratio)
        self._deck_namer = deck_namer or (lambda name: name)
        self._base_content = self._deck_path.read_text()
        self._timing_type = str(metadata.get("timing_type", "")).lower()
        self._pin = str(metadata.get("pin", ""))
        self._related = str(metadata.get("related", ""))
        self._i1_index, self._i2_index = self._extract_indices(metadata.get("arc_id", ""))

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run(self, initial_payload: MeasurementPayload, *, initial_shift: float = 0.0) -> OptimizationResult:
        """Execute a legacy-aligned optimization loop.

        Legacy behaviour summary:
        - Use `reference_shift` to get a valid reference degradation.
        - Target is `target_ratio * reference_degradation`.
        - Treat invalid/NaN measurements as failures.
        - Search only inside [search_lo, search_hi].
        """

        initial_shift = float(initial_shift)
        reference_payload: MeasurementPayload | None = None
        reference_degradation: float | None = None

        # If the executor already simulated the reference shift (typical when we
        # start from a "safe" initial shift), reuse that result instead of
        # re-running the exact same simulation.
        if abs(initial_shift - self._reference_shift) <= self._cache_tolerance:
            candidate = self._get_degradation(initial_payload)
            if candidate is not None:
                reference_payload = initial_payload
                reference_degradation = candidate

        if reference_payload is None or reference_degradation is None:
            reference_payload = self._evaluate(self._reference_shift)
            reference_degradation = self._get_degradation(reference_payload)
        if reference_payload is None or reference_degradation is None:
            return OptimizationResult(
                payload=initial_payload,
                best_shift=0.0,
                iterations=0,
                target=0.0,
                converged=False,
            )

        target = reference_degradation * self._target_ratio
        lower_bound = reference_degradation * (self._target_ratio - self._window_ratio)
        upper_bound = reference_degradation * (self._target_ratio + self._window_ratio)

        cache: Dict[float, tuple[float, Optional[MeasurementPayload]]] = {}
        evaluated: list[tuple[float, float, MeasurementPayload]] = []

        # Seed the cache with the already-simulated initial shift to avoid
        # duplicating work when it overlaps with endpoints or midpoints.
        initial_degradation = self._get_degradation(initial_payload)
        if initial_degradation is not None:
            if lower_bound <= initial_degradation <= upper_bound:
                obj = 0.0
            else:
                obj = initial_degradation - target
            cache[initial_shift] = (obj, initial_payload)
            evaluated.append((initial_shift, obj, initial_payload))

        def find_cached(shift: float) -> tuple[float | None, tuple[float, Optional[MeasurementPayload]] | None]:
            for cached_shift, cached in cache.items():
                if abs(cached_shift - shift) <= self._cache_tolerance:
                    return cached_shift, cached
            return None, None

        def objective(shift: float) -> tuple[float, Optional[MeasurementPayload]]:
            cached_shift, cached = find_cached(shift)
            if cached is not None:
                return cached

            payload = self._evaluate(shift)
            degradation = self._get_degradation(payload)
            if payload is None or degradation is None:
                result = (self.DEFAULT_INFINITY, None)
                cache[shift] = result
                return result

            if lower_bound <= degradation <= upper_bound:
                obj = 0.0
            else:
                obj = degradation - target
            result = (obj, payload)
            cache[shift] = result
            evaluated.append((shift, obj, payload))
            return result

        # Evaluate endpoints first (legacy bracket).
        f_lo, payload_lo = objective(self._search_lo)
        f_hi, payload_hi = objective(self._search_hi)

        iterations = 0
        best_shift = 0.0
        best_payload: MeasurementPayload | None = None

        def pick_best() -> tuple[float, Optional[MeasurementPayload], bool]:
            usable = [(s, o, p) for s, o, p in evaluated if p is not None and self._get_degradation(p) is not None]
            if not usable:
                return 0.0, None, False

            # Prefer any point within the acceptance band.
            in_band = [(s, o, p) for s, o, p in usable if o == 0.0]
            if in_band:
                s, o, p = min(in_band, key=lambda item: abs(item[0]))
                return s, p, True

            s, o, p = min(usable, key=lambda item: abs(item[1]))
            return s, p, False

        # If either endpoint is already acceptable, stop early.
        if f_lo == 0.0 and payload_lo is not None:
            best_shift, best_payload, converged = self._search_lo, payload_lo, True
            return OptimizationResult(
                payload=best_payload,
                best_shift=best_shift,
                iterations=iterations,
                target=target,
                converged=converged,
            )
        if f_hi == 0.0 and payload_hi is not None:
            best_shift, best_payload, converged = self._search_hi, payload_hi, True
            return OptimizationResult(
                payload=best_payload,
                best_shift=best_shift,
                iterations=iterations,
                target=target,
                converged=converged,
            )

        # If both endpoints are invalid, fall back to unoptimized payload.
        if f_lo >= self.DEFAULT_INFINITY and f_hi >= self.DEFAULT_INFINITY:
            return OptimizationResult(
                payload=initial_payload,
                best_shift=0.0,
                iterations=iterations,
                target=target,
                converged=False,
            )

        # If no bracket, select the closest evaluated point (legacy would fail).
        if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
            candidate_shift, candidate_payload, converged = pick_best()
            if candidate_payload is None:
                candidate_payload = initial_payload
            return OptimizationResult(
                payload=candidate_payload,
                best_shift=candidate_shift,
                iterations=iterations,
                target=target,
                converged=converged,
            )

        lo = self._search_lo
        hi = self._search_hi
        f_lo_val = f_lo
        f_hi_val = f_hi

        while iterations < self._max_iterations and abs(hi - lo) > self._cache_tolerance:
            mid = 0.5 * (lo + hi)
            f_mid, payload_mid = objective(mid)
            iterations += 1

            if f_mid == 0.0 and payload_mid is not None:
                best_shift, best_payload = mid, payload_mid
                break

            if not math.isfinite(f_mid):
                # Keep legacy behaviour: treat invalid evaluations as a large
                # positive objective value so the bracket search can continue.
                f_mid = self.DEFAULT_INFINITY

            if f_lo_val * f_mid < 0:
                hi, f_hi_val = mid, f_mid
            else:
                lo, f_lo_val = mid, f_mid

        if best_payload is None:
            candidate_shift, candidate_payload, converged = pick_best()
            if candidate_payload is None:
                candidate_payload = initial_payload
            return OptimizationResult(
                payload=candidate_payload,
                best_shift=candidate_shift,
                iterations=iterations,
                target=target,
                converged=converged,
            )

        converged = True
        return OptimizationResult(
            payload=best_payload,
            best_shift=best_shift,
            iterations=iterations,
            target=target,
            converged=converged,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _evaluate(self, shift: float) -> Optional[MeasurementPayload]:
        adjusted = self._write_adjusted_deck(shift)
        payload = self._run_callback(adjusted, self._metadata, shift)
        if not payload or not payload.metrics:
            return None
        degradation = payload.metrics.get("degradation")
        if degradation is None or math.isnan(degradation):
            return None
        return payload

    @staticmethod
    def _get_degradation(payload: Optional[MeasurementPayload]) -> Optional[float]:
        if payload is None or not payload.metrics:
            return None
        value = payload.metrics.get("degradation")
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(numeric):
            return None
        return numeric

    def _write_adjusted_deck(self, shift: float) -> Path:
        if abs(shift) < 1e-18:
            adjusted_content = self._base_content
        else:
            adjusted_content = self._inject_time_shift(self._base_content, shift)

        filename = self._deck_namer(
            f"{self._deck_path.stem}_shift_{self._format_shift_for_name(shift)}.sp"
        )
        adjusted_path = self._engine_dir / filename
        adjusted_path.write_text(adjusted_content)
        return adjusted_path

    def _inject_time_shift(self, content: str, shift: float) -> str:
        target_pin = self._resolve_target_pin()
        if not target_pin or abs(shift) < 1e-18:
            return content

        pin_to_shift, actual_shift = self._resolve_shift_pin(target_pin, shift)
        if not pin_to_shift:
            return content

        pattern = re.compile(rf"(half_tran_tend\+{re.escape(pin_to_shift)}_t\d+)")
        shift_str = self._format_shift(actual_shift)
        return pattern.sub(lambda match: f"{match.group(1)}{shift_str}", content)

    def _resolve_shift_pin(self, target_pin: str, shift: float) -> tuple[str | None, float]:
        """Return (pin_to_shift, positive_shift_seconds).

        We keep the simulation's first half as an initialization window and
        measure with TD=half_tran_tend. Shifting a pin *earlier* (negative shift)
        risks moving its threshold crossing before half_tran_tend, making .meas
        triggers fail. To explore negative effective shifts safely, delay the
        *opposite* pin by the same magnitude instead.
        """

        if shift >= 0:
            return target_pin, shift

        alternate = None
        if target_pin == self._pin:
            alternate = self._related
        elif target_pin == self._related:
            alternate = self._pin

        if not alternate:
            # Fall back to legacy behaviour when we cannot determine an alternate.
            return target_pin, shift

        return alternate, -shift

    def _resolve_target_pin(self) -> str:
        if "hold" in self._timing_type or "removal" in self._timing_type:
            return self._pin
        return self._related

    @staticmethod
    def _format_shift(value: float) -> str:
        if value >= 0:
            return f"+{value:.12g}"
        return f"{value:.12g}"

    @staticmethod
    def _format_shift_for_name(value: float) -> str:
        return f"{value:.3e}"

    @staticmethod
    def _is_valid(payload: MeasurementPayload) -> bool:
        value = payload.metrics.get("degradation")
        return value is not None and not math.isnan(value)

    @staticmethod
    def _extract_indices(arc_id: str | None) -> tuple[int | None, int | None]:
        if not arc_id:
            return None, None
        match = re.search(r"_i1_(\d+)_i2_(\d+)", arc_id, re.IGNORECASE)
        if not match:
            return None, None
        try:
            return int(match.group(1)), int(match.group(2))
        except (IndexError, ValueError):
            return None, None

    # NOTE: The legacy implementation does not apply any i1/i2-specific target-ratio offsets.


class LatchConstraintDeckOptimizer:
    """Optimizer for latch setup/hold constraints using a glitch + correctness criterion.

    Motivation:
    - For latches, the output transition can happen while EN is transparent, i.e.
      before the closing edge. The classic "DegradeDelay (EN->Q)" metric can be
      negative/NaN and the delay-degradation optimizer fails, leaving the
      constraint stuck at the initial/reference shift (e.g. ~10ns).
    - Instead, run a monotonic binary search over an effective time shift and
      require:
        1) The sampled output at the end of simulation matches the expected logic
           value (correctness)
        2) The output does not glitch after the closing edge (stability)
    """

    DEFAULT_SEARCH_LO = -10e-9
    DEFAULT_SEARCH_HI = 10e-9
    DEFAULT_TOLERANCE = 1e-12
    DEFAULT_LOGIC_THRESHOLD_RATIO = 0.5
    DEFAULT_GLITCH_THRESHOLD_RATIO = 0.1
    DEFAULT_MAX_ITERATIONS = 80
    DEFAULT_CACHE_TOLERANCE = 1e-13

    def __init__(
        self,
        deck_path: Path,
        metadata: Dict[str, object],
        engine_dir: Path,
        run_callback: Callable[[Path, Dict[str, object], float], MeasurementPayload],
        *,
        search_lo: float = DEFAULT_SEARCH_LO,
        search_hi: float = DEFAULT_SEARCH_HI,
        tolerance: float = DEFAULT_TOLERANCE,
        logic_threshold_ratio: float = DEFAULT_LOGIC_THRESHOLD_RATIO,
        glitch_threshold_ratio: float = DEFAULT_GLITCH_THRESHOLD_RATIO,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        cache_tolerance: float = DEFAULT_CACHE_TOLERANCE,
        deck_namer: Callable[[str], str] | None = None,
    ) -> None:
        self._deck_path = Path(deck_path)
        self._metadata = dict(metadata)
        self._engine_dir = Path(engine_dir)
        self._run_callback = run_callback
        self._search_lo = float(search_lo)
        self._search_hi = float(search_hi)
        self._tolerance = float(tolerance)
        self._logic_threshold_ratio = float(logic_threshold_ratio)
        self._glitch_threshold_ratio = float(glitch_threshold_ratio)
        self._max_iterations = int(max_iterations)
        self._cache_tolerance = float(cache_tolerance)
        self._deck_namer = deck_namer or (lambda name: name)

        self._base_content = self._deck_path.read_text()
        self._timing_type = str(metadata.get("timing_type", "")).lower()
        self._sim_type = str(metadata.get("sim_type", "")).lower()
        self._pin = str(metadata.get("pin", ""))
        self._related = str(metadata.get("related", ""))

        self._vdd = self._extract_vdd(self._base_content) or self._fallback_vdd()

    def run(self, initial_payload: MeasurementPayload, *, initial_shift: float = 0.0) -> OptimizationResult:
        expected_final = self._expected_final_bit()
        if expected_final is None:
            return OptimizationResult(
                payload=initial_payload,
                best_shift=0.0,
                iterations=0,
                target=0.0,
                converged=False,
            )

        logic_threshold = self._logic_threshold_ratio * self._vdd
        glitch_threshold = self._glitch_threshold_ratio * self._vdd

        cache: Dict[float, MeasurementPayload] = {}

        def cache_get(shift: float) -> MeasurementPayload | None:
            for cached_shift, payload in cache.items():
                if abs(cached_shift - shift) <= self._cache_tolerance:
                    return payload
            return None

        def evaluate(shift: float) -> MeasurementPayload | None:
            cached = cache_get(shift)
            if cached is not None:
                return cached
            payload = self._evaluate(shift)
            if payload is None:
                return None
            cache[shift] = payload
            return payload

        initial_shift = float(initial_shift)

        hi = self._search_hi
        lo = self._search_lo

        payload_hi: MeasurementPayload | None = None
        if abs(initial_shift - hi) <= self._cache_tolerance:
            payload_hi = initial_payload
            cache[initial_shift] = initial_payload

        if payload_hi is None:
            payload_hi = evaluate(hi)
        if payload_hi is None:
            return OptimizationResult(
                payload=initial_payload,
                best_shift=0.0,
                iterations=0,
                target=glitch_threshold,
                converged=False,
            )

        if not self._passes(payload_hi, expected_final, logic_threshold, glitch_threshold):
            # Even the "safe" shift fails: return unoptimized payload.
            return OptimizationResult(
                payload=payload_hi,
                best_shift=hi,
                iterations=0,
                target=glitch_threshold,
                converged=False,
            )

        payload_lo = evaluate(lo)
        if payload_lo is not None and self._passes(payload_lo, expected_final, logic_threshold, glitch_threshold):
            # Boundary is below the search range.
            return OptimizationResult(
                payload=payload_lo,
                best_shift=lo,
                iterations=0,
                target=glitch_threshold,
                converged=True,
            )

        best_shift = hi
        best_payload = payload_hi
        iterations = 0

        while iterations < self._max_iterations and (hi - lo) > self._tolerance:
            mid = 0.5 * (lo + hi)
            payload_mid = evaluate(mid)
            iterations += 1
            if payload_mid is None:
                break

            if self._passes(payload_mid, expected_final, logic_threshold, glitch_threshold):
                best_shift = mid
                best_payload = payload_mid
                hi = mid
            else:
                lo = mid

        converged = (hi - lo) <= self._tolerance
        return OptimizationResult(
            payload=best_payload,
            best_shift=best_shift,
            iterations=iterations,
            target=glitch_threshold,
            converged=converged,
        )

    def _expected_final_bit(self) -> str | None:
        """Return expected output bit at end of sim (for the primary output).

        For latch constraints we can infer the captured data value from:
        - sim_type (setup captures *after* the data transition; hold captures *before*)
        - table_type (rise_constraint/fall_constraint => data rise/fall)
        Then map through output polarity (Q vs QN).
        """

        table_type = str(self._metadata.get("table_type", "")).lower()
        if "rise_constraint" in table_type:
            data_edge = "rise"
        elif "fall_constraint" in table_type:
            data_edge = "fall"
        else:
            return None

        if self._sim_type == "setup":
            captured_data = "1" if data_edge == "rise" else "0"
        elif self._sim_type == "hold":
            captured_data = "0" if data_edge == "rise" else "1"
        else:
            return None

        is_negative = bool(self._metadata.get("primary_output_is_negative"))
        if not is_negative:
            return captured_data
        return "0" if captured_data == "1" else "1"

    @staticmethod
    def _numeric(metric: object | None) -> float | None:
        if metric is None:
            return None
        try:
            value = float(metric)
        except (TypeError, ValueError):
            return None
        if math.isnan(value):
            return None
        return value

    def _passes(
        self,
        payload: MeasurementPayload,
        expected_final: str,
        logic_threshold: float,
        glitch_threshold: float,
    ) -> bool:
        final_q = self._numeric(payload.metrics.get("final_q"))
        if final_q is None:
            return False

        if expected_final == "1":
            if final_q < logic_threshold:
                return False
        else:
            if final_q > logic_threshold:
                return False

        peak_hi = self._numeric(payload.metrics.get("glitch_peak_rise"))
        peak_lo = self._numeric(payload.metrics.get("glitch_peak_fall"))
        if peak_hi is None or peak_lo is None:
            return False

        abs_diff = max(abs(peak_hi - final_q), abs(peak_lo - final_q))
        return abs_diff <= glitch_threshold

    def _evaluate(self, shift: float) -> MeasurementPayload | None:
        adjusted = self._write_adjusted_deck(shift)
        payload = self._run_callback(adjusted, self._metadata, shift)
        if not payload or not payload.metrics:
            return None
        required = ("constraint", "final_q", "glitch_peak_rise", "glitch_peak_fall")
        for key in required:
            if key not in payload.metrics:
                return None
        return payload

    def _write_adjusted_deck(self, shift: float) -> Path:
        if abs(shift) < 1e-18:
            adjusted_content = self._base_content
        else:
            adjusted_content = self._inject_time_shift(self._base_content, shift)

        filename = self._deck_namer(f"{self._deck_path.stem}_shift_{shift:.3e}.sp")
        adjusted_path = self._engine_dir / filename
        adjusted_path.write_text(adjusted_content)
        return adjusted_path

    def _inject_time_shift(self, content: str, shift: float) -> str:
        target_pin = self._resolve_target_pin()
        if not target_pin or abs(shift) < 1e-18:
            return content

        pin_to_shift, actual_shift = self._resolve_shift_pin(target_pin, shift)
        if not pin_to_shift:
            return content

        pattern = re.compile(rf"(half_tran_tend\+{re.escape(pin_to_shift)}_t\d+)")
        shift_str = self._format_shift(actual_shift)
        return pattern.sub(lambda match: f"{match.group(1)}{shift_str}", content)

    def _resolve_shift_pin(self, target_pin: str, shift: float) -> tuple[str | None, float]:
        if shift >= 0:
            return target_pin, shift

        alternate = None
        if target_pin == self._pin:
            alternate = self._related
        elif target_pin == self._related:
            alternate = self._pin

        if not alternate:
            return target_pin, shift

        return alternate, -shift

    def _resolve_target_pin(self) -> str:
        if "hold" in self._timing_type:
            return self._pin
        return self._related

    @staticmethod
    def _format_shift(value: float) -> str:
        if value >= 0:
            return f"+{value:.12g}"
        return f"{value:.12g}"

    @staticmethod
    def _extract_vdd(content: str) -> float | None:
        match = re.search(r"^VVDD\s+\S+\s+0\s+([0-9.eE+-]+)\s*$", content, re.MULTILINE)
        if not match:
            return None
        try:
            value = float(match.group(1))
        except ValueError:
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        return value

    def _fallback_vdd(self) -> float:
        candidate = self._metadata.get("voltage")
        if candidate is None:
            return 1.0
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            return 1.0
        return value if math.isfinite(value) and value > 0 else 1.0


class RemovalDeckOptimizer:
    """Legacy-aligned optimizer for removal constraints.

    Legacy behaviour summary (see legacy/spice/spice_simulator.py:run_removal_optimization):
    - Binary search a time shift until the output glitch disappears.
    - Glitch criterion compares the peak glitch voltage to v(out) at half_tran_tend.
    """

    DEFAULT_SEARCH_LO = 0.0
    DEFAULT_SEARCH_HI = 1e-9
    DEFAULT_TOLERANCE = 1e-12
    DEFAULT_THRESHOLD_RATIO = 0.1

    def __init__(
        self,
        deck_path: Path,
        metadata: Dict[str, object],
        engine_dir: Path,
        run_callback: Callable[[Path, Dict[str, object], float], MeasurementPayload],
        *,
        search_lo: float = DEFAULT_SEARCH_LO,
        search_hi: float = DEFAULT_SEARCH_HI,
        tolerance: float = DEFAULT_TOLERANCE,
        threshold_ratio: float = DEFAULT_THRESHOLD_RATIO,
        max_iterations: int = 80,
        deck_namer: Callable[[str], str] | None = None,
    ) -> None:
        self._deck_path = Path(deck_path)
        self._metadata = dict(metadata)
        self._engine_dir = Path(engine_dir)
        self._run_callback = run_callback
        self._search_lo = float(search_lo)
        self._search_hi = float(search_hi)
        self._tolerance = float(tolerance)
        self._threshold_ratio = float(threshold_ratio)
        self._max_iterations = int(max_iterations)
        self._deck_namer = deck_namer or (lambda name: name)

        self._base_content = self._deck_path.read_text()
        self._timing_type = str(metadata.get("timing_type", "")).lower()
        self._pin = str(metadata.get("pin", ""))
        self._related = str(metadata.get("related", ""))

        self._vdd = self._extract_vdd(self._base_content) or self._fallback_vdd()

    def run(self, initial_payload: MeasurementPayload) -> OptimizationResult:
        threshold = self._threshold_ratio * self._vdd
        low = self._search_lo
        high = self._search_hi

        best_shift = 0.0
        best_payload: MeasurementPayload | None = None
        iterations = 0

        while iterations < self._max_iterations and (high - low) > self._tolerance:
            mid = 0.5 * (low + high)
            payload = self._evaluate(mid)
            iterations += 1
            if payload is None:
                break

            abs_diff = self._glitch_abs_diff(payload)
            if abs_diff is None:
                break

            best_shift = mid
            best_payload = payload

            if abs_diff <= threshold:
                high = mid
            else:
                low = mid

        if best_payload is None:
            return OptimizationResult(
                payload=initial_payload,
                best_shift=0.0,
                iterations=iterations,
                target=threshold,
                converged=False,
            )

        return OptimizationResult(
            payload=best_payload,
            best_shift=best_shift,
            iterations=iterations,
            target=threshold,
            converged=True,
        )

    def _evaluate(self, shift: float) -> Optional[MeasurementPayload]:
        adjusted = self._write_adjusted_deck(shift)
        payload = self._run_callback(adjusted, self._metadata, shift)
        if not payload or not payload.metrics:
            return None
        if self._glitch_abs_diff(payload) is None:
            return None
        return payload

    def _write_adjusted_deck(self, shift: float) -> Path:
        if abs(shift) < 1e-18:
            adjusted_content = self._base_content
        else:
            adjusted_content = self._inject_time_shift(self._base_content, shift)

        filename = self._deck_namer(f"{self._deck_path.stem}_shift_{shift:.3e}.sp")
        adjusted_path = self._engine_dir / filename
        adjusted_path.write_text(adjusted_content)
        return adjusted_path

    def _inject_time_shift(self, content: str, shift: float) -> str:
        target_pin = self._resolve_target_pin()
        if not target_pin:
            return content
        pattern = re.compile(rf"(half_tran_tend\+{re.escape(target_pin)}_t\d+)")
        shift_str = self._format_shift(shift)
        return pattern.sub(lambda match: f"{match.group(1)}{shift_str}", content)

    def _resolve_target_pin(self) -> str:
        if "hold" in self._timing_type or "removal" in self._timing_type:
            return self._pin
        return self._related

    @staticmethod
    def _format_shift(value: float) -> str:
        if value >= 0:
            return f"+{value:.12g}"
        return f"{value:.12g}"

    @staticmethod
    def _extract_vdd(content: str) -> Optional[float]:
        match = re.search(r"^VVDD\s+\S+\s+0\s+([0-9.eE+-]+)\s*$", content, re.MULTILINE)
        if not match:
            return None
        try:
            value = float(match.group(1))
        except ValueError:
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        return value

    def _fallback_vdd(self) -> float:
        candidate = self._metadata.get("voltage")
        if candidate is None:
            return 1.0
        try:
            value = float(candidate)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1.0
        if not math.isfinite(value) or value <= 0:
            return 1.0
        return value

    @staticmethod
    def _glitch_abs_diff(payload: MeasurementPayload) -> Optional[float]:
        if payload is None or not payload.metrics:
            return None
        half = payload.metrics.get("final_q")
        if half is None:
            half = payload.metrics.get("half_tran_tend_q")
        peak = payload.metrics.get("glitch_peak_rise")
        if peak is None:
            peak = payload.metrics.get("glitch_peak_fall")
        try:
            half_f = float(half)  # type: ignore[arg-type]
            peak_f = float(peak)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if math.isnan(half_f) or math.isnan(peak_f):
            return None
        return abs(peak_f - half_f)
