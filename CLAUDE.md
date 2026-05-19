# CLAUDE.md - conventions for Lemonade Cashier

Local-first cashier assistant with a deterministic financial core, append-only
audit log, and optional offline agent fallbacks. Reliability comes before
autonomy.

## Hard Rules

- **Rule A: Core financial path is stdlib-only.** `core/` imports nothing
  third-party. Keep I/O, model calls, clocks, and filesystem writes outside the
  core.
- **Rule B: No `float` for money.** Use `Decimal` everywhere for monetary
  values. Keep intermediate money math at 4 decimal places and quantize display
  output at the edge.
- **Rule C: The hash-chained JSONL event log is the source of truth.** Receipts
  and live state are projections. Any new event type needs replay coverage.
- **Rule D: Agents are fallback parsers only.** They are never authoritative for
  SKU or price. The deterministic parser at `agents/parser.py` is primary.
- **Rule E: Lemonade, FastFlowLM, and GAIA calls have hard timeouts.** The
  default timeout is 2 seconds. Network failures return `None`; they do not
  raise through the cashier path.
- **Rule F: Sensor layers are interface-only for now.** `camera/`, `speech/`,
  and `fusion/` must not become price or SKU authorities.

## Build Order

```text
inventory -> cart -> totals -> cash -> receipts -> audit -> replay
        -> CIT -> safety -> agents -> cameras -> speech -> sensor fusion
```

Ten of thirteen layers are shipped on `main` as of `686a886`. Do not skip ahead
of this order without a clear reason and tests.

## Test / Verify

```sh
make all
```

`make all` runs lint, type checks, and tests. Use the narrower targets while
iterating:

```sh
make lint
make type
make test
```

## Commits

Use Conventional Commits: `feat`, `fix`, `perf`, `docs`, `refactor`, `build`,
`ci`, `chore`, or `test`. Keep one logical change per commit.

## Branching

Branch from `main`, avoid direct pushes to `main`, squash-merge PRs, and delete
the branch after merge.

## Stacked-PR Lesson

When a base branch is squash-merged and deleted, a stacked PR can auto-close.
Rescue it with:

```sh
git rebase --onto origin/main <old-base-tip> <branch>
```

## What NOT To Do

- Do not add `float` for money.
- Do not mock the database in tests when the SQLite path is the behavior under
  test.
- Do not bypass the event log.
- Do not make agents authoritative for SKU, price, voids, refunds, or closing a
  transaction.
- Do not add production payment processing.
- Do not persist customer audio or images.
- Do not file upstream bugs for Lemonade, FastFlowLM, or GAIA from this repo;
  patch locally or isolate the integration behavior here.

## Memory

Project memory lives at:

```text
~/.claude/projects/-home-bcloud/memory/lemonade-cashier-project.md
```

The Phase 1 vision pipeline note is mirrored at:

```text
~/.claude/projects/-home-bcloud-Projects/memory/project-vision-pipeline.md
```
