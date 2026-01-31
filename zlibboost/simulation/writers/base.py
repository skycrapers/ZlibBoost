"""Base result writer definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional

from zlibboost.simulation.jobs.job import SimulationResult


class ResultWriter:
    """Abstract base class for writing simulation results."""

    SIM_TYPES: tuple[str, ...] = ()

    def supports(self, sim_type: str) -> bool:
        """Return True if this writer handles the provided simulation type."""

        normalized = sim_type.lower()
        return any(normalized == item.lower() for item in self.SIM_TYPES)

    def write(self, result: SimulationResult) -> None:
        """Persist the simulation result."""

        raise NotImplementedError


class ResultWriterRegistry:
    """Registry mapping simulation types to result writers."""

    def __init__(self, writers: Optional[Iterable[ResultWriter]] = None) -> None:
        self._registry: Dict[str, ResultWriter] = {}
        if writers:
            for writer in writers:
                self.register(writer)

    def register(self, writer: ResultWriter) -> None:
        """Register a writer for its supported simulation types."""

        if not writer.SIM_TYPES:
            raise ValueError("Writer must declare SIM_TYPES")
        for sim_type in writer.SIM_TYPES:
            self._registry[sim_type.lower()] = writer

    def get(self, sim_type: str) -> Optional[ResultWriter]:
        """Return the writer for a simulation type, if any."""

        return self._registry.get(sim_type.lower())

    def writers(self) -> Iterable[ResultWriter]:
        """Iterate over registered writer instances (unique)."""

        return set(self._registry.values())
