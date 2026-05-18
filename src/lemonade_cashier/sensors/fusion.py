"""Sensor fusion — interface only.

A future fusion module will reconcile overlapping observations from
the camera and speech streams into a single :class:`FusedEvent` that
the supervisor can treat as if it were a typed input. The fusion
module is itself an *agent*: it never names a SKU, it proposes a
normalized phrase that goes back through the supervisor's
confirmation gate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from .camera import Observation
from .speech import Utterance


@dataclass(frozen=True)
class FusedEvent:
    """Output of the fusion layer — a candidate cashier input."""

    phrase: str
    confidence: float
    evidence: tuple[Observation | Utterance, ...]
    ts: str  # ISO-8601 UTC


class FusionSource(Protocol):
    def events(self) -> Iterable[FusedEvent]:
        """Yield :class:`FusedEvent` items as they arrive."""

    def close(self) -> None: ...


__all__ = ["FusedEvent", "FusionSource"]
