"""Tests for agent.proposal events and the capability registry."""

from __future__ import annotations

import pytest

from lemonade_cashier.agents import proposals, registry


def test_registry_has_every_known_agent():
    """Every agent module exists in the registry. Adding a new agent
    without updating registry.REGISTRY should be caught here."""

    assert {"lemonade", "flm", "qa", "summarizer", "gaia"} <= set(registry.REGISTRY)


def test_qa_cannot_normalize():
    """The Q&A agent must never be allowed to emit cart-mutating
    normalize proposals. Pinned here so a future contributor can't
    quietly widen its capability."""

    with pytest.raises(registry.CapabilityError):
        registry.assert_can_emit("qa", "normalize")


def test_summarizer_cannot_normalize():
    with pytest.raises(registry.CapabilityError):
        registry.assert_can_emit("summarizer", "normalize")


def test_lemonade_cannot_chat_response():
    """Symmetric: the normalizer agents cannot emit chat_response.
    Each agent has exactly one capability."""

    with pytest.raises(registry.CapabilityError):
        registry.assert_can_emit("lemonade", "chat_response")


def test_unknown_agent_rejected():
    with pytest.raises(registry.CapabilityError, match="unknown agent"):
        registry.assert_can_emit("evil-agent", "normalize")


def test_proposal_round_trips_through_event(event_log):
    """An agent.proposal event written via proposals.write() reads
    back as the same :class:`Proposal`."""

    event = proposals.write(
        event_log,
        agent="lemonade",
        kind="normalize",
        input={"phrase": "milkk"},
        output={"phrase": "milk 1 gal"},
        confidence=0.91,
        decision="accepted",
    )
    assert event.type == proposals.EVENT_TYPE

    p = proposals.Proposal.from_event(event)
    assert p.agent == "lemonade"
    assert p.kind == "normalize"
    assert p.input == {"phrase": "milkk"}
    assert p.output == {"phrase": "milk 1 gal"}
    assert abs(p.confidence - 0.91) < 1e-9
    assert p.decision == "accepted"


def test_confidence_clamped_to_unit_interval(event_log):
    """Out-of-range confidence is clamped, not rejected (defensive)."""

    e1 = proposals.write(
        event_log, agent="lemonade", kind="normalize",
        input={}, output={}, confidence=1.5, decision="accepted",
    )
    e2 = proposals.write(
        event_log, agent="lemonade", kind="normalize",
        input={}, output={}, confidence=-0.5, decision="rejected",
    )
    assert proposals.Proposal.from_event(e1).confidence == 1.0
    assert proposals.Proposal.from_event(e2).confidence == 0.0


def test_proposals_from_events_filters_other_types(event_log):
    """proposals_from_events ignores non-proposal events. Mixed logs
    must not produce noise."""

    event_log.append("transaction.open", {"attendant": "alice"})
    proposals.write(
        event_log, agent="lemonade", kind="normalize",
        input={"phrase": "x"}, output=None, confidence=0.1, decision="rejected",
    )
    event_log.append("cart.add", {"sku": "X", "name": "x", "unit_price": "1.00",
                                   "taxable": True, "quantity": 1,
                                   "actor": "attendant", "source": "typed",
                                   "confidence": 1.0})

    got = proposals.proposals_from_events(event_log.read_all())
    assert len(got) == 1
    assert got[0].agent == "lemonade"
