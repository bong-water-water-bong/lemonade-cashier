"""Tests for the agent-activity projection (A3).

The projection scans the hash-chained event log and answers:

* How many ``agent.proposal`` events were written this session?
* Broken down by decision (accepted / rejected / needs_confirmation /
  unreachable / out_of_capability), by ``agent`` (type tag), and by
  ``agent_id`` (per-instance identity).
* How many unique ``delegation_id`` values appeared on proposals vs
  on cart events, and how many cart events carry an orphan
  ``delegation_id`` with no matching proposal.

It's a *read-only* projection over an :class:`EventLog`; the cashier's
replay tooling and the sister `lemonade-security` auditor both consume
the same answers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lemonade_cashier.agents import proposals
from lemonade_cashier.agents.flm_client import FLMConfig
from lemonade_cashier.agents.lemonade_client import LemonadeConfig, NormalizedPhrase
from lemonade_cashier.agents.supervisor import Supervisor, SupervisorConfig
from lemonade_cashier.audit.agent_activity import (
    AgentActivitySummary,
    summarize,
)

# ---------------------------------------------------------------------------
# Counting basics
# ---------------------------------------------------------------------------


def test_empty_log_yields_zero_counts(event_log):
    """No events → all counts zero, no rows in any breakdown."""

    s = summarize(event_log)
    assert isinstance(s, AgentActivitySummary)
    assert s.total_proposals == 0
    assert s.by_decision == {}
    assert s.by_agent == {}
    assert s.by_agent_id == {}
    assert s.delegations_minted == 0
    assert s.delegations_consumed_by_cart == 0
    assert s.orphan_delegations == 0


def test_log_with_only_non_proposal_events_yields_zero(event_log):
    """Cart and till events without any agent.proposal → still empty."""

    event_log.append("transaction.open", {"attendant": "alice"})
    event_log.append("cart.add", {"sku": "APL001", "name": "apple"})
    event_log.append("transaction.close", {})

    s = summarize(event_log)
    assert s.total_proposals == 0
    assert s.by_decision == {}


def test_proposal_counts_by_decision_and_agent(event_log):
    """Mixed decisions and agents → correct per-bucket counts."""

    proposals.write(
        event_log,
        agent="lemonade",
        kind="normalize",
        input={},
        output={},
        confidence=0.9,
        decision="accepted",
    )
    proposals.write(
        event_log,
        agent="lemonade",
        kind="normalize",
        input={},
        output={},
        confidence=0.4,
        decision="rejected",
    )
    proposals.write(
        event_log,
        agent="flm",
        kind="normalize",
        input={},
        output=None,
        confidence=0.0,
        decision="unreachable",
    )
    proposals.write(
        event_log,
        agent="flm",
        kind="normalize",
        input={},
        output={},
        confidence=0.7,
        decision="needs_confirmation",
    )

    s = summarize(event_log)
    assert s.total_proposals == 4
    assert s.by_decision == {
        "accepted": 1,
        "rejected": 1,
        "unreachable": 1,
        "needs_confirmation": 1,
    }
    assert s.by_agent == {"lemonade": 2, "flm": 2}


# ---------------------------------------------------------------------------
# agent_id breakdown (uses A1)
# ---------------------------------------------------------------------------


def test_by_agent_id_distinguishes_two_lemonade_instances(event_log):
    """Two different agent_ids under the same agent type yield distinct
    rows in by_agent_id but share their row in by_agent."""

    proposals.write(
        event_log,
        agent="lemonade",
        agent_id="lemonade@http://127.0.0.1:8000#qwen3:4b",
        kind="normalize",
        input={},
        output={},
        confidence=0.9,
        decision="accepted",
    )
    proposals.write(
        event_log,
        agent="lemonade",
        agent_id="lemonade@http://127.0.0.1:8001#gemma3:1b",
        kind="normalize",
        input={},
        output={},
        confidence=0.7,
        decision="accepted",
    )

    s = summarize(event_log)
    assert s.by_agent == {"lemonade": 2}
    assert s.by_agent_id == {
        "lemonade@http://127.0.0.1:8000#qwen3:4b": 1,
        "lemonade@http://127.0.0.1:8001#gemma3:1b": 1,
    }


def test_legacy_proposals_show_under_agent_id_none(event_log):
    """Proposals written before the A1 schema bump (no agent_id) land
    under a ``None`` key so an investigator can quantify the gap."""

    event_log.append(
        proposals.EVENT_TYPE,
        {
            "agent": "lemonade",
            "kind": "normalize",
            "input": {},
            "output": {},
            "confidence": 0.9,
            "decision": "accepted",
        },
    )
    s = summarize(event_log)
    assert s.by_agent_id == {None: 1}


# ---------------------------------------------------------------------------
# delegation_id reconciliation (uses A1+A2)
# ---------------------------------------------------------------------------


def test_minted_delegations_counts_unique_ids(event_log):
    """Two proposals share the same delegation_id (e.g. lemonade and
    flm unreachable for the same decision) → 1 minted delegation."""

    proposals.write(
        event_log,
        agent="lemonade",
        delegation_id="d" * 32,
        kind="normalize",
        input={},
        output=None,
        confidence=0.0,
        decision="unreachable",
    )
    proposals.write(
        event_log,
        agent="flm",
        delegation_id="d" * 32,  # same id — same supervisor decision
        kind="normalize",
        input={},
        output=None,
        confidence=0.0,
        decision="unreachable",
    )

    s = summarize(event_log)
    assert s.total_proposals == 2
    assert s.delegations_minted == 1


def test_delegation_consumed_by_cart_event(event_log):
    """A cart.add that carries the same delegation_id as a prior
    proposal counts as a consumed delegation. No orphan."""

    proposals.write(
        event_log,
        agent="lemonade",
        delegation_id="a" * 32,
        kind="normalize",
        input={},
        output={"phrase": "milk"},
        confidence=0.9,
        decision="accepted",
    )
    event_log.append(
        "cart.add",
        {
            "sku": "MLK001",
            "name": "milk 1 gal",
            "unit_price": "3.49",
            "taxable": False,
            "quantity": 1,
            "actor": "agent_auto",
            "source": "model_proposed",
            "confidence": 0.95,
            "delegation_id": "a" * 32,
        },
    )

    s = summarize(event_log)
    assert s.delegations_minted == 1
    assert s.delegations_consumed_by_cart == 1
    assert s.orphan_delegations == 0


def test_orphan_delegation_on_cart_event(event_log):
    """A cart.add carrying a delegation_id with NO matching proposal in
    the chain is an orphan. The projection surfaces this count so a
    forensic reader can spot forged-consequence claims at a glance."""

    event_log.append(
        "cart.add",
        {
            "sku": "MLK001",
            "name": "milk 1 gal",
            "unit_price": "3.49",
            "taxable": False,
            "quantity": 1,
            "actor": "agent_auto",
            "source": "model_proposed",
            "confidence": 0.95,
            "delegation_id": "z" * 32,  # no prior proposal with this id
        },
    )

    s = summarize(event_log)
    assert s.delegations_minted == 0
    assert s.delegations_consumed_by_cart == 1
    assert s.orphan_delegations == 1


def test_deterministic_cart_add_does_not_count(event_log):
    """A cart.add with no delegation_id (pure deterministic path) does
    not show up in the delegation reconciliation."""

    event_log.append(
        "cart.add",
        {
            "sku": "APL001",
            "name": "apple",
            "unit_price": "0.75",
            "taxable": True,
            "quantity": 1,
            "actor": "attendant",
            "source": "typed",
            "confidence": 1.0,
        },
    )

    s = summarize(event_log)
    assert s.delegations_minted == 0
    assert s.delegations_consumed_by_cart == 0
    assert s.orphan_delegations == 0


# ---------------------------------------------------------------------------
# Round-trip through the supervisor (the real-world generator)
# ---------------------------------------------------------------------------


def test_summary_reflects_supervisor_round_trip(
    seeded_db: Path, event_log, monkeypatch: pytest.MonkeyPatch
):
    """One supervisor handle_text that crosses the model produces exactly
    1 proposal (accepted, lemonade, with an agent_id and a delegation_id)
    plus 1 cart.add consuming that delegation. The projection sees both."""

    from lemonade_cashier.agents import supervisor as supervisor_mod

    cfg = SupervisorConfig(
        lemonade=LemonadeConfig(enabled=True, url="http://127.0.0.1:8000", model="qwen3:4b"),
        flm=FLMConfig(enabled=False),
    )

    def fake_lemonade_normalize(phrase, cart_shape, config):
        return NormalizedPhrase(candidate="milk 1 gal", confidence=0.95, raw={})

    monkeypatch.setattr(supervisor_mod, "lemonade_normalize", fake_lemonade_normalize)

    sv = Supervisor(event_log, cfg)
    sv.handle_text("white moo juice")  # forces the normalizer branch

    s = summarize(event_log)
    assert s.total_proposals == 1
    assert s.by_decision == {"accepted": 1}
    assert s.by_agent == {"lemonade": 1}
    # exactly one distinct agent_id
    assert len(s.by_agent_id) == 1
    only_agent_id = next(iter(s.by_agent_id))
    assert only_agent_id is not None
    assert "qwen3:4b" in only_agent_id
    # delegation reconciliation: 1 minted, 1 consumed, 0 orphan
    assert s.delegations_minted == 1
    assert s.delegations_consumed_by_cart == 1
    assert s.orphan_delegations == 0


# ---------------------------------------------------------------------------
# Source flexibility
# ---------------------------------------------------------------------------


def test_summarize_accepts_a_path(tmp_path: Path):
    """summarize() accepts a Path to a JSONL log directly, not just an
    EventLog instance — so the replay CLI can call it with a filename."""

    from lemonade_cashier.audit.eventlog import EventLog

    log = EventLog(tmp_path / "events.jsonl")
    proposals.write(
        log,
        agent="lemonade",
        kind="normalize",
        input={},
        output={},
        confidence=0.9,
        decision="accepted",
    )

    s = summarize(tmp_path / "events.jsonl")
    assert s.total_proposals == 1
    assert s.by_decision == {"accepted": 1}
