# Financial Core

> The stdlib-only engine that handles all money math and event sourcing — isolated from every third-party dependency by design.

## Overview
`src/lemonade_cashier/core/` is the blast-radius-zero zone. No third-party imports are allowed. This boundary ensures that a broken dependency, a network call, or an AI model failure cannot corrupt financial calculations or event data.

## How It Works
All monetary values enter as strings or `Decimal`. All intermediate math stays at 4 decimal places. Quantization to 2dp happens only at display/output edges (CLI, receipt). The core never touches the filesystem, never makes network calls, and never reads from AI models.

## Key Decisions
- **Why no I/O in core**: Any I/O in the core creates a failure surface that could block or corrupt a sale. The core must be pure functions over data.
- **Why 4dp intermediate, 2dp output**: Avoids accumulated rounding error across a multi-item session while presenting clean currency values to users.

## Gotchas
- Running `import requests` or any non-stdlib package inside `core/` violates the isolation boundary. This is enforced by code review, not by CI tooling — no linter rule currently blocks it. The convention is real; the automation is not.
- `Decimal('1.1') != Decimal(1.1)` — always construct from strings, never from float literals.

## Related
- [[architecture]] — where core fits in the overall system
- [[audit-log]] — core produces events, audit log consumes them
