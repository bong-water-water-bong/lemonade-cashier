"""Read-only Q&A agent.

Answers attendant questions ("what was my last big void?", "what's
the cash on hand?") from the event log using a local Lemonade or
FastFlowLM endpoint. By contract, the Q&A agent:

* Reads the cart, till, bag, and profile state via the safety/audit
  modules — never the raw event payload.
* Emits a single ``agent.proposal`` event of kind ``chat_response``,
  with the question as ``input`` and the model's text reply as
  ``output``.
* Has **no cart-mutating capability** — see :mod:`agents.registry`.
  The registry denies ``normalize`` for ``"qa"``, so even if a bug
  let the Q&A path try to add a SKU, the proposal emitter would
  refuse.
* Returns ``None`` on any failure (LLM unreachable, capability
  violation, malformed response). Callers must degrade gracefully —
  the cashier never *needs* the Q&A agent to function.

The model sees the cart state and the question, **but no PIN store,
no token, no attendant ID beyond a short string label**. The
:mod:`agents.gaia_bridge` deny-list already encodes the rules; we
explicitly construct the context dict here to make the constraint
local to this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..audit.eventlog import EventLog
from ..safety.report import build as build_report
from . import proposals, registry
from .lemonade_client import LemonadeConfig, chat_completions

SYSTEM_PROMPT = (
    "You are the read-only assistant for a cashier. Answer ONLY using "
    "the JSON state provided. Do not invent SKUs, prices, attendant "
    "names, or PINs. If the answer isn't in the state, say so. Keep "
    "answers under 2 sentences, plain text, no markdown."
)

MAX_ANSWER_CHARS = 800


@dataclass(frozen=True)
class QAAnswer:
    question: str
    answer: str
    confidence: float


def ask(
    log: EventLog,
    question: str,
    *,
    config: LemonadeConfig,
) -> QAAnswer | None:
    """Ask the Q&A agent a question. Returns ``None`` if disabled,
    unreachable, or capability-violating."""

    cleaned = question.strip()
    if not cleaned:
        return None
    if not config.enabled:
        return None

    # Capability check up front. If "qa" is ever accidentally allowed
    # to emit normalize proposals, the check fails loudly here.
    try:
        registry.assert_can_emit("qa", "chat_response")
    except registry.CapabilityError:
        return None

    # Build the read-only context the model sees. Includes cart/till/
    # bag/profile state but NOT raw event payloads (PIN-failure
    # events, attendant identifiers we don't want to expose in detail).
    state = build_report(log).state
    safe_state = _trim_for_model(state)

    # Call the SHARED chat-completions transport with the Q&A's OWN
    # system prompt. The earlier version routed through normalize(),
    # which hard-codes the cart-normalizer's "produce a product
    # phrase" prompt — meaning the Q&A agent received the wrong
    # instructions and produced product fragments as "answers".
    content = chat_completions(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps({"question": cleaned, "state": safe_state}, default=str),
            },
        ],
        config=config,
    )
    if content is None:
        proposals.write(
            log,
            agent="qa",
            kind="chat_response",
            input={"question": cleaned},
            output=None,
            confidence=0.0,
            decision="unreachable",
        )
        return None

    answer_text = str(content).strip()[:MAX_ANSWER_CHARS]
    if not answer_text:
        # Model returned something that stripped to empty — record
        # the rejection so the chain shows the agent tried (and
        # failed) to produce a useful answer.
        proposals.write(
            log,
            agent="qa",
            kind="chat_response",
            input={"question": cleaned},
            output=None,
            confidence=0.0,
            decision="rejected",
        )
        return None

    # No native confidence channel; record an inferred mid-confidence
    # value. A more elaborate setup could ask the model to self-rate.
    inferred_confidence = 0.6

    proposals.write(
        log,
        agent="qa",
        kind="chat_response",
        input={"question": cleaned},
        output={"answer": answer_text},
        confidence=inferred_confidence,
        decision="accepted",
    )
    return QAAnswer(
        question=cleaned,
        answer=answer_text,
        confidence=inferred_confidence,
    )


def _trim_for_model(state: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``state`` with operator-only fields stripped.

    Specifically removes:
    * ``log_path`` — local filesystem detail the model doesn't need.
    * ``tamper_findings`` — investigators read these directly; the
      model's "summary" of a security finding is more noise than
      signal.
    * Per-attendant ``pin_failures`` counts — the model should answer
      questions about transactions, not PIN attempts.
    """

    trimmed = dict(state)
    trimmed.pop("log_path", None)
    trimmed.pop("tamper_findings", None)
    attendants = trimmed.get("attendants")
    if isinstance(attendants, dict):
        cleaned: dict[str, Any] = {}
        for actor, profile in attendants.items():
            if isinstance(profile, dict):
                clean_profile = {k: v for k, v in profile.items() if k != "pin_failures"}
                cleaned[actor] = clean_profile
        trimmed["attendants"] = cleaned
    return trimmed


__all__ = ["SYSTEM_PROMPT", "QAAnswer", "ask"]
