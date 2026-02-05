"""Base classes for SPICE simulation executors."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from zlibboost.core.logger import get_logger
from zlibboost.simulation.iteration import IterationTracker

logger = get_logger(__name__)


class BaseSimulationExecutor:
    """Common interface for all simulation executors."""

    ENGINE_COMMANDS = {
        "hspice": ["hspice", "-i", "{deck}", "-o", "{workdir}"],
        "spectre": ["spectre", "{deck}", "-outdir", "{workdir}"],
        "ngspice": ["ngspice", "-b", "{deck}"],
        "mock": ["mock"],  # logical placeholder for tests
    }

    def __init__(self, engine: Optional[str] = None, **kwargs: Any) -> None:
        self.options = kwargs
        explicit = engine or kwargs.get("engine") or kwargs.get("spice_simulator")
        self.engine = (explicit or "ngspice").lower()
        self.timeout: Optional[float] = kwargs.get("timeout")

    # ------------------------------------------------------------------
    # Template method
    # ------------------------------------------------------------------
    def simulate(self, deck_path: Path, metadata: Dict[str, Any], output_dir: Path) -> Dict[str, Any]:
        """Simulate a SPICE deck and return structured results."""

        deck_path = Path(deck_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir = output_dir.resolve()
        metadata = metadata or {}

        logger.debug(
            "Executing simulation deck=%s engine=%s metadata=%s", deck_path, self.engine, metadata
        )

        start = time.perf_counter()

        self._prepare_environment(output_dir)
        engine_dir = self._resolve_engine_workdir(deck_path, metadata, output_dir)
        engine_dir.mkdir(parents=True, exist_ok=True)
        engine_dir = engine_dir.resolve()
        self._run_engine(deck_path, metadata, engine_dir)
        result = self._collect_results(deck_path, metadata, output_dir, engine_dir) or {}
        self._write_artifacts(result, output_dir, engine_dir)
        self.postprocess(result, output_dir, engine_dir)

        elapsed = time.perf_counter() - start
        result.setdefault("engine", self.engine)
        result.setdefault("status", "completed")
        result.setdefault("deck", str(deck_path))
        result.setdefault("metadata", metadata)
        result["elapsed"] = elapsed

        logger.debug("Simulation finished deck=%s status=%s", deck_path, result.get("status"))

        return result

    def _prepare_environment(self, output_dir: Path) -> None:
        """Prepare output directories or temporary state before running."""
        # Default implementation ensures the directory exists.
        output_dir.mkdir(parents=True, exist_ok=True)

    def _run_engine(self, deck_path: Path, metadata: Dict[str, Any], engine_dir: Path) -> None:
        """Invoke the underlying simulator implementation."""
        self._invoke_engine(deck_path, engine_dir)

    def _collect_results(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        output_dir: Path,
        engine_dir: Path,
    ) -> Dict[str, Any]:
        """Parse simulator outputs into a structured payload."""
        return {}

    def _write_artifacts(self, result: Dict[str, Any], output_dir: Path, engine_dir: Path) -> None:
        """Write any additional artifacts (JSON summaries, logs, etc.)."""
        summary_dir = output_dir / "simulation"
        summary_dir.mkdir(parents=True, exist_ok=True)
        summary_path = summary_dir / "summary.json"
        summary = {
            "engine": result.get("engine", self.engine),
            "status": result.get("status", "completed"),
            "jobs": [result],
        }
        summary_path.write_text(json.dumps(summary, indent=2))

    def postprocess(self, result: Dict[str, Any], output_dir: Path, engine_dir: Path) -> None:
        """Hook for subclasses to perform additional processing after artifacts are written."""

    # ------------------------------------------------------------------
    # Engine helpers
    # ------------------------------------------------------------------
    def _resolve_engine_workdir(self, deck_path: Path, metadata: Dict[str, Any], output_dir: Path) -> Path:
        """Return the directory used as the simulator work/output directory."""
        return output_dir

    def _invoke_engine(self, deck_path: Path, engine_dir: Path) -> None:
        """Run the configured simulator engine."""

        cmd = self._build_command(deck_path, engine_dir)
        if not cmd:
            logger.debug("No command built for engine=%s, skipping invocation", self.engine)
            return

        logger.debug("Running command: %s", " ".join(shlex.quote(part) for part in cmd))
        subprocess.run(
            cmd,
            cwd=str(engine_dir),
            check=True,
            timeout=self.timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _build_command(self, deck_path: Path, engine_dir: Path) -> Optional[list[str]]:
        """Return the command list for the current engine."""

        template = self.ENGINE_COMMANDS.get(self.engine)
        if not template:
            raise ValueError(f"Unsupported engine '{self.engine}'")

        if template == ["mock"]:
            return None

        substitutions = {
            "deck": str(deck_path),
            "workdir": str(engine_dir),
        }
        return [part.format(**substitutions) for part in template]

    @staticmethod
    def _stage_iterated_deck(
        deck_path: Path,
        engine_dir: Path,
        tracker: IterationTracker,
    ) -> Path:
        staged_name = tracker.tag(Path(deck_path).name)
        staged_path = Path(engine_dir) / staged_name
        if staged_path.resolve() == Path(deck_path).resolve():
            return Path(deck_path)
        staged_path.write_text(Path(deck_path).read_text())
        return staged_path

    # ------------------------------------------------------------------
    # Result helpers
    # ------------------------------------------------------------------
    def _build_result_payload(
        self,
        metadata: Optional[Dict[str, Any]],
        arc_id: str,
        *,
        metrics: Optional[Dict[str, Any]] = None,
        artifacts: Optional[Dict[str, Any]] = None,
        status: str = "completed",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compose the structured payload returned by executors."""

        base_metadata: Dict[str, Any] = dict(metadata or {})
        if extra_metadata:
            base_metadata.update(extra_metadata)

        cell_name = base_metadata.get("cell")
        return {
            "engine": self.engine,
            "status": status,
            "cell": cell_name,
            "arc_id": arc_id,
            "metrics": dict(metrics or {}),
            "artifacts": dict(artifacts or {}),
            "metadata": base_metadata,
        }
