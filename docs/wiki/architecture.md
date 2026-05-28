# Architecture

> Local-first cashier: deterministic financial core with append-only audit log, optional offline agent fallbacks. Reliability over autonomy.

## Overview
Lemonade Cashier is a point-of-sale system built around two hard constraints: financial correctness and offline resilience. The architecture separates the deterministic financial core (stdlib-only, no third-party imports) from the AI-assisted layers (agents, LLM integrations) so that failures in the AI layer cannot corrupt financial data.

## How It Works

```
iPhone/scanner → sensors layer → deterministic parser → financial core → JSONL audit log
                                       ↑ fallback only ↓
                                   LLM agents (Lemonade/FLM/GAIA)
```

**core/**: Stdlib-only. All money math, event sourcing, receipt projection. No I/O, no model calls, no filesystem writes. This boundary is enforced by Rule A.

**agents/**: Fallback parsers only. `agents/parser.py` is the primary deterministic parser. LLM calls happen only when the deterministic path fails. Agents are never authoritative for SKU or price.

**audit/**: Hash-chained JSONL event log. The single source of truth. Receipts and live state are projections derived from replay. Every new event type requires replay coverage.

**sensors/**: Hardware input stubs (`camera.py`, `speech.py`, `fusion.py`). Currently return `None`; will be wired to `lemonade-vision-server` HTTP API.

**integrations/**: Lemonade, FastFlowLM, GAIA calls. All have 2-second hard timeouts. Network failures return `None` — never raise, never block. Includes `lemond_process.py`, a subprocess manager for the local vendored `lemond` binary running on port 13400, configured via `scripts/setup_lemond.sh`.


## Key Decisions
- **Why stdlib-only core**: Any third-party import in `core/` creates a failure mode that can corrupt financial data. The boundary is the only way to guarantee the core never breaks due to a dependency update.
- **Why Decimal not float**: IEEE 754 float arithmetic introduces rounding errors that compound across a session. Monetary values stay at 4dp internally, quantized to 2dp at display edges.
- **Why append-only JSONL**: Immutable event log enables full replay, audit trail, and point-in-time state reconstruction. Receipts are projections — losing the receipt file loses nothing if the log is intact.
- **Why agents are fallback-only**: Agents have latency and failure modes. Making them authoritative for price or SKU would mean a network hiccup could block a sale. Deterministic parser is always primary.
- **Why 2-second timeouts**: POS systems must not block at the register. Any AI call that takes longer than 2s is a UX failure; returning `None` and falling back is always correct.

## Gotchas
- `float` anywhere in money math is a bug. This boundary is enforced by code review, not by CI tooling — the linter does not restrict imports per-directory. Don't rely on automation to catch it.
- Adding a new event type without replay coverage will break `audit/replay.py` — always add replay test first (TDD).
- GAIA calls require the GAIA desktop to be running locally. In tests, mock at `agents/gaia_bridge.py` — not inside `core/`, not at `integrations/gaia.py` (that path does not exist).
- `sensors.*` stubs return `None` until the vision pipeline is wired. Code consuming sensor output must handle `None`.

## Related
- [financial-core](financial-core.md) — the stdlib-only core in detail
- [audit-log](audit-log.md) — event sourcing, hash chaining, replay
- [agent-model](agent-model.md) — how agents fit in, delegation, identity
