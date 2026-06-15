# Project Wiki: Lemonade Cashier

## Mission
Build a local-first, offline-capable cashier assistant with a deterministic financial core. It prioritizes reliability and auditable cash transactions over autonomous agent features.

## Architecture
- **Deterministic Core**: Core logic (Inventory -> Cart -> Totals -> Cash) is defined under [core/](../../src/lemonade_cashier/core) using standard library Python only.
  > [!NOTE]
  > While Cart, Totals, and Money are strictly pure and side-effect-free, [inventory.py](../../src/lemonade_cashier/core/inventory.py) performs local SQLite queries and CSV file seeding for local catalog initialization.
- **Event-Sourced & Audited**: Receipts and event replay logic live under [audit/](../../src/lemonade_cashier/audit). State is derived as a function of events (`replay(events) -> state`) logged to an append-only, hash-chained file.
- **Agent Supervisor**: A multi-agent layer wraps the deterministic commands. In the current CLI prototype, agents propose events, but final authorization is processed under a single attendant session authority (see [agents.md](agents.md)). High-confidence agent proposals (confidence $\ge 0.8$) are auto-applied directly.
- **Graceful Fallback**: Optional AI-assisted parsing (via Lemonade Server or FastFlowLM) degrades to rule-based parsing if the models are unreachable.

## Agent Handoff
- **How to Test**: 
    - `make test`: Runs the full unit test suite.
    - `make seed`: Seeds the SQLite database [products.db](../../data/products.db) from [sample_products.csv](../../data/sample_products.csv).
    - `make run`: Launches the CLI for manual testing.
- **Hot Paths**:
    - `src/lemonade_cashier/core/`: The stdlib-only financial core packages (Money, Cart, and SQLite/CSV-backed Inventory catalog).
    - `src/lemonade_cashier/audit/`: Append-only event logging, hash-chain checks, and receipts.
    - `src/lemonade_cashier/agents/`: Supervisor orchestration and LLM client handlers.
- **Current Priorities**: 
    - Finalizing LLM-assisted parser fallbacks under the "reliable before autonomous" boundary (modeled conceptually as Phase 1.5 in draft plans).

## Decisions & Gotchas
- **Money is `Decimal`**: Never use `float` for currency calculations. This is programmatically checked in CI via [test_no_float_money_in_core](../../tests/test_money.py#L71).
- **Bankers' Rounding**: Banker's rounding (`ROUND_HALF_EVEN`) is used as standard for financial calculations (the default behavior of python `round()` / IEEE 754).
- **Cash-Only Core**: Designed for local cash tender and CIT (Cash-In-Transit) custody. External payment gateways are out of scope for the core.
- **Pure Domain Boundary**: Financial math remains free of network dependency. While the catalog database is read in `inventory.py`, all core cart mutations are side-effect-free.
- **Timeout-First AI**: All AI/LLM client operations have a hard 2.0s timeout. Handled and verified in tests like [test_supervisor.py](../../tests/test_supervisor.py) (e.g. `test_supervisor_unreachable_writes_proposal`).
- **PIN Security**: Supervisor actions require a PIN hashed with `PBKDF2-HMAC-SHA256` using 200,000 iterations (conforming to the [OWASP Cheat Sheet Series minimum](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#pbkdf2)) as implemented in [pins.py](../../src/lemonade_cashier/safety/pins.py).
- **Packaging Boundary**: The base `lemonade-cashier` package has no runtime dependencies. External agent bridge packages such as `lemonade-agents`, GAIA, and Torch belong behind the optional `agents` extra so `make install` and deterministic tests stay lightweight. The Makefile creates `.venv` for local development and prefers it for checks when present.

## OpenSpec Workflow

Use `openspec/` as the working standard for department changes:

- `openspec/project.md` defines this repo's department workflow.
- `openspec/specs/cashier/spec.md` records the active contract for this department.
- `openspec/changes/<change-id>/` holds proposal, design, and task files.
  > [!NOTE]
  > The `changes/` subdirectory is created dynamically for active proposal branches and is not pre-populated in the main branch.
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

## Wiki Pages

- [README](README.md) — Main entry point and cashier overview.
- [architecture](architecture.md) — High-level cashier architecture, component boundaries, and event pipeline design.
- [conventions](conventions.md) — PEP 8 standards, mypy strict configurations, standard library core constraints, and Decimal math conventions.
- [runbook](runbook.md) — Local Makefiles, port assignments, and configuration environment variables.
- [agents](agents.md) — Safety guidelines, supervisor override PIN thresholds, and actor permissions.
- [agent-model](agent-model.md) — Conceptual model of fallback parsers, live inference logs, and delegation tracking.
- [financial-core](financial-core.md) — Deterministic, stdlib-only financial calculation ring details.
- [audit-log](audit-log.md) — Append-only, hash-chained JSONL event logging and projection replaying.
