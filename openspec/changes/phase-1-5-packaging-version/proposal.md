# Change Proposal: phase-1-5-packaging-version

## Department

- Department: cashier
- Repo: lemonade-cashier
- Namespace: cashier.*

## Why

The README describes the repository as the Phase 1.5 drop, but package
metadata still reported `0.1.0`. The base package also depended directly
on `lemonade-agents`, which pulls GAIA/Torch dependencies into a normal
cashier install even though the deterministic cashier and local Lemonade
HTTP fallback do not need third-party runtime packages.

## What Changes

- Align package and module version metadata with Phase 1.5 as `1.5.0`.
- Move `lemonade-agents` from required dependencies to the optional
  `agents` extra.
- Teach the Makefile to create and prefer `.venv` for local development.
- Document the base install versus optional external agent bridge install.

## Affected Events

- Consumes: none
- Emits: none

## Approval Gates

- Owner approval required: no
- Approval type: packaging/docs cleanup; no cashier event contract change

## Boundaries

- Reads: package metadata, README, changelog, wiki
- Writes: package metadata, README, changelog, wiki, OpenSpec change record
- Must not touch: financial core behavior, event schemas, replay semantics

## Verification

- [x] `make test`, `make lint`, `make type`
- [x] Examples/docs updated if event contracts changed
- [x] `lemonade-store` registry/docs updated if department boundary changed
