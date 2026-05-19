# Contributing to Lemonade Cashier

Thanks for the interest. The cashier is a small, opinionated project. Reading this once is enough to land good PRs.

## Ground rules

1. **Reliability before autonomy.** Every change that increases the cashier's autonomy must increase its testability by the same amount. New behavior → new regression test.
2. **The financial core is stdlib-only.** `src/lemonade_cashier/core/` must not import third-party packages. `tests/test_money.py::test_no_float_money_in_core` enforces no `float` for money values.
3. **The hash-chained JSONL event log is the source of truth.** Receipts and live state are *projections*. If a behavior needs to be durable, it needs an event, not just an in-memory side effect.
4. **Agents are fallback parsers only.** Never authoritative for SKU or price. The rule-based parser at `src/lemonade_cashier/agents/parser.py` is primary.
5. **Money math runs at 4 decimal places.** Tests that assert money values must use 4dp literals (e.g. `Decimal("400.1700")`, not `Decimal("400.17")`).
6. **Match the literal ask.** Don't expand scope, refactor opportunistically, or add abstractions for future features.

For the full machine-readable convention set, see [`CLAUDE.md`](CLAUDE.md).

## Local setup

```bash
git clone https://github.com/bong-water-water-bong/lemonade-cashier.git
cd lemonade-cashier

# Editable install with dev extras (pytest, ruff, mypy).
make install

# Or, manually:
python -m pip install -e ".[dev]"

# Seed the local product database from data/sample_products.csv
make seed

# Start the cashier CLI
make run
```

Requires Python ≥ 3.11. The cashier's runtime core has no third-party dependencies; the dev extras only install test and lint tooling.

## Running checks

`make all` runs the full pre-PR triple:

```bash
make lint   # ruff check + ruff format --check
make type   # mypy --strict
make test   # pytest (185+ tests; runs in under 10 seconds)
```

CI runs the same three on every PR across Python 3.11 / 3.12 / 3.13.

## Branching and commits

- Branch from `main`. Don't push directly to `main` — open a PR.
- Commits follow **Conventional Commits**: `feat`, `fix`, `perf`, `docs`, `refactor`, `build`, `ci`, `chore`, `test`. The PR squash-merge message is what lands on `main`, so PR titles should also follow the convention.
- One logical change per commit / PR. If you find yourself bundling unrelated work, split it.
- PRs against `main` are auto-reviewed by **CodeRabbit** and **Qodo**. Address blocking findings as a follow-up commit; the bot will re-review on push.

## What gets PRs merged

A PR lands when:

1. ✅ CI is green on all three Python versions.
2. ✅ CodeRabbit has "No actionable comments" or all comments are resolved.
3. ✅ Qodo reports zero unresolved bugs / rule violations.
4. ✅ A CODEOWNER has approved.
5. ✅ Branch is up to date with `main` (squash-merge, no merge commits).

If you're a first-time contributor, expect more conversation on the first PR. Subsequent PRs go faster.

## Stacked-PR lesson

If your PR is based on another open PR's branch (a *stacked* PR), and the base PR gets squash-merged-and-deleted, your stacked PR will auto-close. To rescue it:

```bash
git fetch origin
git rebase --onto origin/main <old-base-tip> <branch>
git push --force-with-lease origin <branch>
# Open a fresh PR against main; the old one stays closed.
```

This is non-negotiable because the project uses squash-merge, which produces a new SHA on `main`.

## Architecture entry points

| File | What it owns |
|---|---|
| `src/lemonade_cashier/core/inventory.py` | SKU/alias matching, CSV seeding, SQLite |
| `src/lemonade_cashier/core/cart.py` | Quantity, subtotal, refunds |
| `src/lemonade_cashier/core/cash.py` | Tender, change, denomination math |
| `src/lemonade_cashier/audit/eventlog.py` | Append-only JSONL + hash chain |
| `src/lemonade_cashier/audit/replay.py` | Pure-function replay of any closed transaction |
| `src/lemonade_cashier/safety/` | PIN store, lockout, profile, tamper, EOS report, bags |
| `src/lemonade_cashier/agents/parser.py` | Deterministic primary parser |
| `src/lemonade_cashier/agents/supervisor.py` | Top-level state machine |
| `docs/BUILD_ORDER.md` | The 13-layer build order — read before touching `sensors.*` |

## Security

Found a vulnerability? **Do not** open a public issue. Use the [private security advisory](https://github.com/bong-water-water-bong/lemonade-cashier/security/advisories/new) instead. See [`SECURITY.md`](SECURITY.md).

## Questions

- Discussion / design conversation → [GitHub Discussions](https://github.com/bong-water-water-bong/lemonade-cashier/discussions)
- Bugs → [Issues](https://github.com/bong-water-water-bong/lemonade-cashier/issues/new/choose)
- Security → [Advisory](https://github.com/bong-water-water-bong/lemonade-cashier/security/advisories/new)
