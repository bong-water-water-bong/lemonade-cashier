"""Tamper-suspected detectors over the event log.

The hash chain (:mod:`audit.eventlog`) detects content tampering of
individual events. ``EventLog.verify`` additionally catches:

* hash mismatches,
* prev-hash chain breaks,
* sequence-number gaps,
* non-monotonic timestamps.

This module catches a different class — **subtle integrity signals**
that don't break the chain but suggest something off:

* **Clock skew**: the latest event's ``ts`` is far in the past or far in
  the future relative to ``now``. Could be an operator with a wrong
  clock; could be an attacker replaying old events.
* **Long gap**: a long quiet period followed by activity. Not
  necessarily malicious, but worth flagging if a shift is supposed to
  be continuous.
* **Many opens without closes**: opens out-numbering closes by more
  than one means a transaction is being abandoned mid-cart — worth a
  daily report mention.

Each finding is returned as a :class:`TamperFinding`; the caller
decides whether to write a ``safety.tamper.suspected`` event into the
log or just surface it in the EOS report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from ..audit.eventlog import Event, EventLog


CLOCK_SKEW_TOLERANCE = timedelta(minutes=10)
LONG_QUIET_TOLERANCE = timedelta(hours=2)


@dataclass(frozen=True)
class TamperFinding:
    kind: str
    message: str
    severity: str  # "info" | "warn" | "critical"
    detail: dict[str, object]

    def to_state(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "detail": dict(self.detail),
        }


def scan(
    log: EventLog,
    *,
    now: datetime | None = None,
    clock_skew_tolerance: timedelta = CLOCK_SKEW_TOLERANCE,
    long_quiet_tolerance: timedelta = LONG_QUIET_TOLERANCE,
) -> list[TamperFinding]:
    """Run all tamper detectors over ``log`` and return findings.

    Cheap: O(n) over the events. Safe to run at end-of-shift.
    """

    events = log.read_all()
    now = now or datetime.now(timezone.utc)
    findings: list[TamperFinding] = []
    findings.extend(_clock_skew_findings(events, now=now, tolerance=clock_skew_tolerance))
    findings.extend(_long_quiet_findings(events, now=now, tolerance=long_quiet_tolerance))
    findings.extend(_open_close_balance_findings(events))
    return findings


def emit(log: EventLog, finding: TamperFinding, *, now: datetime | None = None) -> Event:
    """Append a ``safety.tamper.suspected`` event for ``finding``.

    Use this when a caller wants the audit log itself to record the
    suspicion (e.g., the EOS report renderer). Plain ``scan()`` does
    not write to the log.
    """

    now = now or datetime.now(timezone.utc)
    return log.append(
        "safety.tamper.suspected",
        {
            "kind": finding.kind,
            "severity": finding.severity,
            "message": finding.message,
            "detail": dict(finding.detail),
        },
        ts=now.isoformat(timespec="seconds"),
    )


# --------------------------------------------------------------------------
# Detectors
# --------------------------------------------------------------------------


def _clock_skew_findings(
    events: Iterable[Event], *, now: datetime, tolerance: timedelta
) -> list[TamperFinding]:
    findings: list[TamperFinding] = []
    last: datetime | None = None
    for event in events:
        last = _parse_ts(event.ts) or last
    if last is None:
        return findings
    if last > now + tolerance:
        findings.append(
            TamperFinding(
                kind="clock_skew_future",
                severity="warn",
                message=f"latest event ts {last!s} > now {now!s} by more than {tolerance}",
                detail={"last_ts": last.isoformat(), "now": now.isoformat()},
            )
        )
    return findings


def _long_quiet_findings(
    events: Iterable[Event], *, now: datetime, tolerance: timedelta
) -> list[TamperFinding]:
    findings: list[TamperFinding] = []
    last: datetime | None = None
    for event in events:
        last = _parse_ts(event.ts) or last
    if last is None:
        return findings
    if now - last > tolerance:
        findings.append(
            TamperFinding(
                kind="long_quiet_period",
                severity="info",
                message=(
                    f"no events for {now - last} since last activity at {last!s}"
                ),
                detail={"last_ts": last.isoformat(), "now": now.isoformat()},
            )
        )
    return findings


def _open_close_balance_findings(events: Iterable[Event]) -> list[TamperFinding]:
    opens = 0
    closes = 0
    for event in events:
        if event.type == "transaction.open":
            opens += 1
        elif event.type == "transaction.close":
            closes += 1
    diff = opens - closes
    if diff > 1:
        return [
            TamperFinding(
                kind="open_close_imbalance",
                severity="warn",
                message=(
                    f"{diff} transactions opened without a close. Most "
                    "likely abandoned carts; could also indicate a crash "
                    "between open and close."
                ),
                detail={"opens": opens, "closes": closes},
            )
        ]
    return []


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


__all__ = [
    "CLOCK_SKEW_TOLERANCE",
    "LONG_QUIET_TOLERANCE",
    "TamperFinding",
    "emit",
    "scan",
]
