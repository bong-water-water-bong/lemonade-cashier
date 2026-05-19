"""Tests for the read-only Q&A agent."""

from __future__ import annotations

from lemonade_cashier.agents import proposals
from lemonade_cashier.agents.lemonade_client import LemonadeConfig
from lemonade_cashier.agents.qa_agent import ask


def test_qa_disabled_returns_none(event_log):
    """Disabled Lemonade → no answer, no proposal event."""

    config = LemonadeConfig(enabled=False)
    answer = ask(event_log, "what was my last big void?", config=config)
    assert answer is None
    assert proposals.proposals_from_events(event_log.read_all()) == []


def test_qa_unreachable_records_proposal(event_log):
    """Enabled but unreachable → returns None AND writes an
    `unreachable` proposal so the audit log shows the agent tried."""

    config = LemonadeConfig(
        url="http://127.0.0.1:1",  # nothing there
        timeout_sec=0.25,
        enabled=True,
    )
    answer = ask(event_log, "what was my last big void?", config=config)
    assert answer is None

    history = proposals.proposals_from_events(event_log.read_all())
    assert len(history) == 1
    assert history[0].agent == "qa"
    assert history[0].kind == "chat_response"
    assert history[0].decision == "unreachable"


def test_qa_empty_question_returns_none(event_log):
    config = LemonadeConfig(enabled=True)
    assert ask(event_log, "", config=config) is None
    assert ask(event_log, "   ", config=config) is None
    # No proposal written for an empty question — we never asked.
    assert proposals.proposals_from_events(event_log.read_all()) == []
