"""Constraint timing simulation executor."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from zlibboost.simulation.optimizers.constraint import (
    ConstraintDeckOptimizer,
    OptimizationResult,
    RemovalDeckOptimizer,
)
from zlibboost.simulation.parsers import (
    ConstraintSpectreParser,
    ConstraintHspiceParser,
    MeasurementParserRegistry,
    MeasurementPayload,
)

from .base import BaseSimulationExecutor


class ConstraintSimulationExecutor(BaseSimulationExecutor):
    """Executor for setup/hold/recovery/removal characterization decks."""

    _INDEX_PATTERN = re.compile(r"_i1_(\d+)_i2_(\d+)", re.IGNORECASE)
    _OPTIMIZABLE_TYPES = {"setup", "hold", "recovery", "removal"}

    def __init__(
        self,
        parser_registry: MeasurementParserRegistry | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._parser_registry = parser_registry or MeasurementParserRegistry(
            [ConstraintSpectreParser(), ConstraintHspiceParser()]
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def simulate(self, deck_path: Path, metadata: Dict[str, Any], output_dir: Path) -> Dict[str, Any]:
        """Execute the constraint simulation flow with optional optimization."""

        deck_path = Path(deck_path).resolve()
        output_dir = Path(output_dir).resolve()
        metadata = metadata or {}

        output_dir.mkdir(parents=True, exist_ok=True)

        start = time.perf_counter()
        self._prepare_environment(output_dir)
        engine_dir = self._resolve_engine_workdir(deck_path, metadata, output_dir)
        engine_dir.mkdir(parents=True, exist_ok=True)
        engine_dir = engine_dir.resolve()

        parser_available = self._parser_registry.get(self.engine) is not None
        if not parser_available:
            self._invoke_engine(deck_path, engine_dir)
            measurement = self._locate_measurement(deck_path, engine_dir)
            artifacts: Dict[str, Any] = {}
            if measurement and measurement.exists():
                artifacts["measurement_file"] = str(measurement)
            arc_id = metadata.get("arc_id", deck_path.stem)
            result = self._build_result_payload(
                metadata,
                arc_id,
                artifacts=artifacts,
                status="completed",
                extra_metadata={"parser_status": "skipped"},
            )
            elapsed = time.perf_counter() - start
            result["engine"] = self.engine
            result["elapsed"] = elapsed
            result.setdefault("deck", str(deck_path))
            self._write_artifacts(result, output_dir, engine_dir)
            self.postprocess(result, output_dir, engine_dir)
            return result

        initial_deck = deck_path
        initial_shift = self._resolve_initial_shift(metadata)
        if initial_shift:
            # Start from a "safe" stimulus (large positive effective shift) so the
            # first measurement is likely to produce a valid DegradeDelay. This
            # avoids wasting a run at zero-shift that often fails for constraints.
            shifter = ConstraintDeckOptimizer(
                deck_path=deck_path,
                metadata=metadata,
                engine_dir=engine_dir,
                run_callback=lambda *_args, **_kwargs: MeasurementPayload(metrics={}),
                reference_shift=initial_shift,
            )
            initial_deck = shifter._write_adjusted_deck(initial_shift)

        initial_payload = self._simulate_single(initial_deck, metadata, engine_dir)
        if initial_payload is None:
            result = self._build_result(
                deck_path=deck_path,
                metadata=metadata,
                payload=MeasurementPayload(metrics={}),
                arc_id=metadata.get("arc_id", deck_path.stem),
                status="missing_measurement",
            )
        else:
            optimized_payload, optimization = self._maybe_optimize(
                deck_path, metadata, engine_dir, initial_payload, initial_shift=initial_shift
            )
            status = "completed" if optimized_payload.metrics else "missing_measurement"
            result = self._build_result(
                deck_path=deck_path,
                metadata=metadata,
                payload=optimized_payload,
                arc_id=metadata.get("arc_id", deck_path.stem),
                status=status,
                optimization=optimization,
            )

        elapsed = time.perf_counter() - start
        result["engine"] = self.engine
        result["elapsed"] = elapsed
        result.setdefault("status", "completed")
        result.setdefault("deck", str(deck_path))
        result.setdefault("metadata", metadata)

        self._write_artifacts(result, output_dir, engine_dir)
        self.postprocess(result, output_dir, engine_dir)

        return result

    @staticmethod
    def _resolve_initial_shift(metadata: Dict[str, Any]) -> float:
        """Return the initial effective time shift (in seconds) for constraint sims.

        The optimizer and measurement templates assume the first half of the
        simulation window is used for initialization, and most measurements use
        TD=half_tran_tend. Starting at a positive "safe" shift greatly improves
        the probability that DegradeDelay is measurable on the first run.
        """

        timing_type = str(metadata.get("timing_type", "")).lower()
        # Removal uses a different optimization loop; keep legacy behaviour.
        if "removal" in timing_type:
            return 0.0

        raw = metadata.get("constraint_initial_shift")
        if raw is None:
            return ConstraintDeckOptimizer.DEFAULT_REFERENCE_SHIFT

        try:
            numeric = float(raw)
        except (TypeError, ValueError):
            return ConstraintDeckOptimizer.DEFAULT_REFERENCE_SHIFT

        if abs(numeric) <= 1e-18:
            return 0.0

        # Mirror legacy normalization used elsewhere: treat values larger than
        # 1e-6 as nanoseconds, otherwise as seconds.
        if abs(numeric) > 1e-6:
            numeric *= 1e-9

        return abs(numeric)

    def _prepare_environment(self, output_dir: Path) -> None:
        (output_dir / "simulation").mkdir(parents=True, exist_ok=True)

    def _resolve_engine_workdir(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        output_dir: Path,
    ) -> Path:
        sim_type = metadata.get("sim_type", "constraint")
        arc_id = metadata.get("arc_id", deck_path.stem)
        workdir = output_dir / sim_type / arc_id
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir

    def _write_artifacts(
        self,
        result: Dict[str, Any],
        output_dir: Path,
        engine_dir: Path,
    ) -> None:
        sim_dir = output_dir / "simulation"
        sim_dir.mkdir(parents=True, exist_ok=True)
        arc_id = result.get("arc_id", "arc")
        filename = f"{arc_id}_constraint.json"
        (sim_dir / filename).write_text(json.dumps(result, indent=2))

    def _locate_measurement(self, deck_path: Path, engine_dir: Path) -> Path | None:
        suffixes = [".measure", ".mt0"]
        if self.engine in {"hspice", "ngspice"}:
            suffixes = [".mt0", ".measure"]

        for suffix in suffixes:
            candidate = engine_dir / f"{deck_path.stem}{suffix}"
            if candidate.exists():
                return candidate
            adjacent = deck_path.with_suffix(suffix)
            if adjacent.exists():
                return adjacent
        return None

    @classmethod
    def _extract_indices(cls, arc_id: str | None) -> tuple[int | None, int | None]:
        if not arc_id:
            return None, None
        match = cls._INDEX_PATTERN.search(arc_id)
        if not match:
            return None, None
        try:
            return int(match.group(1)), int(match.group(2))
        except (IndexError, ValueError):
            return None, None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _simulate_single(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        engine_dir: Path,
    ) -> Optional[MeasurementPayload]:
        """Run a single simulation pass and parse measurements."""

        self._invoke_engine(deck_path, engine_dir)
        measurement = self._locate_measurement(deck_path, engine_dir)
        if not measurement or not measurement.exists():
            return None

        parser = self._parser_registry.get(self.engine)
        if parser is None:
            return None

        payload = parser.parse(deck_path, measurement, metadata)
        payload.artifacts.setdefault("measurement_file", str(measurement))
        return payload

    def _maybe_optimize(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        engine_dir: Path,
        payload: MeasurementPayload,
        *,
        initial_shift: float = 0.0,
    ) -> tuple[MeasurementPayload, Optional[OptimizationResult]]:
        sim_type = str(metadata.get("sim_type", "")).lower()
        timing_type = str(metadata.get("timing_type", "")).lower()
        if (
            sim_type not in self._OPTIMIZABLE_TYPES
            and timing_type not in self._OPTIMIZABLE_TYPES
        ):
            return payload, None

        run_callback = (
            lambda adjusted, meta, shift: self._simulate_single(adjusted, meta, engine_dir)
            or MeasurementPayload(metrics={})
        )

        if "removal" in timing_type:
            if "half_tran_tend_q" not in payload.metrics:
                return payload, None
            if (
                "glitch_peak_rise" not in payload.metrics
                and "glitch_peak_fall" not in payload.metrics
            ):
                return payload, None
            optimizer = RemovalDeckOptimizer(
                deck_path=deck_path,
                metadata=metadata,
                engine_dir=engine_dir,
                run_callback=run_callback,
            )
            result = optimizer.run(payload)
        else:
            if "degradation" not in payload.metrics:
                return payload, None
            optimizer = ConstraintDeckOptimizer(
                deck_path=deck_path,
                metadata=metadata,
                engine_dir=engine_dir,
                run_callback=run_callback,
            )
            result = optimizer.run(payload, initial_shift=initial_shift)
        metrics = dict(payload.metrics)
        metrics.update(result.payload.metrics)
        metrics.setdefault("constraint", payload.metrics.get("constraint"))
        metrics["time_shift"] = result.best_shift
        metrics["optimization_iterations"] = result.iterations
        metrics["optimization_target"] = result.target
        metrics["optimization_converged"] = result.converged

        merged_artifacts = dict(payload.artifacts)
        merged_artifacts.update(result.payload.artifacts)
        merged_metadata = dict(payload.metadata)
        merged_metadata.update(result.payload.metadata)
        merged_metadata["optimization"] = {
            "best_shift": result.best_shift,
            "iterations": result.iterations,
            "target": result.target,
            "converged": result.converged,
        }

        merged_payload = MeasurementPayload(
            metrics=metrics,
            artifacts=merged_artifacts,
            metadata=merged_metadata,
        )
        return merged_payload, result

    def _build_result(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        payload: MeasurementPayload,
        arc_id: str,
        status: str,
        optimization: Optional[OptimizationResult] = None,
    ) -> Dict[str, Any]:
        metrics = dict(payload.metrics)
        i1, i2 = self._extract_indices(arc_id)
        if i1 is not None:
            metrics.setdefault("i1", i1)
        if i2 is not None:
            metrics.setdefault("i2", i2)

        artifacts = dict(payload.artifacts)
        payload_metadata = dict(metadata)
        payload_metadata.update(payload.metadata)

        result: Dict[str, Any] = {
            "engine": self.engine,
            "status": status,
            "cell": metadata.get("cell"),
            "arc_id": arc_id,
            "metrics": metrics,
            "artifacts": artifacts,
            "metadata": payload_metadata,
        }
        if optimization:
            result["optimization"] = {
                "best_shift": optimization.best_shift,
                "target": optimization.target,
                "iterations": optimization.iterations,
                "converged": optimization.converged,
            }
        return result
