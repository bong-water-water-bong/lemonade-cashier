# Build Order

The spec is explicit:

> inventory → cart → totals → cash → receipts → audit → replay → CIT →
> safety → agents → cameras → speech → sensor fusion
>
> Reliability before autonomy.

This file annotates each step with **what "done" looks like** so a
future PR can claim a layer is complete.

## 1. Inventory ✅

- `core.inventory.find_product(query)` returns the best match or
  `None`.
- Backed by SQLite, seeded from CSV.
- Supports aliases ("coke" → "Coca-Cola 12oz") at confidence ≥ 0.9.
- `find_product()` never returns a partial match silently.

## 2. Cart ✅

- `core.cart.Cart` holds an ordered list of `CartLine`s.
- Each line carries `source`, `actor`, and `confidence`.
- Quantity changes, removes, and merges are deterministic.

## 3. Totals ✅

- `core.totals.compute_totals(cart, tax_rate)` returns subtotal, tax,
  and total — all `Decimal`, all quantized at the boundary.
- Tax is applied only to taxable lines.

## 4. Cash ✅

- `core.cash.compute_change(total, tendered)` returns change in the
  smallest denominations available.
- `core.cash.is_sufficient(total, tendered)` is the only gate to
  close.

## 5. Receipts ✅

- `audit.receipts.render_text(state)` returns a printable receipt.
- `audit.receipts.render_json(state)` returns a stable JSON shape
  with `schema_version: 1`.

## 6. Audit ✅

- `audit.eventlog.EventLog` writes one JSON object per line, each
  ending in a SHA-256 over `prev_hash || json_payload`.
- Hash chain verifiable in O(n) with no state besides the file.

## 7. Replay ✅

- `audit.replay.replay(events) -> State` is a pure function.
- The CLI's live `state()` and `replay(log)` produce **byte-identical
  JSON** for any closed transaction. This is the central test.

## 8. CIT ✅

- `safety.cit` tracks till opens/closes, drops, pickups, witness
  sign-offs.
- All CIT events live in the same JSONL as cart events, sharing the
  hash chain.

## 9. Safety ✅

- `safety.risk` produces a per-transaction risk score.
- `safety.policy` enforces void/refund/discount thresholds.

## 10. Agents ✅

- `agents.parser` is the deterministic primary parser.
- `agents.supervisor` orchestrates parser → DB match → optional LLM
  fallback → confirmation gate.
- `agents.lemonade_client` and `agents.flm_client` use stdlib
  `urllib` with hard timeouts.
- `agents.gaia_bridge` is an optional adapter for GAIA agents.

## 11. Cameras 🚧

- `sensors.camera.CameraSource` is an interface only.
- Expected to emit `product_observed` events.
- Confirmation gate is the same as for typed input.

## 12. Speech 🚧

- `sensors.speech.SpeechSource` is an interface only.
- Expected to emit `text_observed` events.
- No customer audio is persisted; rolling buffer only.

## 13. Sensor fusion 🚧

- `sensors.fusion.FusionSource` reconciles overlapping camera and
  speech observations into a single `ParsedEvent`.
- The fusion module is *itself* an agent: it never names a SKU,
  only proposes a normalization for the deterministic core to
  accept or reject.

---

## When can a layer be promoted from 🚧 to ✅?

A layer is promoted only when:

1. It writes events that round-trip through `replay()`.
2. It has a "model unreachable" test that does not crash or hang.
3. It has a documented confidence/permission model in
   [`AGENTS.md`](../AGENTS.md).
4. It does not require a new runtime dependency in `core/`.
