"""Tests for the CIT bag lifecycle.

The bag module is a strict state machine + an event-sourced
reconstructor. Both halves need their own tests, because a bug in
either can corrupt the chain of custody without the hash chain
noticing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from lemonade_cashier.audit.eventlog import EventLog
from lemonade_cashier.audit.replay import replay
from lemonade_cashier.safety.bags import (
    BagError,
    DenominationCount,
    Manifest,
    bags_from_events,
    flag_discrepancy,
    handoff_bag,
    receive_bag,
    reconcile_bag,
    seal_bag,
)


def _full_manifest(total: str = "500.00") -> Manifest:
    """Build a manifest whose total equals the given string amount."""

    amt = Decimal(total)
    hundreds = int(amt // Decimal("100.00"))
    cents = int((amt - Decimal(hundreds) * Decimal("100.00")) * Decimal("100"))
    entries: list[DenominationCount] = []
    if hundreds:
        entries.append(DenominationCount(Decimal("100.00"), hundreds))
    if cents:
        entries.append(DenominationCount(Decimal("0.01"), cents))
    return Manifest(entries=tuple(entries))


# --------------------------------------------------------------------------
# Manifest math
# --------------------------------------------------------------------------


def test_manifest_total_is_decimal_exact():
    m = Manifest(
        entries=(
            DenominationCount(Decimal("100.00"), 3),
            DenominationCount(Decimal("20.00"), 5),
            DenominationCount(Decimal("0.01"), 17),
        )
    )
    assert m.total == Decimal("400.17")


def test_manifest_payload_roundtrips():
    m = _full_manifest("250.50")
    restored = Manifest.from_payload(m.to_payload())
    assert restored.total == m.total


def test_manifest_from_payload_robust_against_malformed():
    # Wrong shape entirely.
    with pytest.raises(BagError, match="must be a list"):
        Manifest.from_payload("not a list")
    # Missing key.
    with pytest.raises(BagError, match="missing required key"):
        Manifest.from_payload([{"denomination": "1.00"}])
    # Bad value type.
    with pytest.raises(BagError, match="invalid value"):
        Manifest.from_payload([{"denomination": "x", "count": 1}])


# --------------------------------------------------------------------------
# Seal
# --------------------------------------------------------------------------


def test_seal_rejects_zero_manifest(event_log):
    with pytest.raises(BagError, match="must be > 0"):
        seal_bag(event_log, "alice", Manifest(entries=()))


def test_seal_emits_event_with_manifest(event_log):
    event = seal_bag(event_log, "alice", _full_manifest("300.00"))
    assert event.type == "cit.bag.sealed"
    assert event.payload["manifest_total"] == "300.00"
    assert event.payload["attendant"] == "alice"


def test_seal_rejects_double_seal(event_log):
    event = seal_bag(event_log, "alice", _full_manifest("100.00"))
    bag_id = event.payload["bag_id"]
    with pytest.raises(BagError, match="illegal transition"):
        seal_bag(event_log, "alice", _full_manifest("100.00"), bag_id=bag_id)


# --------------------------------------------------------------------------
# Handoff (two-party)
# --------------------------------------------------------------------------


def test_handoff_requires_distinct_parties(event_log):
    event = seal_bag(event_log, "alice", _full_manifest("100.00"))
    bag_id = event.payload["bag_id"]
    with pytest.raises(BagError, match="two-party"):
        handoff_bag(event_log, bag_id, attendant_id="alice", carrier_id="alice")


def test_handoff_two_party_rule_is_case_insensitive(event_log):
    """A capitalization trick — bag handoff X Alice when the attendant_id
    is 'alice' — must still be rejected. Both sides canonicalize to
    casefold before comparison."""

    event = seal_bag(event_log, "Alice", _full_manifest("100.00"))
    bag_id = event.payload["bag_id"]
    with pytest.raises(BagError, match="two-party"):
        handoff_bag(event_log, bag_id, attendant_id="alice", carrier_id="ALICE")
    with pytest.raises(BagError, match="two-party"):
        handoff_bag(event_log, bag_id, attendant_id="Alice", carrier_id="  alice  ")


def test_handoff_persists_canonical_ids(event_log):
    event = seal_bag(event_log, "  Alice  ", _full_manifest("100.00"))
    bag_id = event.payload["bag_id"]
    handed = handoff_bag(event_log, bag_id, attendant_id="Alice", carrier_id="BoB")
    assert handed.payload["attendant"] == "alice"
    assert handed.payload["carrier"] == "bob"


def test_seal_rejects_empty_attendant(event_log):
    with pytest.raises(BagError, match="non-empty"):
        seal_bag(event_log, "  ", _full_manifest("100.00"))
    with pytest.raises(BagError, match="non-empty"):
        seal_bag(event_log, "", _full_manifest("100.00"))


def test_handoff_rejects_empty_carrier(event_log):
    event = seal_bag(event_log, "alice", _full_manifest("100.00"))
    bag_id = event.payload["bag_id"]
    with pytest.raises(BagError, match="non-empty"):
        handoff_bag(event_log, bag_id, attendant_id="alice", carrier_id="   ")


def test_handoff_requires_sealed_bag(event_log):
    with pytest.raises(BagError, match="illegal transition"):
        handoff_bag(
            event_log, "no-such-bag", attendant_id="alice", carrier_id="bob"
        )


def test_handoff_emits_two_party_event(event_log):
    event = seal_bag(event_log, "alice", _full_manifest("100.00"))
    bag_id = event.payload["bag_id"]
    handed = handoff_bag(event_log, bag_id, attendant_id="alice", carrier_id="bob")
    assert handed.type == "cit.bag.handoff"
    assert handed.payload["attendant"] == "alice"
    assert handed.payload["carrier"] == "bob"


# --------------------------------------------------------------------------
# Receive + reconcile + discrepancy
# --------------------------------------------------------------------------


def _seal_and_handoff(log: EventLog, amount: str = "100.00") -> str:
    seal_event = seal_bag(log, "alice", _full_manifest(amount))
    bag_id = seal_event.payload["bag_id"]
    handoff_bag(log, bag_id, attendant_id="alice", carrier_id="bob")
    return bag_id


def test_receive_then_reconcile_succeeds(event_log):
    bag_id = _seal_and_handoff(event_log, "100.00")
    receive_bag(event_log, bag_id, carrier_id="bob", counted_total=Decimal("100.00"))
    reconcile_bag(event_log, bag_id)

    snapshot = bags_from_events(event_log.read_all())[bag_id]
    assert snapshot.status == "reconciled"
    assert snapshot.counted_total == Decimal("100.0000")
    assert snapshot.delta == Decimal("0.0000")


def test_receive_then_discrepancy(event_log):
    bag_id = _seal_and_handoff(event_log, "100.00")
    # Carrier counts $90 — short by $10.
    receive_bag(event_log, bag_id, carrier_id="bob", counted_total=Decimal("90.00"))
    flag_discrepancy(event_log, bag_id, delta=Decimal("-10.00"))

    snapshot = bags_from_events(event_log.read_all())[bag_id]
    assert snapshot.status == "discrepancy"
    assert snapshot.delta == Decimal("-10.0000")


def test_reconcile_rejected_without_receive(event_log):
    bag_id = _seal_and_handoff(event_log, "100.00")
    with pytest.raises(BagError, match="illegal transition"):
        reconcile_bag(event_log, bag_id)


def test_receive_rejects_negative_count(event_log):
    bag_id = _seal_and_handoff(event_log, "100.00")
    with pytest.raises(BagError, match=">= 0"):
        receive_bag(event_log, bag_id, carrier_id="bob", counted_total=Decimal("-1.00"))


def test_reconciled_is_terminal(event_log):
    bag_id = _seal_and_handoff(event_log, "100.00")
    receive_bag(event_log, bag_id, carrier_id="bob", counted_total=Decimal("100.00"))
    reconcile_bag(event_log, bag_id)
    # Trying to reconcile again — or flag a discrepancy — must fail.
    with pytest.raises(BagError, match="illegal transition"):
        reconcile_bag(event_log, bag_id)
    with pytest.raises(BagError, match="illegal transition"):
        flag_discrepancy(event_log, bag_id, delta=Decimal("0.00"))


# --------------------------------------------------------------------------
# Chain-of-custody reconstruction
# --------------------------------------------------------------------------


def test_chain_of_custody_recorded(event_log):
    bag_id = _seal_and_handoff(event_log, "100.00")
    receive_bag(event_log, bag_id, carrier_id="bob", counted_total=Decimal("100.00"))
    reconcile_bag(event_log, bag_id)

    snapshot = bags_from_events(event_log.read_all())[bag_id]
    # Four events touched this bag, in order.
    assert len(snapshot.chain_of_custody) == 4
    # Sequence numbers are strictly increasing.
    assert list(snapshot.chain_of_custody) == sorted(snapshot.chain_of_custody)


def test_replay_exposes_bags_in_state(event_log):
    """The bag aggregation must surface through audit.replay so a UI
    can render in-flight bags without depending on safety.bags."""

    bag_id = _seal_and_handoff(event_log, "100.00")
    receive_bag(event_log, bag_id, carrier_id="bob", counted_total=Decimal("100.00"))

    state = replay(event_log.read_all()).to_state()
    assert "bags" in state
    bag = state["bags"][bag_id]  # type: ignore[index]
    assert bag["status"] == "received"
    assert bag["sealed_by"] == "alice"
    assert bag["handed_off_to"] == "bob"
    assert bag["counted_total"] == "100.00"
    assert bag["manifest_total"] == "100.00"
    assert bag["delta"] == "0.00"
