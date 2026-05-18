"""Tests for cash-in-transit (CIT) events and the two-person rule."""

from __future__ import annotations

from decimal import Decimal

import pytest

from lemonade_cashier.safety.cit import (
    DEFAULT_TWO_PERSON_THRESHOLD,
    TillError,
    close_till,
    open_till,
    record_drop,
    record_pickup,
    till_state_from_events,
)


def test_open_till_records_starting_count(event_log):
    open_till(event_log, "alice", Decimal("100.00"))
    state = till_state_from_events(event_log.read_all())
    assert state.cash_on_hand == Decimal("100.0000")


def test_drop_above_threshold_requires_witness(event_log):
    open_till(event_log, "alice", Decimal("500.00"))
    with pytest.raises(TillError):
        record_drop(event_log, "alice", DEFAULT_TWO_PERSON_THRESHOLD)


def test_drop_with_witness_succeeds(event_log):
    open_till(event_log, "alice", Decimal("500.00"))
    event = record_drop(
        event_log, "alice", DEFAULT_TWO_PERSON_THRESHOLD, witness_id="bob"
    )
    assert event.type == "cit.drop.witnessed"
    state = till_state_from_events(event_log.read_all())
    assert state.cash_on_hand == Decimal("300.0000")


def test_pickup_increases_till(event_log):
    open_till(event_log, "alice", Decimal("100.00"))
    record_pickup(event_log, "alice", Decimal("50.00"))
    state = till_state_from_events(event_log.read_all())
    assert state.cash_on_hand == Decimal("150.0000")


def test_close_resets_till_to_zero(event_log):
    open_till(event_log, "alice", Decimal("100.00"))
    close_till(event_log, "alice", Decimal("103.27"))
    state = till_state_from_events(event_log.read_all())
    assert state.cash_on_hand == Decimal("0.0000")
