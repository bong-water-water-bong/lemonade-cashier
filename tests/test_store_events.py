"""Tests for projecting cashier-native audit events into store.event.v1."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lemonade_cashier.audit.eventlog import EventLog
from lemonade_cashier.audit.replay import replay_log
from lemonade_cashier.audit.store_events import project_store_events


def test_project_closed_transaction_preserves_native_log(event_log: EventLog):
    event_log.append(
        "transaction.open",
        {"tax_rate": "0.15"},
        ts="2026-05-19T18:00:00+00:00",
        actor={"kind": "attendant", "id": "alice"},
    )
    event_log.append(
        "cart.add",
        {
            "sku": "APL001",
            "name": "apple",
            "unit_price": "1.00",
            "taxable": True,
            "quantity": 2,
        },
        ts="2026-05-19T18:01:00+00:00",
        actor={"kind": "attendant", "id": "alice"},
    )
    event_log.append(
        "transaction.tender",
        {"tender": "5.00", "total": "2.30", "change": "2.70"},
        ts="2026-05-19T18:02:00+00:00",
        actor={"kind": "attendant", "id": "alice"},
    )
    event_log.append(
        "transaction.close",
        {},
        ts="2026-05-19T18:03:00+00:00",
        actor={"kind": "attendant", "id": "alice"},
    )

    event_log.verify()
    native_state = replay_log(event_log.path).to_state()
    projected = list(project_store_events(event_log.iter_events()))

    assert len(projected) == 1
    store_event = projected[0]
    assert store_event["schema_version"] == "store.event.v1"
    assert store_event["department"] == "cashier"
    assert store_event["type"] == "cashier.transaction.closed"
    assert store_event["actor"] == {"kind": "attendant", "id": "alice"}
    assert store_event["payload"]["original_type"] == "transaction.close"
    assert store_event["payload"]["subtotal"] == native_state["subtotal"]
    assert store_event["payload"]["tax"] == native_state["tax"]
    assert store_event["payload"]["total"] == native_state["total"]
    assert store_event["payload"]["cash_tendered"] == native_state["tender"]
    assert store_event["payload"]["change"] == native_state["change"]

    # Projection is read-only: the source chain still verifies after projecting.
    event_log.verify()


def test_projected_closed_transaction_passes_store_contract(event_log: EventLog):
    store_src = Path(__file__).resolve().parents[2] / "lemonade-store" / "src"
    if not store_src.exists():
        store_src = Path("/home/bcloud/lemonade-store/src")
    if str(store_src) not in sys.path:
        sys.path.insert(0, str(store_src))
    events_module = pytest.importorskip("lemonade_store.events")

    event_log.append(
        "transaction.open",
        {"tax_rate": "0.15"},
        ts="2026-05-19T18:00:00+00:00",
    )
    event_log.append(
        "transaction.close",
        {},
        ts="2026-05-19T18:01:00+00:00",
    )

    projected = next(project_store_events(event_log.iter_events()))
    loaded = events_module.load_event(projected)

    assert loaded.schema_version == "store.event.v1"
    assert loaded.department == "cashier"
    assert loaded.type == "cashier.transaction.closed"
