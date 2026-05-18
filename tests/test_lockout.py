"""Tests for the PIN-failure lockout projection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from lemonade_cashier.safety.lockout import (
    DEFAULT_FAILURE_THRESHOLD,
    LockoutError,
    lift_lockout,
    record_pin_attempt,
    state_for,
)


T0 = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)


def test_initial_state_is_unlocked(event_log):
    state = state_for(event_log, "alice", now=T0)
    assert not state.is_locked
    assert state.recent_failures == 0


def test_single_failure_no_lock(event_log):
    record_pin_attempt(event_log, "alice", success=False, now=T0)
    state = state_for(event_log, "alice", now=T0)
    assert not state.is_locked
    assert state.recent_failures == 1


def test_threshold_failures_lock(event_log):
    for i in range(DEFAULT_FAILURE_THRESHOLD):
        record_pin_attempt(
            event_log, "alice", success=False, now=T0 + timedelta(seconds=i)
        )
    state = state_for(event_log, "alice", now=T0 + timedelta(seconds=10))
    assert state.is_locked
    assert state.locked_until is not None


def test_locked_attempt_raises(event_log):
    for i in range(DEFAULT_FAILURE_THRESHOLD):
        record_pin_attempt(
            event_log, "alice", success=False, now=T0 + timedelta(seconds=i)
        )
    with pytest.raises(LockoutError):
        record_pin_attempt(
            event_log, "alice", success=False, now=T0 + timedelta(seconds=10)
        )


def test_lockout_expires_naturally(event_log):
    for i in range(DEFAULT_FAILURE_THRESHOLD):
        record_pin_attempt(
            event_log, "alice", success=False, now=T0 + timedelta(seconds=i)
        )
    # Default lockout is 5 minutes — check just after that.
    far_future = T0 + timedelta(minutes=10)
    state = state_for(event_log, "alice", now=far_future)
    assert not state.is_locked


def test_success_clears_failure_counter(event_log):
    record_pin_attempt(event_log, "alice", success=False, now=T0)
    record_pin_attempt(event_log, "alice", success=False, now=T0 + timedelta(seconds=1))
    record_pin_attempt(event_log, "alice", success=True, now=T0 + timedelta(seconds=2))
    state = state_for(event_log, "alice", now=T0 + timedelta(seconds=3))
    assert not state.is_locked
    assert state.recent_failures == 0


def test_lift_lockout_requires_distinct_actor(event_log):
    with pytest.raises(LockoutError, match="cannot lift their own"):
        lift_lockout(event_log, "alice", by_actor="alice")


def test_lift_lockout_clears_state(event_log):
    for i in range(DEFAULT_FAILURE_THRESHOLD):
        record_pin_attempt(
            event_log, "alice", success=False, now=T0 + timedelta(seconds=i)
        )
    lift_lockout(
        event_log, "alice", by_actor="manager", now=T0 + timedelta(seconds=10)
    )
    state = state_for(event_log, "alice", now=T0 + timedelta(seconds=11))
    assert not state.is_locked
    assert state.recent_failures == 0


def test_failures_outside_window_dont_count(event_log):
    # Two failures more than 60s apart — neither should count toward
    # the threshold from the perspective of "now".
    record_pin_attempt(event_log, "alice", success=False, now=T0)
    record_pin_attempt(
        event_log, "alice", success=False, now=T0 + timedelta(minutes=5)
    )
    state = state_for(event_log, "alice", now=T0 + timedelta(minutes=5, seconds=1))
    assert state.recent_failures == 1  # only the most recent is in the 60s window
    assert not state.is_locked
