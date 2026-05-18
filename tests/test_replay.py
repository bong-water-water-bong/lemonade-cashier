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


def test_replay_round_trips_cit_events(event_log):
    """CIT events flow through the generic replay path, not just
    `till_state_from_events`. The replay state exposes them under the
    `cit` key so any consumer can render till activity from the JSONL
    alone without depending on safety.cit."""

    from decimal import Decimal

    from lemonade_cashier.safety.cit import (
        DEFAULT_TWO_PERSON_THRESHOLD,
        close_till,
        open_till,
        record_drop,
        record_pickup,
    )

    open_till(event_log, "alice", Decimal("100.00"))
    record_drop(event_log, "alice", Decimal("25.00"))
    record_drop(
        event_log, "alice", DEFAULT_TWO_PERSON_THRESHOLD, witness_id="bob"
    )
    record_pickup(event_log, "alice", Decimal("10.00"))
    close_till(event_log, "alice", Decimal("0.00"))

    state = replay(event_log.read_all()).to_state()
    assert "cit" in state
    cit_types = [e["type"] for e in state["cit"]]
    assert cit_types == [
        "cit.till.open",
        "cit.drop",
        "cit.drop.witnessed",
        "cit.pickup",
        "cit.till.close",
    ]
    # The witnessed drop must carry the witness id through the chain.
    witnessed = next(e for e in state["cit"] if e["type"] == "cit.drop.witnessed")
    assert witnessed["payload"]["witness"] == "bob"


def test_replay_records_malformed_event_without_crashing(event_log):
    """A garbled event payload should land in unknown_events with a
    replay_error annotation; subsequent events still apply cleanly."""

    from lemonade_cashier.audit.replay import replay

    event_log.append("transaction.open", {"tax_rate": "0.15"})
    # Missing required keys (sku, name, unit_price, ...).
    event_log.append("cart.add", {"sku": "ONLY"})
    event_log.append("cart.clear", {})  # valid; should still apply

    state = replay(event_log.read_all()).to_state()
    assert state["items"] == []  # cart.add failed, cart.clear ran
    assert "unknown_events" in state
    bad = state["unknown_events"][0]
    assert bad["type"] == "cart.add"
    assert "replay_error" in bad
