<!-- One PR per logical change. Match the project's Conventional Commits scope. -->

## Summary

<!-- 1-3 bullets describing what changed and why -->

## Why

<!-- Link the motivation: bug, design doc, issue, conversation. -->

Closes #
Refs #

## Scope check

- [ ] One logical change (no opportunistic refactors)
- [ ] Stays inside the existing build-order layer
- [ ] No changes to `src/lemonade_cashier/core/` deps (must remain stdlib-only)
- [ ] Money math uses `Decimal`; no `float`
- [ ] Event log is still the source of truth (no in-memory shortcuts)
- [ ] Agents stay fallback parsers — never authoritative for SKU or price

## Tests

- [ ] New behavior covered by a regression test
- [ ] Money-math changes have 4-decimal expected values
- [ ] `make all` passes locally (`lint type test`)

## Reviewer notes

<!-- Anything specific you want eyes on: tradeoffs, alternatives rejected, follow-ups deferred. -->
