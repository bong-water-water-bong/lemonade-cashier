# Project Wiki: Lemonade Cashier

## Mission
Build a local-first, offline-capable cashier assistant with a deterministic financial core. It prioritizes reliability and auditable cash transactions over autonomous agent features.

## Architecture
- **Deterministic Core**: The "pure" financial logic (Inventory -> Cart -> Totals -> Cash -> Receipts -> Audit) is written in stdlib-only Python.
- **Event-Sourced**: State is a function of events (`replay(events) -> state`). The event log is append-only and hash-chained.
- **Agent Supervisor**: A multi-agent layer with strict permission states (e.g., `attendant` vs. `agent_auto`). Agents can only propose events; they cannot authorize them.
- **Graceful Fallback**: Optional AI-assisted parsing (via Lemonade Server or FastFlowLM) degrades to rule-based parsing if the models are unreachable.

## Agent Handoff
- **How to Test**: 
    - `make test`: Runs the full suite.
    - `make seed`: Seeds the local SQLite product database from CSV.
    - `make run`: Launches the CLI for manual testing.
- **Hot Paths**:
    - `src/lemonade_cashier/core/`: The "Pure" financial core (Money, Inventory, Cart).
    - `src/lemonade_cashier/audit/`: Event log and replay logic.
    - `src/lemonade_cashier/agents/`: Supervisor and LLM client implementations.
- **Current Priorities**: 
    - Phase 1.5: Finalizing the LLM-assisted parser fallback.
    - Maintaining the "reliable before autonomous" boundary.

## Decisions & Gotchas
- **Money is `Decimal`**: Never use `float` for currency calculations. CI enforces this.
- **Cash-Only Core**: The system is built for cash tender and CIT (Cash-In-Transit) custody. External payment providers are strictly optional plugins.
- **No I/O in Core**: The financial core is pure; all side effects live in the audit/receipt layers.
- **Timeout-First AI**: Any agent path must have a "Lemonade unreachable" test to ensure the UI never hangs on a model spinner.
- **PIN Security**: Supervisor-level actions (voids, large refunds) require a PIN hashed with PBKDF2-SHA256.

## OpenSpec Workflow

Use `openspec/` as the working standard for department changes:

- `openspec/project.md` defines this repo's department workflow.
- `openspec/specs/cashier/spec.md` records the active contract for this department.
- `openspec/changes/<change-id>/` holds proposal, design, and task files for active work.
- GitHub issues and PRs must name affected event types and approval gates.

Keep this repo aligned with `lemonade-store` when event contracts, owner approval gates, or department boundaries change.

## LLM Wiki Standard

This repo treats Andrej Karpathy's LLM Wiki pattern as the governing source for agent knowledge management: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

For this project, that means:

- `docs/wiki/` is the maintained project memory for architecture, decisions, gotchas, and onboarding.
- `AGENTS.md` is the agent instruction schema.
- `openspec/` is the structured change/spec layer.
- Raw source material stays in docs, examples, tests, issue/PR discussions, and committed specs.
- Agents must update the wiki when they learn durable repo knowledge that future agents need.

Keep wiki entries concise, factual, and linked back to concrete files, specs, or test evidence.
