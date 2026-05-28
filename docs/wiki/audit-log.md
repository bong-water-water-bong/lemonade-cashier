# Audit Log

> The hash-chained JSONL event log — the single source of truth for all cashier state.

## Overview
All cashier state is derived from an append-only JSONL event log. Receipts, totals, and session state are projections computed by replaying the log. Nothing is stored directly — only events are persisted.

## How It Works
Each event is a JSON object appended to the log file. Each event includes a hash of the previous event, forming a chain. Tampering with any event breaks the chain and is detected on replay.

**Event lifecycle:**
1. Core produces an event (e.g., `ItemScanned`, `PaymentApplied`)
2. Event is hashed with the previous event's hash
3. Appended to the JSONL log atomically
4. State projections are recomputed from the new tail

## Key Decisions
- **Why append-only**: Mutation would require locking and could corrupt state mid-write. Append is atomic on most filesystems for small writes.
- **Why hash-chaining**: Provides tamper detection without a database. A corrupted log is detectable before it causes incorrect financial reporting.
- **Why projections not stored state**: Stored state can diverge from the log. Projections are always consistent with the log by definition.

## Gotchas
- Every new event type needs a replay handler in `audit/replay.py`. Add the handler before the event producer — TDD.
- Log rotation must preserve the chain — the last hash of the rotated log must be the first hash reference of the new log. (Log rotation is not yet implemented; this is a design constraint for when it is.)
- Never delete or truncate the log to "fix" a problem. Replay from genesis is always possible and is the correct recovery path.

## Related
- [architecture](architecture.md) — audit log in context
- [financial-core](financial-core.md) — produces the events the log stores
