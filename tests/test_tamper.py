"""Tests for the tamper detectors."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lemonade_cashier.safety.tamper import (
    CLOCK_SKEW_TOLERANCE,
    LONG_QUIET_TOLERANCE,
    emit,
    scan,
)


T0 = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)


def test_clean_log_has_no_findings(event_log):
    event_log.append("transaction.open", {"attendant": "alice"}, ts=T0.isoformat(timespec="seconds"))
    event_log.append("transaction.close", {}, ts=(T0 + timedelta(minutes=1)).isoformat(timespec="seconds"))
    findings = scan(event_log, now=T0 + timedelta(minutes=2))
    assert findings == []


def test_clock_skew_future_flagged(event_log):
    # Event is timestamped 1 hour in the future.
    future = T0 + timedelta(hours=1)
    event_log.append(
        "transaction.open", {"attendant": "alice"}, ts=future.isoformat(timespec="seconds")
    )
    findings = scan(event_log, now=T0)
    assert any(f.kind == "clock_skew_future" for f in findings)


def test_long_quiet_period_flagged(event_log):
    event_log.append(
        "transaction.open", {"attendant": "alice"}, ts=T0.isoformat(timespec="seconds")
    )
    # Three hours later, we still haven't seen anything.
    findings = scan(event_log, now=T0 + LONG_QUIET_TOLERANCE + timedelta(seconds=1))
    assert any(f.kind == "long_quiet_period" for f in findings)


def test_open_close_imbalance_flagged(event_log):
    # Four opens, one close → 3 abandoned transactions.
    for i in range(4):
        event_log.append(
            "transaction.open", {"attendant": "alice"},
            ts=(T0 + timedelta(minutes=i)).isoformat(timespec="seconds"),
        )
    event_log.append(
        "transaction.close", {},
        ts=(T0 + timedelta(minutes=5)).isoformat(timespec="seconds"),
    )
    findings = scan(event_log, now=T0 + timedelta(minutes=6))
    assert any(f.kind == "open_close_imbalance" for f in findings)


def test_emit_writes_event(event_log):
    findings = scan(event_log, now=T0)
    # Manually craft a finding to emit.
    from lemonade_cashier.safety.tamper import TamperFinding
    f = TamperFinding(
        kind="manual_test",
        severity="info",
        message="hello",
        detail={"k": "v"},
    )
    emit(event_log, f, now=T0)
    events = event_log.read_all()
    assert any(e.type == "safety.tamper.suspected" for e in events)
