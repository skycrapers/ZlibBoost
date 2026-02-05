"""Iteration helpers for iterative simulation decks."""

from __future__ import annotations

from dataclasses import dataclass
import re

_ITER_PREFIX_RE = re.compile(r"^iter\d{4}_", re.IGNORECASE)


@dataclass(slots=True)
class IterationTracker:
    """Track and tag iteration numbers for per-arc simulation decks."""

    prefix: str = "iter"
    width: int = 4
    counter: int = 0

    def tag(self, name: str) -> str:
        """Prefix name with the next iteration tag if not already tagged."""

        if _ITER_PREFIX_RE.match(name):
            return name
        self.counter += 1
        return f"{self.prefix}{self.counter:0{self.width}d}_{name}"

    @staticmethod
    def strip_prefix(name: str) -> str:
        """Strip a leading iteration tag from a name."""

        return _ITER_PREFIX_RE.sub("", name, count=1)
