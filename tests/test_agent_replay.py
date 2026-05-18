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


def test_confirmation_flow_preserves_agent_provenance(seeded_db, event_log, monkeypatch):
    """When a model proposes a low-confidence match that the attendant
    confirms, the resulting cart.add MUST keep actor=agent_confirmed
    and source=model_proposed — not silently demote to attendant/typed
    on the second pass.

    Regression test for the independent-reviewer finding that the
    confirmation round-trip was laundering agent provenance through
    the canonical product name."""

    from lemonade_cashier.agents.lemonade_client import (
        LemonadeConfig,
        NormalizedPhrase,
    )
    from lemonade_cashier.agents.supervisor import Supervisor, SupervisorConfig
    import lemonade_cashier.agents.supervisor as sup_mod

    # Stub the Lemonade normalizer to return a candidate that resolves
    # to a low-confidence match via substring (not exact). The cleanest
    # way: make the model propose "appl" -> "apple". find_product("apple")
    # would be exact (1.0 conf), so instead the model proposes a
    # candidate that find_product resolves at the substring score
    # (0.86) — under the 0.8 threshold default? No — 0.86 > 0.8.
    # Make threshold tight enough that 0.86 is below it.
    def fake_normalize(phrase, cart_shape, config):
        return NormalizedPhrase(candidate="apples", confidence=0.55, raw={})

    monkeypatch.setattr(sup_mod, "lemonade_normalize", fake_normalize)

    sup = Supervisor(
        event_log,
        SupervisorConfig(
            lemonade=LemonadeConfig(enabled=True),
            confidence_threshold=0.9,  # forces "apples" (0.95 alias) below
        ),
        # The 0.9 threshold means even "apples" → APL001 at confidence
        # 0.95 still triggers the model fallback path? No — 0.95 > 0.9
        # so it auto-adds. Tighten further.
    )
    sup.config.confidence_threshold = 0.98  # forces the confirm gate

    # First pass: model proposes, low confidence → needs_confirmation.
    out = sup.handle_text("xyz nonsense")
    assert out.needs_confirmation
    assert out.candidate_source == "model_proposed"

    # Second pass with the canonical name + source_hint.
    out = sup.handle_text(
        out.candidate_match.name,
        confirmed=True,
        source_hint=out.candidate_source,
    )

    # The cart line must reflect the original agent provenance.
    items = out.state["items"]
    assert len(items) == 1
    assert items[0]["source"] == "model_proposed"
    assert items[0]["actor"] == "agent_confirmed"


def test_supervisor_unreachable_writes_proposal(seeded_db, event_log):
    """When Lemonade is enabled but unreachable, an `unreachable`
    proposal lands in the chain so investigators can distinguish
    'agent tried and failed' from 'agent was never asked'.

    Also asserts the call returns within the configured timeout
    budget — a hung connect should not block the cashier loop.
    Qodo flagged this as a testability rule violation when the
    timeout assertion was missing."""

    import time

    from lemonade_cashier.agents.lemonade_client import LemonadeConfig
    from lemonade_cashier.agents.supervisor import Supervisor, SupervisorConfig

    timeout_sec = 0.25
    sup = Supervisor(
        event_log,
        SupervisorConfig(
            lemonade=LemonadeConfig(
                url="http://127.0.0.1:1", timeout_sec=timeout_sec, enabled=True
            )
        ),
    )
    start = time.monotonic()
    sup.handle_text("zzz nonsense")  # no inventory match, triggers fallback
    elapsed = time.monotonic() - start

    # The single fallback path opens at most two sockets (Lemonade, then
    # FLM). FLM is disabled by default, so only Lemonade tries. Budget
    # is the configured timeout + generous slack for connect-refused
    # overhead. If this ever runs over, something is hanging instead
    # of bouncing off the closed socket.
    assert elapsed < timeout_sec + 2.0, (
        f"unreachable call took {elapsed:.2f}s > budget {timeout_sec + 2.0}s"
    )

    history = proposals.proposals_from_events(event_log.read_all())
    assert any(p.agent == "lemonade" and p.decision == "unreachable" for p in history)
