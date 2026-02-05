"""MPW simulation executor."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import subprocess

from zlibboost.simulation.optimizers.mpw import MpwDeckOptimizer, MpwOptimizationResult
from zlibboost.simulation.parsers import (
    MeasurementParserRegistry,
    MpwSpectreParser,
    MpwHspiceParser,
    MeasurementPayload,
)
from zlibboost.simulation.iteration import IterationTracker

from .base import BaseSimulationExecutor


logger = logging.getLogger(__name__)


class MpwSimulationExecutor(BaseSimulationExecutor):
    """Executor for minimum pulse width characterization decks."""

    _INDEX_PATTERN = re.compile(r"_i1_(\d+)", re.IGNORECASE)

    def __init__(
        self,
        parser_registry: MeasurementParserRegistry | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._parser_registry = parser_registry or MeasurementParserRegistry(
            [MpwSpectreParser(), MpwHspiceParser()]
        )

    def simulate(self, deck_path: Path, metadata: Dict[str, Any], output_dir: Path) -> Dict[str, Any]:
        deck_path = Path(deck_path).resolve()
        output_dir = Path(output_dir).resolve()
        metadata = metadata or {}
        output_dir.mkdir(parents=True, exist_ok=True)

        start = time.perf_counter()
        self._prepare_environment(output_dir)
        engine_dir = self._resolve_engine_workdir(deck_path, metadata, output_dir)
        engine_dir.mkdir(parents=True, exist_ok=True)
        engine_dir = engine_dir.resolve()
        iter_tracker = IterationTracker()

        parser_available = self._parser_registry.get(self.engine) is not None
        if not parser_available:
            try:
                iter_deck = self._stage_iterated_deck(deck_path, engine_dir, iter_tracker)
                self._invoke_engine(iter_deck, engine_dir)
            except subprocess.CalledProcessError:
                pass
            measurement = self._locate_measurement(iter_deck, engine_dir)
            artifacts: Dict[str, Any] = {}
            if measurement and measurement.exists():
                artifacts["measurement_file"] = str(measurement)
            arc_id = metadata.get("arc_id") or IterationTracker.strip_prefix(deck_path.stem)
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

        initial_deck = self._stage_iterated_deck(deck_path, engine_dir, iter_tracker)
        initial_payload = self._simulate_single(initial_deck, metadata, engine_dir)
        if initial_payload is None:
            payload = MeasurementPayload(metrics={})
            arc_id = metadata.get("arc_id") or IterationTracker.strip_prefix(deck_path.stem)
            result = self._build_result(
                deck_path=deck_path,
                metadata=metadata,
                payload=payload,
                arc_id=arc_id,
                status="missing_measurement",
                optimization=None,
            )
        else:
            optimized_payload, optimization = self._maybe_optimize(
                deck_path, metadata, engine_dir, initial_payload, iter_tracker=iter_tracker
            )
            status = "completed" if optimized_payload.metrics else "missing_measurement"
            arc_id = metadata.get("arc_id") or IterationTracker.strip_prefix(deck_path.stem)
            result = self._build_result(
                deck_path=deck_path,
                metadata=metadata,
                payload=optimized_payload,
                arc_id=arc_id,
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

    def _prepare_environment(self, output_dir: Path) -> None:
        (output_dir / "simulation").mkdir(parents=True, exist_ok=True)

    def _resolve_engine_workdir(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        output_dir: Path,
    ) -> Path:
        sim_type = metadata.get("sim_type", "mpw")
        arc_id = metadata.get("arc_id") or IterationTracker.strip_prefix(deck_path.stem)
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
        filename = f"{arc_id}_mpw.json"
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

    def _simulate_single(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        engine_dir: Path,
    ) -> Optional[MeasurementPayload]:
        try:
            self._invoke_engine(deck_path, engine_dir)
        except subprocess.CalledProcessError:
            return None
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
        iter_tracker: IterationTracker | None = None,
    ) -> Tuple[MeasurementPayload, Optional[MpwOptimizationResult]]:
        tracker = iter_tracker or IterationTracker()
        try:
            optimizer = MpwDeckOptimizer(
                deck_path=deck_path,
                metadata=metadata,
                engine_dir=engine_dir,
                run_callback=lambda adjusted, meta, width: self._simulate_single(
                    self._stage_iterated_deck(adjusted, engine_dir, tracker),
                    meta,
                    engine_dir,
                )
                or MeasurementPayload(metrics={}),
                deck_namer=tracker.tag,
            )
        except (ValueError, OSError) as exc:
            logger.debug("Skipping MPW optimization for %s: %s", deck_path, exc)
            return payload, None
        result = optimizer.run(payload)
        optimized_metrics = dict(result.payload.metrics)
        optimized_artifacts = dict(payload.artifacts)
        optimized_artifacts.update(result.payload.artifacts)
        optimized_metadata = dict(payload.metadata)
        optimized_metadata.update(result.payload.metadata)
        optimized_payload = MeasurementPayload(
            metrics=optimized_metrics,
            artifacts=optimized_artifacts,
            metadata=optimized_metadata,
        )
        return optimized_payload, result

    def _build_result(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        payload: MeasurementPayload,
        arc_id: str,
        status: str,
        optimization: Optional[MpwOptimizationResult],
    ) -> Dict[str, Any]:
        metrics = dict(payload.metrics)
        i1 = self._extract_index(arc_id)
        if i1 is not None:
            metrics.setdefault("i1", i1)

        artifacts = dict(payload.artifacts)
        payload_metadata = dict(metadata)
        payload_metadata.setdefault("arc_id", arc_id)
        if optimization is not None:
            payload_metadata["optimization"] = {
                "best_width": optimization.best_width_ns,
                "iterations": optimization.iterations,
                "converged": optimization.converged,
            }

        return {
            "arc_id": arc_id,
            "status": status,
            "metrics": metrics,
            "artifacts": artifacts,
            "metadata": payload_metadata,
            "deck": str(deck_path),
        }

    @classmethod
    def _extract_index(cls, arc_id: str | None) -> int | None:
        if not arc_id:
            return None
        match = cls._INDEX_PATTERN.search(arc_id)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (IndexError, ValueError):
            return None
