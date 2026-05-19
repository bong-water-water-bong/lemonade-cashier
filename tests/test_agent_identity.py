"""Tests for agent_id and delegation_id on agent.proposal payloads.

These are the schema additions from the IBM Technology / IAM-for-AI
review (see /home/bcloud/Desktop/Shared AI /ibm-technology-transcripts-
cashier-impact.md, action items A1 and A2):

* ``agent_id`` is a stable per-instance identifier for an agent
  (type, endpoint, model). Two Lemonade servers running different
  models on the same host produce distinguishable rows.

* ``delegation_id`` is a UUID minted by the supervisor at the start
  of any decision that may cross the model. The same id appears on
  the ``agent.proposal`` event and on the resulting ``cart.add`` event
  so a forensic reader can follow one model-mediated decision end to
  end with a single grep.

Both fields are *optional*: legacy events (and pure-deterministic cart
adds that never crossed the model) load without them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lemonade_cashier.agents import proposals
from lemonade_cashier.agents.flm_client import FLMConfig
from lemonade_cashier.agents.lemonade_client import LemonadeConfig, NormalizedPhrase
from lemonade_cashier.agents.supervisor import Supervisor, SupervisorConfig

# ---------------------------------------------------------------------------
# A1 — agent_id on the proposal payload
# ---------------------------------------------------------------------------


def test_proposal_payload_carries_agent_id_when_provided(event_log):
    """proposals.write(..., agent_id="...") writes the id into the payload."""

    event = proposals.write(
        event_log,
        agent="lemonade",
        agent_id="lemonade@http://127.0.0.1:8000#qwen3:4b",
        kind="normalize",
        input={"phrase": "milkk"},
        output={"phrase": "milk 1 gal"},
        confidence=0.91,
        decision="accepted",
    )
    assert event.payload["agent_id"] == "lemonade@http://127.0.0.1:8000#qwen3:4b"
    p = proposals.Proposal.from_event(event)
    assert p.agent_id == "lemonade@http://127.0.0.1:8000#qwen3:4b"


def test_proposal_agent_id_omitted_when_not_provided(event_log):
    """When no agent_id is passed, the payload does not contain the
    key. Legacy readers and JSONL-grep tooling continue to work.
    """

    event = proposals.write(
        event_log,
        agent="lemonade",
        kind="normalize",
        input={"phrase": "x"},
        output=None,
        confidence=0.0,
        decision="rejected",
    )
    assert "agent_id" not in event.payload
    p = proposals.Proposal.from_event(event)
    assert p.agent_id is None


def test_proposal_from_legacy_event_has_no_agent_id(event_log):
    """An event written before this schema bump (no agent_id key) must
    still load cleanly with agent_id == None. Replay tolerates absence."""

    event_log.append(
        proposals.EVENT_TYPE,
        {
            "agent": "lemonade",
            "kind": "normalize",
            "input": {"phrase": "milkk"},
            "output": {"phrase": "milk 1 gal"},
            "confidence": 0.9,
            "decision": "accepted",
        },
    )
    event = event_log.read_all()[0]
    p = proposals.Proposal.from_event(event)
    assert p.agent_id is None


def test_two_instances_of_same_agent_distinguishable_by_agent_id(event_log):
    """The point of agent_id: two Lemonade endpoints (different models)
    produce proposals with distinct agent_id values. The plain `agent`
    field can't distinguish them — it's a type tag, not an identity.
    """

    proposals.write(
        event_log,
        agent="lemonade",
        agent_id="lemonade@http://127.0.0.1:8000#qwen3:4b",
        kind="normalize",
        input={"phrase": "milkk"},
        output={"phrase": "milk"},
        confidence=0.9,
        decision="accepted",
    )
    proposals.write(
        event_log,
        agent="lemonade",
        agent_id="lemonade@http://127.0.0.1:8001#gemma3:1b",
        kind="normalize",
        input={"phrase": "egz"},
        output={"phrase": "eggs"},
        confidence=0.7,
        decision="accepted",
    )
    parsed = proposals.proposals_from_events(event_log.read_all())
    ids = {p.agent_id for p in parsed}
    agents = {p.agent for p in parsed}
    assert agents == {"lemonade"}, "type tag alone cannot distinguish instances"
    assert ids == {
        "lemonade@http://127.0.0.1:8000#qwen3:4b",
        "lemonade@http://127.0.0.1:8001#gemma3:1b",
    }


def test_supervisor_lemonade_proposal_includes_lemonade_agent_id(
    seeded_db: Path, event_log, monkeypatch: pytest.MonkeyPatch
):
    """End-to-end: a supervisor that uses Lemonade as the normalizer
    writes an agent.proposal with agent_id derived from the lemonade
    config (url + model).
    """

    from lemonade_cashier.agents import supervisor as supervisor_mod

    cfg = SupervisorConfig(
        lemonade=LemonadeConfig(enabled=True, url="http://127.0.0.1:8000", model="qwen3:4b"),
        flm=FLMConfig(enabled=False),
    )

    # Force a hit on the Lemonade arm: return a canonical phrase that
    # *is* in the seeded inventory ("milk 1 gal").
    def fake_lemonade_normalize(phrase, cart_shape, config):
        return NormalizedPhrase(candidate="milk 1 gal", confidence=0.9, raw={})

    monkeypatch.setattr(supervisor_mod, "lemonade_normalize", fake_lemonade_normalize)

    sv = Supervisor(event_log, cfg)
    # Input that the deterministic catalog cannot match — forces the
    # supervisor down the normalizer branch.
    sv.handle_text("white moo juice")

    proposals_seen = proposals.proposals_from_events(event_log.read_all())
    assert proposals_seen, "supervisor should have written a proposal"
    p = proposals_seen[0]
    assert p.agent == "lemonade"
    assert p.agent_id is not None
    # Must include the URL and model so two configs are distinguishable.
    assert "http://127.0.0.1:8000" in p.agent_id
    assert "qwen3:4b" in p.agent_id


def test_supervisor_flm_proposal_includes_flm_agent_id(
    seeded_db: Path, event_log, monkeypatch: pytest.MonkeyPatch
):
    """When Lemonade is disabled and FLM answers, the proposal's
    agent_id is built from the FLM config, not the Lemonade one."""

    from lemonade_cashier.agents import supervisor as supervisor_mod

    cfg = SupervisorConfig(
        lemonade=LemonadeConfig(enabled=False),
        flm=FLMConfig(enabled=True, url="http://127.0.0.1:11434", model="gemma3:1b"),
    )

    def fake_flm_normalize(phrase, cart_shape, config):
        return NormalizedPhrase(candidate="eggs dozen", confidence=0.8, raw={})

    monkeypatch.setattr(supervisor_mod, "flm_normalize", fake_flm_normalize)

    sv = Supervisor(event_log, cfg)
    sv.handle_text("dozen of those oval things")

    proposals_seen = proposals.proposals_from_events(event_log.read_all())
    assert proposals_seen
    p = proposals_seen[0]
    assert p.agent == "flm"
    assert p.agent_id is not None
    assert "http://127.0.0.1:11434" in p.agent_id
    assert "gemma3:1b" in p.agent_id


# ---------------------------------------------------------------------------
# A2 — delegation_id ties one proposal to one consequence
# ---------------------------------------------------------------------------


_UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


def test_proposal_payload_carries_delegation_id_when_provided(event_log):
    """proposals.write(..., delegation_id=...) writes the id into the payload."""

    delegation_id = "0" * 32
    event = proposals.write(
        event_log,
        agent="lemonade",
        delegation_id=delegation_id,
        kind="normalize",
        input={"phrase": "milkk"},
        output={"phrase": "milk 1 gal"},
        confidence=0.91,
        decision="accepted",
    )
    assert event.payload["delegation_id"] == delegation_id
    p = proposals.Proposal.from_event(event)
    assert p.delegation_id == delegation_id


def test_proposal_delegation_id_omitted_when_not_provided(event_log):
    event = proposals.write(
        event_log,
        agent="lemonade",
        kind="normalize",
        input={"phrase": "x"},
        output=None,
        confidence=0.0,
        decision="rejected",
    )
    assert "delegation_id" not in event.payload
    p = proposals.Proposal.from_event(event)
    assert p.delegation_id is None


def test_model_mediated_cart_add_carries_matching_delegation_id(
    seeded_db: Path, event_log, monkeypatch: pytest.MonkeyPatch
):
    """When the supervisor uses the model normalizer to resolve an
    input that *then* matches a real SKU, both the agent.proposal AND
    the resulting cart.add event carry the SAME delegation_id. A
    single grep on delegation_id surfaces the entire causal chain.
    """

    from lemonade_cashier.agents import supervisor as supervisor_mod

    cfg = SupervisorConfig(
        lemonade=LemonadeConfig(enabled=True, url="http://127.0.0.1:8000", model="qwen3:4b"),
        flm=FLMConfig(enabled=False),
    )

    def fake_lemonade_normalize(phrase, cart_shape, config):
        return NormalizedPhrase(candidate="milk 1 gal", confidence=0.95, raw={})

    monkeypatch.setattr(supervisor_mod, "lemonade_normalize", fake_lemonade_normalize)

    sv = Supervisor(event_log, cfg)
    # Input that the deterministic catalog cannot match — forces the
    # supervisor down the normalizer branch.
    sv.handle_text("white moo juice")

    events = event_log.read_all()
    proposal_events = [e for e in events if e.type == proposals.EVENT_TYPE]
    cart_add_events = [e for e in events if e.type == "cart.add"]

    assert len(proposal_events) == 1
    assert len(cart_add_events) == 1

    prop_did = proposal_events[0].payload.get("delegation_id")
    cart_did = cart_add_events[0].payload.get("delegation_id")

    assert prop_did is not None, "proposal must carry delegation_id"
    assert cart_did is not None, "model-mediated cart.add must carry delegation_id"
    assert _UUID_HEX_RE.match(prop_did), f"delegation_id must be 32 hex: {prop_did!r}"
    assert prop_did == cart_did, "same delegation_id on cause and effect"


def test_deterministic_cart_add_has_no_delegation_id(seeded_db: Path, event_log):
    """A pure-deterministic cart.add (no model crossed) carries no
    delegation_id. The schema is *optional* and only present when a
    delegation actually happened. This keeps deterministic receipts
    free of spurious UUID noise.
    """

    sv = Supervisor(event_log, SupervisorConfig())
    sv.handle_text("apple")  # exact alias hit; no model call

    cart_add_events = [e for e in event_log.read_all() if e.type == "cart.add"]
    assert len(cart_add_events) == 1
    assert "delegation_id" not in cart_add_events[0].payload


def test_two_consecutive_model_calls_get_distinct_delegation_ids(
    seeded_db: Path, event_log, monkeypatch: pytest.MonkeyPatch
):
    """Each handle_text() that crosses the model mints a fresh
    delegation_id; the supervisor does not accidentally reuse one
    across decisions.
    """

    from lemonade_cashier.agents import supervisor as supervisor_mod

    cfg = SupervisorConfig(
        lemonade=LemonadeConfig(enabled=True, url="http://127.0.0.1:8000", model="qwen3:4b"),
        flm=FLMConfig(enabled=False),
    )

    def fake_lemonade_normalize(phrase, cart_shape, config):
        if "moo" in phrase:
            return NormalizedPhrase(candidate="milk 1 gal", confidence=0.95, raw={})
        return NormalizedPhrase(candidate="eggs dozen", confidence=0.95, raw={})

    monkeypatch.setattr(supervisor_mod, "lemonade_normalize", fake_lemonade_normalize)

    sv = Supervisor(event_log, cfg)
    # Two distinct un-matchable phrases — each forces a fresh model
    # call and therefore a fresh delegation_id.
    sv.handle_text("white moo juice")
    sv.handle_text("dozen of those oval things")

    proposal_events = [e for e in event_log.read_all() if e.type == proposals.EVENT_TYPE]
    dids = [e.payload.get("delegation_id") for e in proposal_events]
    assert len(dids) == 2
    assert all(d is not None for d in dids)
    assert dids[0] != dids[1], "fresh delegation_id per handle_text"


def test_unreachable_proposal_still_carries_delegation_id(
    seeded_db: Path, event_log, monkeypatch: pytest.MonkeyPatch
):
    """When both normalizers are enabled-but-unreachable, the supervisor
    writes ``unreachable`` proposals. Those events MUST also carry the
    delegation_id of the decision that tried to delegate, so the audit
    chain shows the attempt — not just the silent miss.
    """

    from lemonade_cashier.agents import supervisor as supervisor_mod

    cfg = SupervisorConfig(
        lemonade=LemonadeConfig(enabled=True, url="http://127.0.0.1:8000", model="qwen3:4b"),
        flm=FLMConfig(enabled=True, url="http://127.0.0.1:11434", model="gemma3:1b"),
    )

    monkeypatch.setattr(supervisor_mod, "lemonade_normalize", lambda *a, **kw: None)
    monkeypatch.setattr(supervisor_mod, "flm_normalize", lambda *a, **kw: None)

    sv = Supervisor(event_log, cfg)
    sv.handle_text("zzzcompletely-unknown-phrase-zzz")

    proposal_events = [e for e in event_log.read_all() if e.type == proposals.EVENT_TYPE]
    assert len(proposal_events) == 2  # one unreachable per enabled client
    dids = {e.payload.get("delegation_id") for e in proposal_events}
    assert None not in dids
    assert len(dids) == 1, "both unreachable proposals share the same delegation_id"
