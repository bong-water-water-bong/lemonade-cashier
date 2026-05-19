"""Replay: pure-function reconstruction of state from events.

``replay(events)`` walks an iterable of :class:`Event` objects and
applies each one to a fresh :class:`ReplayState`. The result is byte-
identical to the in-memory state of the live cashier at the moment
those events were written.

Event types understood:

* ``transaction.open``    — open a new transaction.
* ``cart.add``            — add a cart line.
* ``cart.remove_last``    — remove the most recently added line.
* ``cart.remove_sku``     — remove a named SKU.
* ``cart.set_quantity``   — set quantity of a SKU.
* ``cart.clear``          — clear the cart (start of a separate order).
* ``transaction.tender``  — record cash tendered + change due.
* ``transaction.close``   — close the transaction (final receipt).
* ``cit.*``               — passed through verbatim into ``state.cit``.

Unknown event types are accumulated under ``state.unknown_events`` so
the replay is lossless even when this module trails the producer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ..core.cart import Actor, Cart, CartLine, Source
from ..core.money import money_str, to_money
from ..core.totals import compute_totals
from .eventlog import Event, EventLog

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass
class ReplayState:
    schema_version: int = 1
    opened_at: str | None = None
    closed_at: str | None = None
    cart: Cart = field(default_factory=Cart)
    tax_rate: Decimal = field(default_factory=lambda: to_money("0.15"))
    tender: Decimal | None = None
    change: Decimal | None = None
    cit_events: list[dict[str, object]] = field(default_factory=list)
    unknown_events: list[dict[str, object]] = field(default_factory=list)
    agent_history: list[dict[str, object]] = field(default_factory=list)

    def to_state(self) -> dict[str, object]:
        totals = compute_totals(self.cart, self.tax_rate)
        state: dict[str, object] = {
            "schema_version": self.schema_version,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "items": [line.to_state() for line in self.cart.lines],
            **totals.to_state(),
        }
        if self.tender is not None:
            state["tender"] = money_str(self.tender)
        if self.change is not None:
            state["change"] = money_str(self.change)
        if self.cit_events:
            state["cit"] = list(self.cit_events)
        # Aggregate bag snapshots from the cit.bag.* subset. Lives next
        # to `cit` so consumers can render in-flight bags without
        # walking the event list themselves.
        if any(str(e.get("type", "")).startswith("cit.bag.") for e in self.cit_events):
            from ..safety.bags import bags_from_events
            from .eventlog import Event

            synthetic = [
                Event(
                    seq=int(cast("int | str", e["seq"])),
                    ts=str(e.get("ts", "")),
                    type=str(e["type"]),
                    payload=cast("dict[str, object]", e["payload"]),
                    prev="",
                    hash="",
                )
                for e in self.cit_events
            ]
            state["bags"] = {
                bag_id: snap.to_state() for bag_id, snap in bags_from_events(synthetic).items()
            }
        if self.unknown_events:
            state["unknown_events"] = list(self.unknown_events)
        if self.agent_history:
            state["agent_history"] = list(self.agent_history)
        return state


def replay(events: Iterable[Event]) -> ReplayState:
    """Apply ``events`` in order to a fresh :class:`ReplayState`."""

    state = ReplayState()
    for event in events:
        _apply(state, event)
    return state


def replay_log(path: Path | str) -> ReplayState:
    """Convenience wrapper that loads from a file path."""

    log = EventLog(path)
    log.verify()
    return replay(log.iter_events())


def _apply(state: ReplayState, event: Event) -> None:
    handler = _HANDLERS.get(event.type)
    if handler is None:
        if event.type == "agent.proposal":
            # Agent proposals are first-class: surfaced into a
            # dedicated state.agent_history list so a UI can render
            # "what the model proposed vs. what the supervisor did"
            # without depending on agents.proposals.
            state.agent_history.append(
                {
                    "seq": event.seq,
                    "ts": event.ts,
                    "payload": event.payload,
                }
            )
            return
        if event.type.startswith("cit."):
            state.cit_events.append(
                {
                    "seq": event.seq,
                    "ts": event.ts,
                    "type": event.type,
                    "payload": event.payload,
                }
            )
            return
        state.unknown_events.append(
            {"seq": event.seq, "type": event.type, "payload": event.payload}
        )
        return
    # A malformed event payload (missing required field, wrong type)
    # would otherwise crash the entire replay. Capture it and keep
    # going: the rest of the log is still useful, and `state.unknown_events`
    # is the audit-visible signal that something is off.
    try:
        handler(state, event)
    except (KeyError, TypeError, ValueError) as exc:
        state.unknown_events.append(
            {
                "seq": event.seq,
                "type": event.type,
                "payload": event.payload,
                "replay_error": f"{type(exc).__name__}: {exc}",
            }
        )


def _on_open(state: ReplayState, event: Event) -> None:
    state.opened_at = event.ts
    rate = event.payload.get("tax_rate")
    if rate is not None:
        state.tax_rate = to_money(rate)


def _on_close(state: ReplayState, event: Event) -> None:
    state.closed_at = event.ts


def _on_cart_add(state: ReplayState, event: Event) -> None:
    payload = event.payload
    line = CartLine(
        sku=str(payload["sku"]),
        name=str(payload["name"]),
        unit_price=to_money(payload["unit_price"]),
        taxable=bool(payload["taxable"]),
        quantity=int(cast("int | str", payload.get("quantity", 1))),
        actor=cast("Actor", payload.get("actor", "attendant")),
        source=cast("Source", payload.get("source", "typed")),
        confidence=float(cast("int | float | str", payload.get("confidence", 1.0))),
    )
    state.cart.add(line)


def _on_remove_last(state: ReplayState, _event: Event) -> None:
    state.cart.remove_last()


def _on_remove_sku(state: ReplayState, event: Event) -> None:
    state.cart.remove_sku(str(event.payload["sku"]))


def _on_set_quantity(state: ReplayState, event: Event) -> None:
    state.cart.set_quantity(
        str(event.payload["sku"]),
        int(cast("int | str", event.payload["quantity"])),
    )


def _on_clear(state: ReplayState, _event: Event) -> None:
    state.cart.clear()


def _on_tender(state: ReplayState, event: Event) -> None:
    state.tender = to_money(event.payload["tender"])
    if "change" in event.payload:
        state.change = to_money(event.payload["change"])


_HANDLERS = {
    "transaction.open": _on_open,
    "transaction.close": _on_close,
    "transaction.tender": _on_tender,
    "cart.add": _on_cart_add,
    "cart.remove_last": _on_remove_last,
    "cart.remove_sku": _on_remove_sku,
    "cart.set_quantity": _on_set_quantity,
    "cart.clear": _on_clear,
}


def main() -> None:  # pragma: no cover — CLI helper
    """``python -m lemonade_cashier.audit.replay path/to/log.jsonl``."""

    import sys

    if len(sys.argv) < 2:
        print("usage: python -m lemonade_cashier.audit.replay LOG.jsonl")
        raise SystemExit(2)
    state = replay_log(sys.argv[1])
    print(json.dumps(state.to_state(), indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["ReplayState", "replay", "replay_log"]
