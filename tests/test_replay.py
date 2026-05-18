"""Tests for the pure-function replay of an event log to state."""

from __future__ import annotations

from lemonade_cashier.audit.replay import replay, replay_log
from lemonade_cashier.agents.supervisor import Supervisor, SupervisorConfig
from lemonade_cashier.core.money import to_money


def test_replay_reconstructs_live_state(seeded_db, event_log):
    supervisor = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.15")))
    supervisor.handle_text("apple")
    supervisor.handle_text("two of those")
    supervisor.handle_text("milk")
    live = supervisor._state()  # noqa: SLF001 — internal access ok in tests

    replayed = replay(event_log.read_all()).to_state()
    # The live state has voids_in_txn; the replay doesn't track it
    # explicitly. Drop that key for the equality check.
    live.pop("voids_in_txn", None)
    replayed_skus = [item["sku"] for item in replayed["items"]]
    live_skus = [item["sku"] for item in live["items"]]
    assert replayed_skus == live_skus
    assert replayed["subtotal"] == live["subtotal"]
    assert replayed["tax"] == live["tax"]
    assert replayed["total"] == live["total"]


def test_replay_handles_removal(seeded_db, event_log):
    supervisor = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.15")))
    supervisor.handle_text("apple")
    supervisor.handle_text("milk")
    supervisor.handle_text("remove that")
    state = replay(event_log.read_all()).to_state()
    assert [item["sku"] for item in state["items"]] == ["APL001"]


def test_replay_via_path(seeded_db, tmp_path):
    from lemonade_cashier.audit.eventlog import EventLog

    log_path = tmp_path / "log.jsonl"
    log = EventLog(log_path)
    supervisor = Supervisor(log, SupervisorConfig(tax_rate=to_money("0.15")))
    supervisor.handle_text("apple")
    supervisor.handle_text("milk")

    state = replay_log(log_path).to_state()
    assert {item["sku"] for item in state["items"]} == {"APL001", "MLK001"}
