"""Tests for the end-of-shift safety report."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from lemonade_cashier.safety.bags import (
    DenominationCount,
    Manifest,
    handoff_bag,
    receive_bag,
    seal_bag,
)
from lemonade_cashier.safety.cit import open_till, record_drop
from lemonade_cashier.safety.report import build, save

T0 = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)


def test_empty_report_shape(event_log):
    report = build(event_log, now=T0)
    state = report.state
    assert state["schema_version"] == 1
    assert state["log_verified"] is True
    assert state["till"]["cash_on_hand"] == "0.00"
    assert state["bags"] == {}
    assert state["totals"] == {
        "transactions": 0,
        "voids": 0,
        "bag_discrepancies": 0,
        "pin_failures": 0,
    }


def test_report_with_activity(event_log):
    # One open, one cart.add, one drop, one sealed bag.
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
    open_till(event_log, "alice", Decimal("100.00"))
    record_drop(event_log, "alice", Decimal("25.00"))
    manifest = Manifest(entries=(DenominationCount(Decimal("100.00"), 1),))
    seal_event = seal_bag(event_log, "alice", manifest)
    bag_id = seal_event.payload["bag_id"]
    handoff_bag(event_log, bag_id, attendant_id="alice", carrier_id="bob")
    receive_bag(event_log, bag_id, carrier_id="bob", counted_total=Decimal("100.00"))

    report = build(event_log, now=T0)
    state = report.state
    assert state["totals"]["transactions"] == 1
    assert state["totals"]["bag_discrepancies"] == 0
    assert "alice" in state["attendants"]
    assert state["till"]["drops_count"] == 1
    assert bag_id in state["bags"]


def test_report_text_renders(event_log):
    event_log.append("transaction.open", {"attendant": "alice", "tax_rate": "0.15"})
    text = build(event_log, now=T0).to_text()
    assert "LEMONADE CASHIER" in text
    assert "TILL" in text
    assert "ATTENDANTS" in text


def test_report_save(event_log, tmp_path: Path):
    report = build(event_log, now=T0)
    path = save(report, tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("{")
