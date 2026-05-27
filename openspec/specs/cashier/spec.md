# Cashier Department Spec

Status: active
Department repo: `lemonade-cashier`
Suite registry: `lemonade-store/src/lemonade_store/departments.py`

## Namespace

`cashier.*`

## Owns

deterministic checkout, product matching, cart state, totals, cash tender, change, receipts, CIT custody, replay, and attendant-approved barter records.

## Consumes

inventory.created, inventory.adjusted, inventory.category.updated.

## Emits

cashier.transaction.opened, cashier.transaction.line_added, cashier.transaction.line_voided, cashier.transaction.closed, cashier.cit.*, cashier.barter.recorded.

## Owner Approval

normal cash checkout does not require owner approval; barter, refunds, voids, discounts, and CIT thresholds follow cashier policy.

## Must Not

card processors, social posting, public website deploys, full accounting ownership, or inventory ownership.

## Change Rules

- Changes to consumed/emitted events must be reflected in `lemonade-store`.
- Event-shape changes must include examples and tests in this repo.
- Public, financial, deployment, export, publish, and purchase-order side effects must remain owner-gated.
