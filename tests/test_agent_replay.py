"""Tests that agent.proposal events flow through replay."""

from __future__ import annotations

from lemonade_cashier.agents import proposals
from lemonade_cashier.audit.replay import replay


def test_replay_surfaces_agent_history(event_log):
    """A proposal event lands in state.agent_history when replayed."""

    proposals.write(
        event_log,
        agent="lemonade",
        kind="normalize",
        input={"phrase": "milkk"},
        output={"phrase": "milk 1 gal"},
        confidence=0.91,
        decision="accepted",
    )
    state = replay(event_log.read_all()).to_state()
    assert "agent_history" in state
    assert len(state["agent_history"]) == 1
    entry = state["agent_history"][0]
    assert entry["payload"]["agent"] == "lemonade"
    assert entry["payload"]["decision"] == "accepted"


def test_replay_omits_agent_history_when_empty(event_log):
    """No proposals → no agent_history key. Same convention as
    state.cit / state.bags."""

    event_log.append("transaction.open", {"attendant": "alice"})
    state = replay(event_log.read_all()).to_state()
    assert "agent_history" not in state


def test_supervisor_unreachable_writes_proposal(seeded_db, event_log):
    """When Lemonade is enabled but unreachable, an `unreachable`
    proposal lands in the chain so investigators can distinguish
    'agent tried and failed' from 'agent was never asked'."""

    from lemonade_cashier.agents.lemonade_client import LemonadeConfig
    from lemonade_cashier.agents.supervisor import Supervisor, SupervisorConfig

    sup = Supervisor(
        event_log,
        SupervisorConfig(
            lemonade=LemonadeConfig(
                url="http://127.0.0.1:1", timeout_sec=0.25, enabled=True
            )
        ),
    )
    sup.handle_text("zzz nonsense")  # no inventory match, triggers fallback

    history = proposals.proposals_from_events(event_log.read_all())
    # Lemonade enabled but unreachable → "unreachable" proposal recorded.
    assert any(p.agent == "lemonade" and p.decision == "unreachable" for p in history)
