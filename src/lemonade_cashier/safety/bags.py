"""Cash-in-Transit bag lifecycle.

A *bag* is a sealed, tamper-evident container that holds cash drops from
a till and travels through a custody chain to a counting authority
(bank, processor, smart safe). The cashier never opens it; only the
counting authority does.

The lifecycle is a strict state machine:

::

    sealed ──► handoff ──► received ──► reconciled
                                    └─► discrepancy

Each transition emits one event into the same hash-chained JSONL as
the cart and till events (:mod:`audit.eventlog`). Each event names the
``bag_id`` so :func:`bags_from_events` can reconstruct the full chain
of custody from the log alone.

Design notes (see ``~/.claude/projects/-home-bcloud/memory/ref-cit-cashtech.md``):

* **Two-party verification** at handoff: the cashier ``attendant_id``
  who sealed the bag *and* the ``carrier_id`` receiving it both appear
  in ``cit.bag.handoff``. A handoff with the same ID on both sides is
  rejected — a carrier cannot also be the sealing attendant.
* **Discrepancies are events, not errors.** A carrier short-count
  produces ``cit.bag.discrepancy`` with the signed ``delta`` (negative
  = short, positive = over) rather than raising. The audit layer
  surfaces it so reconciliation can be human-driven.
* **No state inside the module.** Every helper reads the event log to
  decide if a transition is legal. The hash chain is the single source
  of truth; in-memory state would let two cashier processes disagree.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from ..audit.eventlog import Event, EventLog
from ..core.money import ZERO, money_str, to_money

# bag_id / carrier_id / seal_id are persisted into the JSONL event log
# and rendered into receipt text. We restrict the character set to keep
# the log greppable, prevent newline-injection into adjacent JSON
# records, and rule out control / shell characters in receipt output.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


def _validate_identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise BagError(f"{field_name} must be a string; got {type(value).__name__}")
    cleaned = value.strip()
    if not _ID_PATTERN.fullmatch(cleaned):
        raise BagError(f"{field_name} must match {_ID_PATTERN.pattern}; got {value!r}")
    return cleaned


# Strict state machine. The keys are the *current* status; the values
# are the set of statuses the bag is allowed to transition into.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "absent": frozenset({"sealed"}),
    "sealed": frozenset({"handoff"}),
    "handoff": frozenset({"received"}),
    "received": frozenset({"reconciled", "discrepancy"}),
    "reconciled": frozenset(),  # terminal
    "discrepancy": frozenset(),  # terminal — requires human reconciliation
}

BagStatus = Literal["absent", "sealed", "handoff", "received", "reconciled", "discrepancy"]


class BagError(RuntimeError):
    """Raised when a bag transition violates the state machine."""


@dataclass(frozen=True)
class DenominationCount:
    """One entry in a bag manifest: a denomination and its count."""

    denomination: Decimal
    count: int

    def total(self) -> Decimal:
        return self.denomination * Decimal(self.count)

    def to_payload(self) -> dict[str, object]:
        return {"denomination": money_str(self.denomination), "count": self.count}


@dataclass(frozen=True)
class Manifest:
    """The denomination-by-denomination accounting of a sealed bag.

    The manifest is what the sealing attendant *says* is in the bag.
    The counting authority's tally is what's *actually* in the bag.
    Reconciliation compares the two.
    """

    entries: tuple[DenominationCount, ...]

    @property
    def total(self) -> Decimal:
        result = ZERO
        for entry in self.entries:
            result += entry.total()
        return result

    def to_payload(self) -> list[dict[str, object]]:
        return [entry.to_payload() for entry in self.entries]

    @classmethod
    def from_payload(cls, payload: object) -> Manifest:
        if not isinstance(payload, list):
            raise BagError(f"manifest payload must be a list, got {type(payload).__name__}")
        entries: list[DenominationCount] = []
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                raise BagError(f"manifest entry {index} must be a dict")
            try:
                entries.append(
                    DenominationCount(
                        denomination=to_money(item["denomination"]),
                        count=int(item["count"]),
                    )
                )
            except KeyError as exc:
                raise BagError(f"manifest entry {index} missing required key {exc}") from exc
            except (TypeError, ValueError) as exc:
                raise BagError(f"manifest entry {index} has invalid value: {exc}") from exc
        return cls(entries=tuple(entries))


@dataclass(frozen=True)
class BagSnapshot:
    """The current status of one bag, reconstructed from events.

    ``chain_of_custody`` is the ordered list of event ``seq`` numbers
    that touched this bag — useful for surfacing the audit trail of a
    single bag without scanning the whole log.
    """

    bag_id: str
    status: BagStatus
    seal_id: str | None = None
    manifest_total: Decimal | None = None
    counted_total: Decimal | None = None
    delta: Decimal | None = None
    sealed_by: str | None = None
    handed_off_to: str | None = None
    chain_of_custody: tuple[int, ...] = ()

    def to_state(self) -> dict[str, object]:
        state: dict[str, object] = {
            "bag_id": self.bag_id,
            "status": self.status,
            "chain_of_custody": list(self.chain_of_custody),
        }
        if self.seal_id is not None:
            state["seal_id"] = self.seal_id
        if self.manifest_total is not None:
            state["manifest_total"] = money_str(self.manifest_total)
        if self.counted_total is not None:
            state["counted_total"] = money_str(self.counted_total)
        if self.delta is not None:
            state["delta"] = money_str(self.delta)
        if self.sealed_by is not None:
            state["sealed_by"] = self.sealed_by
        if self.handed_off_to is not None:
            state["handed_off_to"] = self.handed_off_to
        return state


# --------------------------------------------------------------------------
# Transition helpers
# --------------------------------------------------------------------------


def _canonicalize_actor_id(value: object, *, field_name: str) -> str:
    """Strip whitespace + casefold an actor id, rejecting empty values.

    Two-party verification compares ``attendant_id`` to ``carrier_id``;
    if the CLI parser case-folds one side and not the other (which it
    does — see ``agents/parser.py``), a hostile or sloppy operator can
    bypass the rule simply by typing the carrier_id in a different case
    than the attendant_id is stored in. We canonicalize both sides at
    the policy boundary, in this module, so the rule holds regardless
    of how the surface layer normalizes input.
    """

    if not isinstance(value, str):
        raise BagError(f"{field_name} must be a string; got {type(value).__name__}")
    cleaned = value.strip().casefold()
    if not cleaned:
        raise BagError(f"{field_name} must be a non-empty, non-whitespace string")
    return cleaned


def seal_bag(
    log: EventLog,
    attendant_id: str,
    manifest: Manifest,
    *,
    bag_id: str | None = None,
    seal_id: str | None = None,
) -> Event:
    """Seal a new bag with ``manifest``. Returns the resulting event.

    ``bag_id`` and ``seal_id`` default to a uuid4 each if not supplied.
    The bag must not already exist — sealing an existing bag_id raises
    :class:`BagError`.
    """

    attendant_canon = _canonicalize_actor_id(attendant_id, field_name="attendant_id")
    if manifest.total <= ZERO:
        raise BagError(f"manifest total must be > 0; got ${money_str(manifest.total)}")
    final_bag_id = bag_id or f"bag-{uuid.uuid4().hex[:12]}"
    final_seal_id = seal_id or f"seal-{uuid.uuid4().hex[:12]}"
    final_bag_id = _validate_identifier(final_bag_id, field_name="bag_id")
    final_seal_id = _validate_identifier(final_seal_id, field_name="seal_id")

    current = _current_status(log, final_bag_id)
    _require_transition(current, "sealed", final_bag_id)

    return log.append(
        "cit.bag.sealed",
        {
            "bag_id": final_bag_id,
            "seal_id": final_seal_id,
            "attendant": attendant_canon,
            "manifest_total": money_str(manifest.total),
            "manifest": manifest.to_payload(),
        },
    )


def handoff_bag(
    log: EventLog,
    bag_id: str,
    *,
    attendant_id: str,
    carrier_id: str,
) -> Event:
    """Cashier hands a sealed bag to a carrier (two-party verification).

    Both ids are stripped + casefolded before the equality check so
    capitalization tricks ("Alice" vs "alice") cannot defeat the
    two-party rule. The canonical form is what's persisted to the
    event log.
    """

    attendant_canon = _canonicalize_actor_id(attendant_id, field_name="attendant_id")
    carrier_canon = _canonicalize_actor_id(carrier_id, field_name="carrier_id")
    bag_id = _validate_identifier(bag_id, field_name="bag_id")
    if attendant_canon == carrier_canon:
        raise BagError(
            "carrier_id must differ from attendant_id (two-party rule); "
            f"both canonicalized to {attendant_canon!r}"
        )
    current = _current_status(log, bag_id)
    _require_transition(current, "handoff", bag_id)
    return log.append(
        "cit.bag.handoff",
        {
            "bag_id": bag_id,
            "attendant": attendant_canon,
            "carrier": carrier_canon,
        },
    )


def receive_bag(
    log: EventLog,
    bag_id: str,
    *,
    carrier_id: str,
    counted_total: Decimal,
    tolerance: Decimal = Decimal("0.00"),
) -> Event:
    """Counting authority records the actual counted total for ``bag_id``.

    This is **not** the terminal event: if ``counted_total`` matches the
    manifest within ``tolerance`` the caller should immediately follow
    with :func:`reconcile_bag`; otherwise with :func:`flag_discrepancy`.
    :func:`receive_bag` exists as its own event so the chain of custody
    records the moment the bag entered the counting authority, even if
    the discrepancy resolution takes hours.
    """

    carrier_canon = _canonicalize_actor_id(carrier_id, field_name="carrier_id")
    bag_id = _validate_identifier(bag_id, field_name="bag_id")
    counted = to_money(counted_total)
    if counted < ZERO:
        raise BagError(f"counted_total must be >= 0; got ${money_str(counted)}")
    current = _current_status(log, bag_id)
    _require_transition(current, "received", bag_id)
    return log.append(
        "cit.bag.received",
        {
            "bag_id": bag_id,
            "carrier": carrier_canon,
            "counted_total": money_str(counted),
            "tolerance": money_str(to_money(tolerance)),
        },
    )


def reconcile_bag(log: EventLog, bag_id: str) -> Event:
    """Mark ``bag_id`` reconciled. Caller must verify counted == manifest first."""

    bag_id = _validate_identifier(bag_id, field_name="bag_id")
    current = _current_status(log, bag_id)
    _require_transition(current, "reconciled", bag_id)
    return log.append(
        "cit.bag.reconciled",
        {"bag_id": bag_id},
    )


def flag_discrepancy(log: EventLog, bag_id: str, *, delta: Decimal) -> Event:
    """Record a counted-vs-manifest discrepancy.

    ``delta = counted - manifest_total``. Negative is short; positive is
    over. Both directions are recorded as ``cit.bag.discrepancy`` so the
    audit layer can flag them; this module never decides what to do
    about the discrepancy (that's a human decision).
    """

    bag_id = _validate_identifier(bag_id, field_name="bag_id")
    current = _current_status(log, bag_id)
    _require_transition(current, "discrepancy", bag_id)
    return log.append(
        "cit.bag.discrepancy",
        {
            "bag_id": bag_id,
            "delta": money_str(to_money(delta)),
        },
    )


# --------------------------------------------------------------------------
# Reconstruction
# --------------------------------------------------------------------------


def bags_from_events(events: list[Event]) -> dict[str, BagSnapshot]:
    """Reconstruct every bag's snapshot from the events list.

    The result is keyed by ``bag_id``. Bags in any state are included,
    so a UI can render in-flight bags as well as terminal ones.
    """

    return _bags_from_events_impl(events)


def _current_status(log: EventLog, bag_id: str) -> BagStatus:
    snapshots = _bags_from_events_impl(log.read_all())
    snapshot = snapshots.get(bag_id)
    return snapshot.status if snapshot else "absent"


def _require_transition(current: BagStatus, target: BagStatus, bag_id: str) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise BagError(f"bag {bag_id!r}: illegal transition {current!r} -> {target!r}")


def _bags_from_events_impl(events: list[Event]) -> dict[str, BagSnapshot]:
    bags: dict[str, _MutableBag] = {}
    for event in events:
        if not event.type.startswith("cit.bag."):
            continue
        bag_id = event.payload.get("bag_id")
        if not isinstance(bag_id, str):
            continue
        bag = bags.setdefault(bag_id, _MutableBag(bag_id=bag_id))
        bag.chain_of_custody.append(event.seq)

        if event.type == "cit.bag.sealed":
            bag.status = "sealed"
            bag.seal_id = str(event.payload.get("seal_id", ""))
            bag.sealed_by = str(event.payload.get("attendant", ""))
            mt = event.payload.get("manifest_total")
            if isinstance(mt, (str, int)):
                bag.manifest_total = to_money(mt)
        elif event.type == "cit.bag.handoff":
            bag.status = "handoff"
            bag.handed_off_to = str(event.payload.get("carrier", ""))
        elif event.type == "cit.bag.received":
            bag.status = "received"
            ct = event.payload.get("counted_total")
            if isinstance(ct, (str, int)):
                bag.counted_total = to_money(ct)
                if bag.manifest_total is not None:
                    bag.delta = bag.counted_total - bag.manifest_total
        elif event.type == "cit.bag.reconciled":
            bag.status = "reconciled"
        elif event.type == "cit.bag.discrepancy":
            bag.status = "discrepancy"
            d = event.payload.get("delta")
            if isinstance(d, (str, int)):
                bag.delta = to_money(d)

    return {bid: b.freeze() for bid, b in bags.items()}


@dataclass
class _MutableBag:
    bag_id: str
    status: BagStatus = "absent"
    seal_id: str | None = None
    manifest_total: Decimal | None = None
    counted_total: Decimal | None = None
    delta: Decimal | None = None
    sealed_by: str | None = None
    handed_off_to: str | None = None
    chain_of_custody: list[int] = field(default_factory=list)

    def freeze(self) -> BagSnapshot:
        return BagSnapshot(
            bag_id=self.bag_id,
            status=self.status,
            seal_id=self.seal_id,
            manifest_total=self.manifest_total,
            counted_total=self.counted_total,
            delta=self.delta,
            sealed_by=self.sealed_by,
            handed_off_to=self.handed_off_to,
            chain_of_custody=tuple(self.chain_of_custody),
        )


__all__ = [
    "BagError",
    "BagSnapshot",
    "BagStatus",
    "DenominationCount",
    "Manifest",
    "bags_from_events",
    "flag_discrepancy",
    "handoff_bag",
    "receive_bag",
    "reconcile_bag",
    "seal_bag",
]
