"""Agent-proposal event writer.

Every LLM-assisted action in the cashier writes an ``agent.proposal``
event into the same hash-chained JSONL as the cart and till events.
The proposal records exactly what the model saw, what it said, and
whether the supervisor accepted, rejected, or asked for confirmation.

The audit story this delivers:

* An investigator can read the chain alone (no module imports needed)
  and reconstruct every agent decision: input phrase → output phrase →
  supervisor verdict.
* A forged "the model proposed X" claim is detectable because the
  proposal and its consequence (``cart.add``, ``cart.remove_*``) are
  cryptographically tied by the hash chain.
* Disabled or unreachable agents leave **no proposal events**, so
  investigators can also distinguish "the model said nothing" from
  "the model said something we ignored".

Schema (payload of ``agent.proposal``):

::

    {
      "agent":      "lemonade" | "flm" | "gaia" | "qa" | "summarizer",
      "kind":       "normalize" | "chat_response" | "summarize",
      "input":      <opaque, agent-specific>,
      "output":     <opaque, agent-specific>,
      "confidence": <float in [0, 1]>,
      "decision":   "accepted" | "rejected" | "needs_confirmation" |
                    "unreachable" | "out_of_capability"
    }

The shape is opaque on purpose — different agents have different I/O
forms — but the top-level keys are canonical so a generic UI can
render any proposal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..audit.eventlog import Event, EventLog

EVENT_TYPE = "agent.proposal"

Decision = Literal[
    "accepted",
    "rejected",
    "needs_confirmation",
    "unreachable",
    "out_of_capability",
]

ProposalKind = Literal["normalize", "chat_response", "summarize"]


@dataclass(frozen=True)
class Proposal:
    """One agent's proposal record. Roundtrips through ``write`` /
    ``from_event``."""

    agent: str
    kind: ProposalKind
    input: Any
    output: Any
    confidence: float
    decision: Decision

    def to_payload(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "kind": self.kind,
            "input": self.input,
            "output": self.output,
            "confidence": float(self.confidence),
            "decision": self.decision,
        }

    @classmethod
    def from_event(cls, event: Event) -> "Proposal":
        if event.type != EVENT_TYPE:
            raise ValueError(f"expected {EVENT_TYPE} event, got {event.type}")
        p = event.payload or {}
        return cls(
            agent=str(p.get("agent", "?")),
            kind=str(p.get("kind", "?")),  # type: ignore[arg-type]
            input=p.get("input"),
            output=p.get("output"),
            confidence=float(p.get("confidence", 0.0)),
            decision=str(p.get("decision", "rejected")),  # type: ignore[arg-type]
        )


def write(
    log: EventLog,
    *,
    agent: str,
    kind: ProposalKind,
    input: Any,
    output: Any,
    confidence: float,
    decision: Decision,
) -> Event:
    """Append one :data:`EVENT_TYPE` event. Returns the resulting Event."""

    payload = Proposal(
        agent=agent,
        kind=kind,
        input=input,
        output=output,
        confidence=max(0.0, min(1.0, float(confidence))),
        decision=decision,
    ).to_payload()
    return log.append(EVENT_TYPE, payload)


def proposals_from_events(events: list[Event]) -> list[Proposal]:
    """Materialize every ``agent.proposal`` event into a list of :class:`Proposal`."""

    return [Proposal.from_event(e) for e in events if e.type == EVENT_TYPE]


__all__ = [
    "Decision",
    "EVENT_TYPE",
    "Proposal",
    "ProposalKind",
    "proposals_from_events",
    "write",
]
