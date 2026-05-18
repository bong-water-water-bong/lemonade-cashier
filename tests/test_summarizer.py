"""Tests for the EOS summarizer agent."""

from __future__ import annotations

from lemonade_cashier.agents.lemonade_client import LemonadeConfig
from lemonade_cashier.agents.summarizer import summarize


def test_summarizer_falls_back_when_disabled(event_log):
    """The summarizer must NEVER block on the model. With Lemonade
    disabled, the deterministic template is used."""

    s = summarize(event_log, config=LemonadeConfig(enabled=False))
    assert s.source == "fallback"
    assert "Shift summary" in s.text
    assert "log verification" in s.text.lower()


def test_summarizer_falls_back_when_unreachable(event_log):
    """Enabled but unreachable → still produces a summary via the
    template."""

    config = LemonadeConfig(
        url="http://127.0.0.1:1",
        timeout_sec=0.25,
        enabled=True,
    )
    s = summarize(event_log, config=config)
    assert s.source == "fallback"
    assert "Shift summary" in s.text


def test_summarizer_includes_basic_counts(event_log):
    """The fallback template surfaces transaction and void counts so
    even without the model the operator gets something actionable."""

    event_log.append("transaction.open", {"attendant": "alice", "tax_rate": "0.15"})
    event_log.append("transaction.open", {"attendant": "alice", "tax_rate": "0.15"})

    s = summarize(event_log, config=LemonadeConfig(enabled=False))
    assert "2 transactions" in s.text
