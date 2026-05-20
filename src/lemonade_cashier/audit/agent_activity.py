"""Read-only projection: per-session agent-activity summary.

Scans the hash-chained event log and answers four questions an
investigator or operator asks routinely:

1. *How much did the model get consulted this session?* — total
   ``agent.proposal`` events plus a breakdown by ``decision``.
2. *Which agent(s) and which instance(s) did the work?* — a count
   keyed on the type tag (``agent``) and a finer count keyed on the
   per-instance identity (``agent_id``, A1 schema). Legacy proposals
   without an ``agent_id`` show under a ``None`` key so the gap is
   visible.
3. *How many delegations did the supervisor mint, and did the cart
   actually consume them?* — counts of unique ``delegation_id`` values
   on proposals vs on cart events (A2 schema).
4. *Is there forged-consequence noise in the chain?* — count of
   ``cart.add`` / ``cart.remove_*`` events that carry a
   ``delegation_id`` with no matching prior proposal (orphan).

Stdlib-only per Rule A: this module is part of ``audit/``. It reads
events through the same envelope every other auditor uses, never
mutates the log, and returns a plain dataclass.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..agents.proposals import EVENT_TYPE as PROPOSAL_EVENT_TYPE
from .eventlog import Event, EventLog

# Cart events that may carry a delegation_id. Match the supervisor's
# write surface in ``_line_payload`` + the remove handlers. Listed
# here explicitly so a future cart-mutation verb won't silently slip
# its delegation tracking past the audit projection.
_CART_EVENT_TYPES: frozenset[str] = frozenset(
    {"cart.add", "cart.remove_last", "cart.remove_sku"}
)


@dataclass(frozen=True)
class AgentActivitySummary:
    """One session's worth of agent-activity counts.

    All fields are non-negative integers or dict-of-counts. ``None``
    keys in ``by_agent_id`` represent legacy proposals that predate
    the A1 schema (no ``agent_id`` field on the payload).
    """

    total_proposals: int
    by_decision: dict[str, int] = field(default_factory=dict)
    by_agent: dict[str, int] = field(default_factory=dict)
    by_agent_id: dict[str | None, int] = field(default_factory=dict)
    delegations_minted: int = 0
    delegations_consumed_by_cart: int = 0
    orphan_delegations: int = 0


def summarize(source: EventLog | Path | str) -> AgentActivitySummary:
    """Return an :class:`AgentActivitySummary` for ``source``.

    ``source`` accepts either an :class:`EventLog` instance or a path
    (string or :class:`Path`) to a JSONL event log. The replay CLI
    passes a path; tests usually pass a fixture log.
    """

    events = _load_events(source)

    by_decision: dict[str, int] = defaultdict(int)
    by_agent: dict[str, int] = defaultdict(int)
    by_agent_id: dict[str | None, int] = defaultdict(int)
    proposal_delegation_ids: set[str] = set()
    cart_delegation_ids: list[str] = []
    total_proposals = 0

    for ev in events:
        if ev.type == PROPOSAL_EVENT_TYPE:
            total_proposals += 1
            p = ev.payload or {}
            decision = str(p.get("decision", ""))
            agent = str(p.get("agent", "?"))
            agent_id_raw = p.get("agent_id")
            agent_id: str | None = (
                str(agent_id_raw) if agent_id_raw is not None else None
            )
            delegation_id = p.get("delegation_id")

            by_decision[decision] += 1
            by_agent[agent] += 1
            by_agent_id[agent_id] += 1
            if isinstance(delegation_id, str) and delegation_id:
                proposal_delegation_ids.add(delegation_id)
            continue

        if ev.type in _CART_EVENT_TYPES:
            delegation_id = (ev.payload or {}).get("delegation_id")
            if isinstance(delegation_id, str) and delegation_id:
                cart_delegation_ids.append(delegation_id)

    delegations_consumed_by_cart = len(cart_delegation_ids)
    orphan_delegations = sum(
        1 for d in cart_delegation_ids if d not in proposal_delegation_ids
    )

    return AgentActivitySummary(
        total_proposals=total_proposals,
        by_decision=dict(by_decision),
        by_agent=dict(by_agent),
        by_agent_id=dict(by_agent_id),
        delegations_minted=len(proposal_delegation_ids),
        delegations_consumed_by_cart=delegations_consumed_by_cart,
        orphan_delegations=orphan_delegations,
    )


def _load_events(source: EventLog | Path | str) -> list[Event]:
    if isinstance(source, EventLog):
        return source.read_all()
    return EventLog(Path(source)).read_all()


__all__ = ["AgentActivitySummary", "summarize"]
