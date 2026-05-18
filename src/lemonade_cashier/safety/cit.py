"""Cash-in-transit (CIT): till opens, closes, drops, pickups.

CIT events live in the same JSONL as cart events, prefixed
``cit.*``. The hash chain therefore covers till activity too — a drop
that "didn't happen" cannot be silently re-inserted later.

A drop above ``two_person_threshold`` requires a witness sign-off
recorded as ``cit.drop.witnessed`` (else ``cit.drop`` alone). The
:func:`record_drop` helper enforces the gate by returning the right
event type.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..audit.eventlog import Event, EventLog
from ..core.money import money_str, to_money

DEFAULT_TWO_PERSON_THRESHOLD = Decimal("200.00")


@dataclass(frozen=True)
class TillState:
    cash_on_hand: Decimal
    drops_count: int
    pickups_count: int

    def to_state(self) -> dict[str, object]:
        return {
            "cash_on_hand": money_str(self.cash_on_hand),
            "drops_count": self.drops_count,
            "pickups_count": self.pickups_count,
        }


class TillError(RuntimeError):
    """Raised when a CIT operation violates a precondition."""


def open_till(
    log: EventLog, attendant_id: str, starting_count: Decimal
) -> Event:
    return log.append(
        "cit.till.open",
        {
            "attendant": attendant_id,
            "starting_count": money_str(starting_count),
        },
    )


def close_till(
    log: EventLog, attendant_id: str, ending_count: Decimal
) -> Event:
    return log.append(
        "cit.till.close",
        {
            "attendant": attendant_id,
            "ending_count": money_str(ending_count),
        },
    )


def record_drop(
    log: EventLog,
    attendant_id: str,
    amount: Decimal,
    *,
    witness_id: str | None = None,
    two_person_threshold: Decimal = DEFAULT_TWO_PERSON_THRESHOLD,
) -> Event:
    """Record a cash drop from the till to the safe.

    If ``amount >= two_person_threshold`` and no ``witness_id`` is
    provided, :class:`TillError` is raised — the cashier must surface
    this to the supervisor and re-attempt with a witness.

    ``amount`` must be strictly positive. A negative drop would otherwise
    add cash to the till via the subtraction in
    :func:`till_state_from_events` — bypassing both the pickup audit
    trail and the witness rule for what is effectively a pickup.
    """

    amt = to_money(amount)
    if amt <= to_money("0.00"):
        raise TillError(
            f"drop amount must be > 0; got ${money_str(amt)}. "
            "Use record_pickup() to put money into the till."
        )
    if amt >= to_money(two_person_threshold) and not witness_id:
        raise TillError(
            f"drop of ${money_str(amt)} >= ${money_str(to_money(two_person_threshold))}"
            " requires a witness"
        )

    event_type = "cit.drop.witnessed" if witness_id else "cit.drop"
    payload: dict[str, object] = {
        "attendant": attendant_id,
        "amount": money_str(amt),
    }
    if witness_id:
        payload["witness"] = witness_id
    return log.append(event_type, payload)


def record_pickup(
    log: EventLog, attendant_id: str, amount: Decimal
) -> Event:
    amt = to_money(amount)
    if amt <= to_money("0.00"):
        raise TillError(
            f"pickup amount must be > 0; got ${money_str(amt)}. "
            "Use record_drop() to remove money from the till."
        )
    return log.append(
        "cit.pickup",
        {
            "attendant": attendant_id,
            "amount": money_str(amt),
        },
    )


def till_state_from_events(events: list[Event]) -> TillState:
    """Reconstruct the till's current cash + counts from CIT events."""

    cash = to_money("0.00")
    drops = 0
    pickups = 0
    for event in events:
        if event.type == "cit.till.open":
            cash = to_money(event.payload["starting_count"])  # type: ignore[arg-type]
        elif event.type == "cit.till.close":
            cash = to_money("0.00")
        elif event.type in ("cit.drop", "cit.drop.witnessed"):
            cash -= to_money(event.payload["amount"])  # type: ignore[arg-type]
            drops += 1
        elif event.type == "cit.pickup":
            cash += to_money(event.payload["amount"])  # type: ignore[arg-type]
            pickups += 1
    return TillState(cash_on_hand=cash, drops_count=drops, pickups_count=pickups)


__all__ = [
    "DEFAULT_TWO_PERSON_THRESHOLD",
    "TillError",
    "TillState",
    "close_till",
    "open_till",
    "record_drop",
    "record_pickup",
    "till_state_from_events",
]
