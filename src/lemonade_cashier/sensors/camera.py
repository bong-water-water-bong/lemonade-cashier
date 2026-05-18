"""PoE camera pipeline — interface only.

A PoE camera at the counter is expected to emit ``product_observed``
events shaped like the :class:`Observation` below. The cashier core
treats those exactly the same as a typed line: it routes them through
the supervisor's confirmation gate, never directly into the cart.

The reason this is just an interface today is the spec's principle:
**reliability before autonomy**. We commit to the event shape now so a
later contributor can implement the camera path without touching
``core/`` or ``audit/``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BBox:
    """Pixel-space bounding box (left, top, right, bottom)."""

    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class Observation:
    """One observed product candidate from a single video frame."""

    candidate_skus: tuple[str, ...]
    confidence: float
    bbox: BBox
    frame_id: int
    ts: str  # ISO-8601 UTC


class CameraSource(Protocol):
    """The minimal contract a camera implementation must satisfy."""

    def observations(self) -> Iterable[Observation]:
        """Yield :class:`Observation` events as they arrive."""

    def close(self) -> None:
        """Release any underlying resources (sockets, capture handles)."""


__all__ = ["BBox", "CameraSource", "Observation"]
