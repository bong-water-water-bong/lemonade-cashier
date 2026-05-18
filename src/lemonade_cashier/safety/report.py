"""End-of-shift (EOS) safety report.

Composes everything in :mod:`safety` plus the till / bag state from
:mod:`safety.cit` and :mod:`safety.bags` into a single rolled-up report:

::

    {
      "schema_version": 1,
      "generated_at": "<iso ts>",
      "log_path": "<event log path>",
      "log_verified": true,
      "verify_error": null,
      "till": { ... },
      "bags": {
        "bag-...": { ... },
        ...
      },
      "attendants": {
        "alice": { ... per-attendant profile },
        ...
      },
      "tamper_findings": [ ... ],
      "totals": {
        "transactions": N,
        "voids": M,
        "discrepancies": K,
        "pin_failures": P
      }
    }

The text rendering is 80-column ASCII so it can be pinned in a
break-room printer.

The report does **not** write anything to the event log by default;
the caller decides via :func:`save` whether to persist as a JSON
sidecar or via :func:`emit_tamper_events` whether to land the tamper
findings into the chain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..audit.eventlog import EventLog, EventLogError
from . import tamper
from .bags import bags_from_events
from .cit import till_state_from_events
from .profile import profiles_from_events


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Report:
    state: dict[str, object]

    def to_json(self) -> str:
        return json.dumps(self.state, indent=2, sort_keys=True)

    def to_text(self) -> str:
        return _render_text(self.state)


def build(log: EventLog, *, now: datetime | None = None) -> Report:
    """Walk ``log`` and return a :class:`Report`."""

    now = now or datetime.now(timezone.utc)
    events = log.read_all()

    log_verified = True
    verify_error: str | None = None
    try:
        log.verify()
    except EventLogError as exc:
        log_verified = False
        verify_error = str(exc)

    till = till_state_from_events(events)
    bags = bags_from_events(events)
    profiles = profiles_from_events(events)
    tamper_findings = tamper.scan(log, now=now)

    state: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "log_path": str(log.path),
        "log_verified": log_verified,
        "verify_error": verify_error,
        "till": till.to_state(),
        "bags": {bag_id: snap.to_state() for bag_id, snap in bags.items()},
        "attendants": {actor: prof.to_state() for actor, prof in profiles.items()},
        "tamper_findings": [f.to_state() for f in tamper_findings],
        "totals": {
            "transactions": sum(p.total_transactions for p in profiles.values()),
            "voids": sum(p.voids for p in profiles.values()),
            "bag_discrepancies": sum(
                1 for s in bags.values() if s.status == "discrepancy"
            ),
            "pin_failures": sum(p.pin_failures for p in profiles.values()),
        },
    }
    return Report(state=state)


def save(report: Report, directory: Path | str) -> Path:
    """Persist ``report.to_json()`` as ``<directory>/eos-<ts>.json``."""

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ts = str(report.state.get("generated_at", "")).replace(":", "-")
    path = directory / f"eos-{ts}.json"
    path.write_text(report.to_json(), encoding="utf-8")
    return path


def _render_text(state: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("LEMONADE CASHIER — END-OF-SHIFT REPORT".center(80))
    lines.append(str(state.get("generated_at", "")).center(80))
    lines.append("=" * 80)

    lines.append("")
    if not state.get("log_verified"):
        lines.append("!! LOG VERIFICATION FAILED: " + str(state.get("verify_error", "")))
    else:
        lines.append("log: verified")
    lines.append(f"log path: {state.get('log_path', '')}")

    lines.append("")
    lines.append("-- TILL --")
    till = state.get("till", {})
    if isinstance(till, dict):
        for k, v in till.items():
            lines.append(f"  {k}: {v}")

    lines.append("")
    lines.append("-- BAGS --")
    bags = state.get("bags", {})
    if isinstance(bags, dict):
        if not bags:
            lines.append("  (none)")
        else:
            for bag_id, snap in bags.items():
                if isinstance(snap, dict):
                    lines.append(
                        f"  {bag_id}: status={snap.get('status')}, "
                        f"manifest={snap.get('manifest_total', '?')}, "
                        f"counted={snap.get('counted_total', '?')}"
                    )

    lines.append("")
    lines.append("-- ATTENDANTS --")
    attendants = state.get("attendants", {})
    if isinstance(attendants, dict):
        if not attendants:
            lines.append("  (none)")
        else:
            for actor, prof in attendants.items():
                if isinstance(prof, dict):
                    lines.append(
                        f"  {actor}: txns={prof.get('total_transactions')}, "
                        f"voids={prof.get('voids')} "
                        f"({prof.get('void_rate', 0):.2%}), "
                        f"pin_failures={prof.get('pin_failures')}"
                    )

    lines.append("")
    lines.append("-- TAMPER FINDINGS --")
    findings = state.get("tamper_findings", [])
    if isinstance(findings, list):
        if not findings:
            lines.append("  (none)")
        else:
            for finding in findings:
                if isinstance(finding, dict):
                    lines.append(
                        f"  [{finding.get('severity', '?').upper():8s}] "
                        f"{finding.get('kind', '?')}: {finding.get('message', '')}"
                    )

    lines.append("")
    lines.append("=" * 80)
    return "\n".join(lines)


__all__ = ["Report", "SCHEMA_VERSION", "build", "save"]
