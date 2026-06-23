# GitHub Copilot Instructions — Lemonade Cashier

Part of the Lemonade Store suite: offline-first, cash-only retail OS for ma-and-pa shops.
Communicates via `store.event.v1` events. See `lemonade-store` for contracts.

## Hard rules
1. Cash-only core. No Stripe/card readers/wallets/payment gateways.
2. Cashier is source of truth for checkout.
3. Local-first. Cloud for public website only.
4. Owner approval gates public/financial side effects.
5. No customer card data, audio, or images.
6. `store.event.v1` envelope is the contract.
7. No third-party runtime deps beyond `lemonade-store`.

## Coding
- Python 3.11+. `from __future__ import annotations` everywhere.
- Ruff (line-length=100). Mypy strict. Dataclasses frozen=True.
- Money is Decimal. No floats. Agents draft; humans approve.
- Event IDs deterministic (SHA-256). Include tests with new code.
