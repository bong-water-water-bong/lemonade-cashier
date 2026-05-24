# Agent Model

> Agents are fallback parsers, not authorities — they assist the deterministic core, never replace it.

## Overview
Cashier's agent layer wraps Lemonade, FastFlowLM, and GAIA. Agents are invoked only when the deterministic parser at `agents/parser.py` fails to resolve an input. They are never the primary path for SKU lookup or price determination.

## How It Works
```
Input → deterministic parser → resolved? → yes: use it
                             → no: invoke LLM agent with 2s timeout
                                         → resolved? → yes: use it, log inference
                                                     → no: return None, prompt operator
```

Agent identity and delegation are tracked per-session for audit purposes. Each agent call is logged with its confidence, model used, and whether it was overridden by the operator.

## Key Decisions
- **Why deterministic parser is primary**: LLM agents have latency, token limits, and hallucination risk. A POS system cannot block at the register waiting for a model response.
- **Why 2-second hard timeout**: Any agent call exceeding 2s becomes a UX failure. `None` + operator fallback is always correct; a stalled agent is never correct.
- **Why log agent inferences**: Audit trail requires knowing when a price or SKU came from an agent vs. the deterministic path. This feeds into reconciliation and dispute resolution.

## Gotchas
- delegation-id is minted per-call when an LLM is invoked — it is not a session-level initialization. Deterministic paths produce no delegation-id, and that is correct. Do not add session-level delegation-id initialization; look at `agents/supervisor.py` for the actual minting logic.
- GAIA requires the desktop process running. In CI, mock at `agents/gaia_bridge.py` — `integrations/gaia.py` does not exist.
- Agent responses for price are advisory only. The operator must confirm before a non-catalog price is accepted.

## Related
- [[architecture]] — agents in the full system context
- [[financial-core]] — the deterministic layer agents augment
