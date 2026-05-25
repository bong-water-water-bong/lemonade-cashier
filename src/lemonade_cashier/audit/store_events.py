"""Read-only projection from cashier audit JSONL to `store.event.v1`.

The cashier's native log keeps its internal event names (`transaction.close`,
`cart.add`, and friends) because replay, tamper checks, and safety reports
depend on them. This module projects that native stream into Lemonade Store's
cross-department envelope without rewriting the source log.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from .eventlog import Event
from .replay import replay

STORE_SCHEMA_VERSION = "store.event.v1"
STORE_EVENT_TYPE_TRANSACTION_CLOSED = "cashier.transaction.closed"


def project_store_events(
    events: Iterable[Event],
    *,
    store_id: str = "tie-dye-farms",
    source: str = "lemonade-cashier",
) -> Iterator[dict[str, Any]]:
    """Yield Lemonade Store envelope events for closed cashier transactions.

    The projection currently emits only `cashier.transaction.closed`. That is
    enough for accounting to consume completed sales while keeping native
    cashier replay unchanged.
    """

    prefix: list[Event] = []
    for event in events:
        prefix.append(event)
        if event.type != "transaction.close":
            continue
        state = replay(prefix).to_state()
        yield _closed_transaction_event(event, state, store_id=store_id, source=source)


def _closed_transaction_event(
    event: Event,
    state: dict[str, object],
    *,
    store_id: str,
    source: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "original_seq": event.seq,
        "original_hash": event.hash,
        "original_type": event.type,
        "opened_at": state.get("opened_at"),
        "closed_at": state.get("closed_at"),
        "items": state.get("items", []),
        "subtotal": state.get("subtotal", "0.00"),
        "taxable_subtotal": state.get("taxable_subtotal", "0.00"),
        "tax": state.get("tax", "0.00"),
        "total": state.get("total", "0.00"),
    }
    if "tender" in state:
        payload["cash_tendered"] = state["tender"]
    if "change" in state:
        payload["change"] = state["change"]

    return {
        "schema_version": STORE_SCHEMA_VERSION,
        "event_id": _store_event_id(event),
        "ts": event.ts,
        "store_id": _event_store_id(event, fallback=store_id),
        "department": "cashier",
        "type": STORE_EVENT_TYPE_TRANSACTION_CLOSED,
        "source": source,
        "actor": _event_actor(event),
        "requires_approval": False,
        "approved_by": None,
        "payload": payload,
    }


def _store_event_id(event: Event) -> str:
    if event.event_id:
        return f"{event.event_id}:store"
    return f"cashier-{event.seq}:store"


def _event_store_id(event: Event, *, fallback: str) -> str:
    return event.store_id or fallback


def _event_actor(event: Event) -> dict[str, str]:
    raw = event.actor
    if isinstance(raw, dict):
        kind = raw.get("kind")
        actor_id = raw.get("id")
        if isinstance(kind, str) and isinstance(actor_id, str):
            return {"kind": kind, "id": actor_id}
    return {"kind": "attendant", "id": "unknown"}


__all__ = [
    "STORE_EVENT_TYPE_TRANSACTION_CLOSED",
    "STORE_SCHEMA_VERSION",
    "project_store_events",
]
