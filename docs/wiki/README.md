# Lemonade Cashier — Wiki

> Local-first POS assistant with a deterministic financial core, append-only audit log, and optional offline AI fallbacks. Reliability comes before autonomy.

## Current State
Core financial path is stable. Agents (Lemonade/FLM/GAIA) integrated as fallback parsers. Audit log with hash-chaining and replay is live. Vision pipeline sensors are stubbed — wiring to `lemonade-vision-server` is the active work thread.

## Start Here
- [[architecture]] — read this first. Explains the core/agents/audit separation that shapes every decision.
- [[financial-core]] — if touching anything in `src/lemonade_cashier/core/`
- [[audit-log]] — if adding a new event type (read before writing any producer code)
- [[agent-model]] — if touching `agents/` or `integrations/`

## Open Threads
- Vision pipeline integration: `sensors.*` stubs need wiring to `lemonade-vision-server` HTTP API — see `docs/VISION_PIPELINE.md` for contract
- CIT (Cash-in-Transit) phase is next after vision pipeline — see `docs/SAFETY.md` for scope

## Hard Rules (non-negotiable)
- `core/` is stdlib-only. No third-party imports. Ever.
- No `float` for money. `Decimal` everywhere.
- Every new event type needs replay coverage before the producer is written.
- Agents return `None` on timeout — never raise, never block the register.

## Article Index
| Article | What it covers |
|---------|----------------|
| [[architecture]] | System shape, layer separation, data flow |
| [[financial-core]] | stdlib-only core, Decimal math, isolation boundary |
| [[audit-log]] | JSONL event log, hash chaining, replay, projections |
| [[agent-model]] | Agent identity, delegation, fallback model, timeouts |
