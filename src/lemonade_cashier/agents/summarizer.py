"""EOS report → natural-language summary.

Wraps :func:`safety.report.build` with a one-paragraph plain-English
summary from the local LLM. Falls back to a deterministic template
when the LLM is disabled or unreachable so the EOS workflow is *never*
blocked on the model.

The summarizer is presentation only:
* No event payloads are written by the summarizer itself except its
  own ``agent.proposal`` of kind ``summarize``.
* The model sees the trimmed report state (no PIN counts, no tamper
  detail) — same trimming as the Q&A agent.
* Registry-bound: the summarizer can only emit ``summarize``
  proposals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..audit.eventlog import EventLog
from ..safety.report import build as build_report
from . import proposals, registry
from .lemonade_client import LemonadeConfig, normalize as _lemonade_normalize


@dataclass(frozen=True)
class Summary:
    text: str
    source: str  # "model" | "fallback"


def summarize(log: EventLog, *, config: LemonadeConfig) -> Summary:
    """Build the EOS report and return a one-paragraph summary.

    Always returns a :class:`Summary` — the deterministic template is
    used if the model is unavailable. Failing closed would defeat the
    "reliability before autonomy" principle.
    """

    try:
        registry.assert_can_emit("summarizer", "summarize")
    except registry.CapabilityError:
        return Summary(text=_template(build_report(log).state), source="fallback")

    state = build_report(log).state

    if not config.enabled:
        return Summary(text=_template(state), source="fallback")

    # Use the chat client; the prompt asks for one paragraph of plain
    # text. Falls back if the model is unreachable.
    digest = _state_digest(state)
    normalized = _lemonade_normalize(
        digest,
        cart_shape={"items": []},
        config=config,
    )
    if normalized is None or not normalized.candidate.strip():
        proposals.write(
            log,
            agent="summarizer",
            kind="summarize",
            input={"digest": digest},
            output=None,
            confidence=0.0,
            decision="unreachable",
        )
        return Summary(text=_template(state), source="fallback")

    text = normalized.candidate.strip()
    proposals.write(
        log,
        agent="summarizer",
        kind="summarize",
        input={"digest": digest},
        output={"text": text},
        confidence=normalized.confidence,
        decision="accepted",
    )
    return Summary(text=text, source="model")


def _state_digest(state: dict[str, Any]) -> str:
    """One-line digest of the EOS state for the model. Avoids
    overwhelming the context window."""

    totals = state.get("totals", {}) if isinstance(state.get("totals"), dict) else {}
    till = state.get("till", {}) if isinstance(state.get("till"), dict) else {}
    bags = state.get("bags", {}) if isinstance(state.get("bags"), dict) else {}
    return (
        f"shift: txns={totals.get('transactions', 0)}, "
        f"voids={totals.get('voids', 0)}, "
        f"bag_discrepancies={totals.get('bag_discrepancies', 0)}, "
        f"pin_failures={totals.get('pin_failures', 0)}; "
        f"till_cash_on_hand={till.get('cash_on_hand', '0.00')}, "
        f"open_bags={len([b for b in bags.values() if isinstance(b, dict) and b.get('status') not in ('reconciled', 'discrepancy')])}; "
        f"log_verified={state.get('log_verified', True)}"
    )


def _template(state: dict[str, Any]) -> str:
    """Deterministic fallback summary. Plain English, no model."""

    totals = state.get("totals", {}) if isinstance(state.get("totals"), dict) else {}
    till = state.get("till", {}) if isinstance(state.get("till"), dict) else {}
    bags = state.get("bags", {}) if isinstance(state.get("bags"), dict) else {}
    discrepancies = totals.get("bag_discrepancies", 0)
    verb = "OK" if not discrepancies else f"{discrepancies} discrepanc(y/ies)"
    return (
        f"Shift summary: {totals.get('transactions', 0)} transactions, "
        f"{totals.get('voids', 0)} voids, "
        f"{totals.get('pin_failures', 0)} PIN failures. "
        f"Till cash on hand: ${till.get('cash_on_hand', '0.00')}. "
        f"Bags in flight or terminal: {len(bags)}. Bag reconciliation: {verb}. "
        f"Log verification: {'PASSED' if state.get('log_verified', True) else 'FAILED'}."
    )


__all__ = ["Summary", "summarize"]
