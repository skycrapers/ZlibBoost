"""Mock simulation executor used in tests and local development."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .base import BaseSimulationExecutor


class MockSimulationExecutor(BaseSimulationExecutor):
    """Deterministic executor that emulates a simulator without external tools."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(engine="mock", **kwargs)

    def _prepare_environment(self, output_dir: Path) -> None:
        """Ensure simulation directory exists for artifact writing."""
        (output_dir / "simulation").mkdir(parents=True, exist_ok=True)

    def _run_engine(self, deck_path: Path, metadata: Dict[str, Any], engine_dir: Path) -> None:
        """Skip actual engine invocation for deterministic results."""
        # Nothing to run for the mock engine.
        return

    def _collect_results(
        self,
        deck_path: Path,
        metadata: Dict[str, Any],
        output_dir: Path,
        engine_dir: Path,
    ) -> Dict[str, Any]:
        """Return predictable result payload used by tests."""
        cell = metadata.get("cell")
        arc_id = metadata.get("arc_id", deck_path.stem)
        result = {
            "engine": "mock",
            "status": "completed",
            "cell": cell,
            "arc_id": arc_id,
            "pin": metadata.get("pin"),
            "related": metadata.get("related"),
        }
        return result

    def _write_artifacts(self, result: Dict[str, Any], output_dir: Path, engine_dir: Path) -> None:
        """Write per-arc JSON artifact inside the simulation directory."""
        sim_dir = output_dir / "simulation"
        sim_dir.mkdir(parents=True, exist_ok=True)
        arc_id = result.get("arc_id", "arc")
        artifact_path = sim_dir / f"{arc_id}.json"
        artifact_path.write_text(json.dumps(result, indent=2))
