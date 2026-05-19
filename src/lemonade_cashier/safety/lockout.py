"""Per-attendant PIN-failure lockout.

State is **purely an event projection** over the audit log:

* ``safety.pin.failed`` events for the attendant within the rolling
  window (default 60 seconds) accumulate toward the lockout threshold.
* ``safety.pin.ok`` events reset the counter to zero.
* ``safety.lockout.locked`` / ``safety.lockout.lifted`` events mark
  explicit state transitions and form a strict "locked ↔ unlocked"
  flip-flop the audit layer can render.

There is no in-memory cache. Two cashier processes can't disagree
because the only source of truth is the event log — same invariant as
:mod:`safety.bags`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..audit.eventlog import Event, EventLog
from .pins import _validate_actor_id, verify_pin

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_FAILURE_WINDOW = timedelta(seconds=60)
DEFAULT_LOCKOUT_DURATION = timedelta(minutes=5)


class LockoutError(RuntimeError):
    """Raised when a PIN attempt happens while the attendant is locked out."""


@dataclass(frozen=True)
class LockoutState:
    """Read-only snapshot of one attendant's lockout status."""

    actor_id: str
    is_locked: bool
    locked_until: datetime | None
    recent_failures: int

    def to_state(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "is_locked": self.is_locked,
            "locked_until": (
                self.locked_until.isoformat(timespec="seconds") if self.locked_until else None
            ),
            "recent_failures": self.recent_failures,
        }


def record_pin_attempt(
    log: EventLog,
    actor_id: str,
    *,
    success: bool,
    now: datetime | None = None,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    failure_window: timedelta = DEFAULT_FAILURE_WINDOW,
    lockout_duration: timedelta = DEFAULT_LOCKOUT_DURATION,
) -> LockoutState:
    """Append the appropriate ``safety.pin.*`` event and return the new
    :class:`LockoutState`.

    If this failure pushes the attendant past ``failure_threshold``
    within ``failure_window``, also emits ``safety.lockout.locked`` with
    the absolute ``until`` timestamp.

    If the attendant is already locked, raises :class:`LockoutError`
    *before* writing anything to the log — a locked attendant's
    attempts should not refresh the window.
    """

    actor_id = _validate_actor_id(actor_id)
    now = now or datetime.now(UTC)

    # Check current state first; refuse to log fresh attempts while locked.
    current = state_for(
        log,
        actor_id,
        now=now,
        failure_window=failure_window,
        lockout_duration=lockout_duration,
    )
    if current.is_locked:
        raise LockoutError(f"{actor_id!r} is locked out until {current.locked_until!s}")

    event_type = "safety.pin.ok" if success else "safety.pin.failed"
    log.append(
        event_type,
        {"actor_id": actor_id},
        ts=now.isoformat(timespec="seconds"),
    )

    if success:
        return state_for(log, actor_id, now=now, lockout_duration=lockout_duration)

    # Re-check after the failed write to decide whether to lock.
    updated = state_for(
        log,
        actor_id,
        now=now,
        lockout_duration=lockout_duration,
        failure_window=failure_window,
    )
    if updated.recent_failures >= failure_threshold:
        locked_until = now + lockout_duration
        log.append(
            "safety.lockout.locked",
            {
                "actor_id": actor_id,
                "until": locked_until.isoformat(timespec="seconds"),
                "reason": (
                    f"{updated.recent_failures} pin failures within "
                    f"{int(failure_window.total_seconds())}s"
                ),
            },
            ts=now.isoformat(timespec="seconds"),
        )
        return LockoutState(
            actor_id=actor_id,
            is_locked=True,
            locked_until=locked_until,
            recent_failures=updated.recent_failures,
        )
    return updated


def lift_lockout(
    log: EventLog,
    actor_id: str,
    *,
    by_actor: str,
    by_pin: str,
    now: datetime | None = None,
    pin_store_path: str | None = None,
) -> Event:
    """Supervisor (``by_actor``) lifts ``actor_id``'s lockout early.

    ``by_actor`` must have a PIN configured in the store and must
    supply it via ``by_pin``. Without a verified PIN, the lift is
    refused. This closes the original gap where any caller could
    unlock any attendant simply by passing a string id.
    """

    actor_id = _validate_actor_id(actor_id)
    by_actor = _validate_actor_id(by_actor)
    if actor_id == by_actor:
        raise LockoutError("an attendant cannot lift their own lockout")
    if not verify_pin(by_actor, by_pin, path=pin_store_path):
        raise LockoutError(f"lift_lockout: {by_actor!r}'s PIN did not verify; refusing to lift")
    now = now or datetime.now(UTC)
    return log.append(
        "safety.lockout.lifted",
        {"actor_id": actor_id, "by": by_actor},
        ts=now.isoformat(timespec="seconds"),
    )


def state_for(
    log: EventLog,
    actor_id: str,
    *,
    now: datetime | None = None,
    failure_window: timedelta = DEFAULT_FAILURE_WINDOW,
    lockout_duration: timedelta = DEFAULT_LOCKOUT_DURATION,
) -> LockoutState:
    """Reconstruct ``actor_id``'s lockout state from the event log."""

    actor_id = _validate_actor_id(actor_id)
    now = now or datetime.now(UTC)
    return _project(
        log.read_all(),
        actor_id,
        now=now,
        failure_window=failure_window,
        lockout_duration=lockout_duration,
    )


def _project(
    events: Iterable[Event],
    actor_id: str,
    *,
    now: datetime,
    failure_window: timedelta,
    lockout_duration: timedelta,
) -> LockoutState:
    failures_in_window: list[datetime] = []
    locked_until: datetime | None = None
    is_locked = False

    for event in events:
        if not event.type.startswith("safety."):
            continue
        if event.payload.get("actor_id") != actor_id:
            continue
        ts = _parse_ts(event.ts)
        if ts is None:
            continue

        if event.type == "safety.pin.failed":
            failures_in_window.append(ts)
            # Trim the window each time we add.
            failures_in_window = [t for t in failures_in_window if now - t <= failure_window]
        elif event.type == "safety.pin.ok":
            failures_in_window.clear()
        elif event.type == "safety.lockout.locked":
            raw_until = event.payload.get("until")
            until = _parse_ts(raw_until) if isinstance(raw_until, str) else None
            locked_until = until
            is_locked = until is not None and now < until
        elif event.type == "safety.lockout.lifted":
            locked_until = None
            is_locked = False
            failures_in_window.clear()

    # Final window check (events older than the window don't count).
    failures_in_window = [t for t in failures_in_window if now - t <= failure_window]

    # Even without an explicit "lifted" event, the lockout naturally
    # expires when locked_until <= now.
    if locked_until is not None and now >= locked_until:
        is_locked = False

    return LockoutState(
        actor_id=actor_id,
        is_locked=is_locked,
        locked_until=locked_until if is_locked else None,
        recent_failures=len(failures_in_window),
    )


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


__all__ = [
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_FAILURE_WINDOW",
    "DEFAULT_LOCKOUT_DURATION",
    "LockoutError",
    "LockoutState",
    "lift_lockout",
    "record_pin_attempt",
    "state_for",
]
