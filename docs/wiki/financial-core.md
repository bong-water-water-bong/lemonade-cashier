# Financial Core

> The stdlib-only engine that handles all money math and event sourcing — isolated from every third-party dependency by design.

## Overview
`src/lemonade_cashier/core/` is the blast-radius-zero zone. No third-party imports are allowed. This boundary ensures that a broken dependency, a network call, or an AI model failure cannot corrupt financial calculations or event data.

## How It Works
All monetary values enter as strings or `Decimal`. All intermediate math stays at 4 decimal places. Quantization to 2dp happens only at display/output edges (CLI, receipt). 

Except for [inventory.py](../../src/lemonade_cashier/core/inventory.py) (which initializes and queries the local SQLite database/CSV product catalog), the financial core modules never touch the filesystem, never make network calls, and never read from AI models.

## Key Decisions
- **Why pure logic for Cart & Money**: Keeping calculation logic side-effect-free prevents database write conflicts, network failures, or locking issues from corrupting active cart transactions.
- **Why 4dp intermediate, 2dp output**: Avoids accumulated rounding error across a multi-item session while presenting clean currency values to users.

## Gotchas
- Running `import requests` or any non-stdlib package inside `core/` violates the isolation boundary. This is enforced by code review, and the standard-library constraint is checked by unit tests.
- `Decimal('1.1') != Decimal(1.1)` — always construct from strings, never from float literals.

## Related
- [architecture](architecture.md) — where core fits in the overall system
- [audit-log](audit-log.md) — core produces events, audit log consumes them
