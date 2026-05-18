"""Tests for the append-only hash-chained event log."""

from __future__ import annotations

import json

import pytest

from lemonade_cashier.audit.eventlog import GENESIS_PREV, EventLog, EventLogError


def test_append_and_read(event_log):
    a = event_log.append("cart.add", {"sku": "APL001"})
    b = event_log.append("cart.add", {"sku": "MLK001"})
    events = event_log.read_all()
    assert [e.seq for e in events] == [1, 2]
    assert events[0].prev == GENESIS_PREV
    assert events[1].prev == a.hash
    assert events[1].seq == 2
    assert b.hash == events[1].hash


def test_verify_passes_on_clean_log(event_log):
    event_log.append("cart.add", {"sku": "APL001"})
    event_log.append("cart.add", {"sku": "MLK001"})
    event_log.verify()  # no raise


def test_verify_detects_tamper(tmp_path):
    log_path = tmp_path / "events.jsonl"
    log = EventLog(log_path)
    log.append("cart.add", {"sku": "APL001"})
    log.append("cart.add", {"sku": "MLK001"})

    # Tamper: rewrite the first event's payload but leave its hash intact.
    lines = log_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["payload"] = {"sku": "EVIL"}
    lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    fresh = EventLog(log_path)
    with pytest.raises(EventLogError):
        fresh.verify()


def test_resume_after_reopen(tmp_path):
    log_path = tmp_path / "events.jsonl"
    log = EventLog(log_path)
    log.append("cart.add", {"sku": "APL001"})

    fresh = EventLog(log_path)
    fresh.append("cart.add", {"sku": "MLK001"})

    events = fresh.read_all()
    assert [e.seq for e in events] == [1, 2]
    assert events[1].prev == events[0].hash
