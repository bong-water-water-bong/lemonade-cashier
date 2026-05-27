# lemonade-cashier OpenSpec Standard

Status: active
Department: `cashier`
Namespace: `cashier.*`
Suite registry: `lemonade-store/src/lemonade_store/departments.py`

## Purpose

This folder is the working spec layer for the `cashier` department. It keeps changes organized before code is written, reviewed, packaged, or sent across department boundaries.

## Required Flow

1. Start with a change under `openspec/changes/<change-id>/`.
2. Write `proposal.md` before implementation.
3. Add `design.md` when the change affects event contracts, storage, permissions, packaging, public behavior, or another department.
4. Break implementation into `tasks.md`.
5. Update `openspec/specs/cashier/spec.md` when this department contract changes.
6. Run `make test`, `make lint`, `make type` before marking a change ready.
7. Owner approval is required for public, financial, deployment, export, publish, or purchase-order side effects.

## Department Contract

- Owns: deterministic checkout, product matching, cart state, totals, cash tender, change, receipts, CIT custody, replay, and attendant-approved barter records.
- Consumes: inventory.created, inventory.adjusted, inventory.category.updated.
- Emits: cashier.transaction.opened, cashier.transaction.line_added, cashier.transaction.line_voided, cashier.transaction.closed, cashier.cit.*, cashier.barter.recorded.
- Approval: normal cash checkout does not require owner approval; barter, refunds, voids, discounts, and CIT thresholds follow cashier policy.
- Must not: card processors, social posting, public website deploys, full accounting ownership, or inventory ownership.

## Alignment Rule

When consumed/emitted events or approval gates change, update this repo and `lemonade-store` in the same PR cycle.

## Source Pattern

This OpenSpec standard treats Karpathy's LLM Wiki pattern as the governing source for agent knowledge management: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

- Raw source: repo files, examples, tests, issue/PR context, and department specs.
- Wiki: `docs/wiki/` summarizes durable knowledge for future agents.
- Schema: `AGENTS.md`, GitHub templates, and `openspec/` define how work is proposed, executed, verified, and reviewed.
# OpenSpec Project Standard

Status: active
Source pattern: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

## Purpose

This folder is the structured change/spec layer for this repository. It exists so agents and humans agree on intent, design, tasks, and verification before making broad changes.

## Required Flow

1. For non-trivial work, create `openspec/changes/<change-id>/`.
2. Write `proposal.md` first: why, what changes, risk, and verification.
3. Add `design.md` when architecture, storage, permissions, public behavior, or cross-repo contracts change.
4. Track implementation in `tasks.md` and keep task state current.
5. Update `docs/wiki/` with durable architecture, workflow, gotcha, or onboarding knowledge.
6. Verify with this repo's native tests/checks before marking work ready.

## Memory Model

- Raw source: committed files, examples, tests, issues, PRs, and specs.
- Wiki: `docs/wiki/` durable project memory.
- Schema: `AGENTS.md`, GitHub templates, and `openspec/`.

## Guardrails

- Prefer small, reversible changes.
- Do not overwrite existing project-specific rules.
- Do not add speculative frameworks or broad refactors.
- Record assumptions and verification.
