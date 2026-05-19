# Security Policy

Lemonade Cashier is local-first cashier software. Security reports should focus
on bugs that could change money, hide audit history, bypass attendant policy, or
expose local credentials.

## Supported Versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

## Reporting a Vulnerability

Please report vulnerabilities privately through GitHub Security Advisories:

https://github.com/bong-water-water-bong/lemonade-cashier/security/advisories/new

Do not open public issues for suspected security bugs. Include:

- A short description of the issue.
- Steps to reproduce it locally.
- The affected version or commit.
- Whether the bug can alter totals, receipts, PIN policy, or the event log.

## Response Targets

The maintainer target is:

- Acknowledge the report within 7 days.
- Fix or publish a workaround within 30 days for critical issues.
- Fix or publish a workaround within 90 days for other accepted issues.

These are targets, not a paid support SLA.

## In Scope

Reports are in scope when they affect this repository's own cashier behavior:

- Deterministic financial core: inventory, cart, totals, cash, and receipts.
- Append-only hash-chained JSONL event log and replay.
- PIN store, lockout, policy gates, and attendant risk profile.
- Cash-in-transit flow, including bag lifecycle and witness rules.
- Local agent fallback paths that could bypass deterministic validation.

## Out of Scope

Please report upstream issues to their own projects:

- Lemonade Server.
- FastFlowLM.
- GAIA.
- Operating system, browser, GitHub, Python, SQLite, or dependency issues that
  are not caused by Lemonade Cashier code.

## Top-Severity Invariant

The hash-chained event log is the source of truth. Any vulnerability that allows
silent tampering, deletion, reordering, or substitution of event-log entries
without detection is treated as top severity, even if it does not immediately
change the visible cart total.

## Non-Goals

This project does not process real payments, store card data, or persist
customer audio or images. Reports about payment processor compliance or raw
media retention are out of scope until those features exist.
