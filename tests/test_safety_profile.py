"""Tests for the per-attendant safety profile projection."""

from __future__ import annotations

from lemonade_cashier.safety.profile import profile_for, profiles_from_events


def test_empty_log_no_profiles(event_log):
    assert profiles_from_events(event_log.read_all()) == {}


def test_transaction_open_increments(event_log):
    event_log.append("transaction.open", {"attendant": "alice", "tax_rate": "0.15"})
    event_log.append("transaction.open", {"attendant": "alice", "tax_rate": "0.15"})
    p = profile_for(event_log.read_all(), "alice")
    assert p.total_transactions == 2
    assert p.voids == 0


def test_low_conf_add_counted(event_log):
    event_log.append("transaction.open", {"attendant": "alice", "tax_rate": "0.15"})
    event_log.append(
        "cart.add",
        {
            "sku": "X",
            "name": "x",
            "unit_price": "1.00",
            "taxable": True,
            "quantity": 1,
            "actor": "attendant",
            "source": "fuzzy",
            "confidence": 0.6,
        },
    )
    p = profile_for(event_log.read_all(), "alice")
    assert p.low_conf_adds == 1
    assert p.model_proposed_adds == 0


def test_model_proposed_counted(event_log):
    event_log.append("transaction.open", {"attendant": "alice", "tax_rate": "0.15"})
    event_log.append(
        "cart.add",
        {
            "sku": "X",
            "name": "x",
            "unit_price": "1.00",
            "taxable": True,
            "quantity": 1,
            "actor": "agent_auto",
            "source": "model_proposed",
            "confidence": 0.95,
        },
    )
    p = profile_for(event_log.read_all(), "alice")
    assert p.model_proposed_adds == 1


def test_attendant_case_canonicalized(event_log):
    event_log.append("transaction.open", {"attendant": "Alice", "tax_rate": "0.15"})
    event_log.append("transaction.open", {"attendant": "alice", "tax_rate": "0.15"})
    profiles = profiles_from_events(event_log.read_all())
    # Both 'Alice' and 'alice' collapse into one entry.
    assert set(profiles.keys()) == {"alice"}
    assert profiles["alice"].total_transactions == 2


def test_void_attribution_to_most_active_attendant(event_log):
    event_log.append("transaction.open", {"attendant": "alice", "tax_rate": "0.15"})
    event_log.append(
        "cart.add",
        {
            "sku": "X",
            "name": "x",
            "unit_price": "1.00",
            "taxable": True,
            "quantity": 1,
            "actor": "attendant",
            "source": "typed",
            "confidence": 1.0,
        },
    )
    event_log.append("cart.remove_last", {"sku": "X"})
    p = profile_for(event_log.read_all(), "alice")
    assert p.voids == 1


def test_pin_failures_counted(event_log):
    event_log.append("safety.pin.failed", {"actor_id": "alice"})
    event_log.append("safety.pin.failed", {"actor_id": "alice"})
    p = profile_for(event_log.read_all(), "alice")
    assert p.pin_failures == 2


def test_void_rate_zero_without_transactions(event_log):
    p = profile_for(event_log.read_all(), "alice")
    assert p.void_rate == 0.0
    assert p.discrepancy_rate == 0.0
