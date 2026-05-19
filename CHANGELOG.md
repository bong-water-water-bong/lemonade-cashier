# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-19

### Added

- Inventory, cart, totals, cash, and receipts layers.
- Append-only hash-chained JSONL event log with pure-function replay in
  `src/lemonade_cashier/audit/`.
- Cash-in-transit lifecycle: drops, pickups, till counts, two-person rule, and
  full bag chain-of-custody from sealed to handoff to received to reconciled or
  discrepancy.
- Safety layer: PBKDF2-SHA256 hashed PIN store, per-attendant lockout,
  per-attendant risk profile, clock-skew and quiet-gap tamper detection, and
  end-of-shift reporting.
- Agents layer: multi-agent supervisor, capability registry, agent proposals
  and replay, Q&A agent, summarizer, and security guardrails for cart-state to
  local-LLM calls.
- Regression suite covering the shipped deterministic core, audit, safety, CIT,
  and agent fallback behavior.

### Deferred

- `sensors.camera`, `sensors.speech`, and `sensors.fusion` remain interfaces
  only until the Phase 2 sensor pipeline is implemented.
