"""ASR (automatic speech recognition) — interface only.

A future ASR module will run a local Whisper-class model on a rolling
audio buffer and emit ``text_observed`` events shaped like
:class:`Utterance` below. The buffer is *not persisted*: only the
inferred event is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Utterance:
    """One transcribed utterance from the counter microphone."""

    text: str
    confidence: float
    speaker: str  # "attendant" | "customer" | "unknown"
    ts: str


class SpeechSource(Protocol):
    def utterances(self) -> "Iterable[Utterance]":  # noqa: F821
        """Yield :class:`Utterance` events as they arrive."""

    def close(self) -> None: ...


__all__ = ["SpeechSource", "Utterance"]
