"""Simulation job data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from zlibboost.database.models.timing_arc import TimingArc


@dataclass(frozen=True)
class SimulationJob:
    """Immutable description of a single SPICE simulation run."""

    job_id: str
    cell_name: str
    sim_type: str
    deck_path: Path
    output_dir: Path
    arc: Optional[TimingArc] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    requires_serial: bool = False

    def with_metadata(self, **extra: Any) -> "SimulationJob":
        """Return a copy with additional metadata merged in."""

        merged = {**self.metadata, **extra}
        return SimulationJob(
            job_id=self.job_id,
            cell_name=self.cell_name,
            sim_type=self.sim_type,
            deck_path=self.deck_path,
            output_dir=self.output_dir,
            arc=self.arc,
            metadata=merged,
            requires_serial=self.requires_serial,
        )


@dataclass
class SimulationResult:
    """Structured outcome of a simulation job."""

    job: SimulationJob
    status: str
    engine: str
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    elapsed: float | None = None

    def is_success(self) -> bool:
        """Return True when the job completed successfully."""

        return self.status.lower() == "completed" and self.error is None
