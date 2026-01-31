"""Base classes and registries for measurement parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


@dataclass(slots=True)
class MeasurementPayload:
    """Structured data extracted from simulator measurement artifacts."""

    metrics: Dict[str, Any]
    artifacts: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class MeasurementParser:
    """Abstract measurement parser."""

    SUPPORTED_ENGINES: tuple[str, ...] = ()

    def handles(self, engine: str) -> bool:
        """Return True if this parser supports the given engine."""

        normalized = engine.lower()
        return any(normalized == item.lower() for item in self.SUPPORTED_ENGINES)

    def parse(
        self,
        deck_path: Path,
        measurement_path: Path,
        metadata: Dict[str, Any],
    ) -> MeasurementPayload:
        """Parse simulator measurement artifacts into structured metrics."""

        raise NotImplementedError


class MeasurementParserRegistry:
    """Registry for mapping engines to measurement parsers."""

    def __init__(self, parsers: Optional[Iterable[MeasurementParser]] = None) -> None:
        self._registry: Dict[str, MeasurementParser] = {}
        if parsers:
            for parser in parsers:
                self.register(parser)

    def register(self, parser: MeasurementParser) -> None:
        """Register a parser for its supported engines."""

        if not parser.SUPPORTED_ENGINES:
            raise ValueError("Parser must declare SUPPORTED_ENGINES")
        for engine in parser.SUPPORTED_ENGINES:
            self._registry[engine.lower()] = parser

    def get(self, engine: str) -> Optional[MeasurementParser]:
        """Return the parser for the specified engine, if any."""

        return self._registry.get(engine.lower())
