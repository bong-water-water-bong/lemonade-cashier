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

## 8. CIT ✅ (v2 — chain of custody)

- `safety.cit` tracks till opens/closes, drops, pickups, witness
  sign-offs.
- `safety.bags` tracks the full bag lifecycle:
  `sealed → handoff → received → reconciled | discrepancy`.
- Two-party verification at handoff: cashier `attendant_id` and
  `carrier_id` must differ. Same-ID handoff is rejected.
- Manifest is a `tuple[DenominationCount, ...]` (same shape as
  `ChangeBreakdown`) — the sealed total is auditable per denomination,
  not just gross.
- Discrepancies are events, not exceptions:
  `cit.bag.discrepancy` carries a signed `delta` (negative = short,
  positive = over).
- All CIT events live in the same JSONL as cart events, sharing the
  hash chain. `audit.replay` exposes a `state.bags` dict keyed by
  `bag_id` so any UI can render in-flight bags without depending on
  `safety.bags`.

## 9. Safety ✅ (v2 — PIN gates, lockout, profile, tamper, EOS report)

- `safety.risk` produces a per-transaction risk score.
- `safety.policy` enforces void/refund/discount thresholds (sign-aware
  via abs(); see earlier independent-reviewer finding).
- `safety.pins` is the hashed PIN store: PBKDF2-SHA256, 200k iterations,
  per-entry salt, constant-time compare, atomic write. PIN values never
  appear in any persisted file or event payload.
- `safety.lockout` is an event-projected per-attendant lockout: N
  failed PIN attempts within a rolling window → locked for K minutes.
  Same single-source-of-truth invariant as `safety.bags`.
- `safety.profile` rolls every attendant's behavior into stats: void
  rate, low-confidence add rate, model-proposed-add rate, bag-discrepancy
  rate, pin-failure count.
- `safety.tamper` runs cheap O(n) detectors over the log: clock skew
  vs system time, long quiet periods, transaction.open/close imbalance.
  Findings are returned for the report layer; the chain itself remains
  the integrity source.
- `safety.report` is the end-of-shift roll-up: log verification status,
  till state, every bag's status, every attendant's profile, every
  tamper finding, and totals. Renders to JSON and 80-column text.
- Supervisor wiring: every void above the policy threshold demands a
  PIN. Wrong PINs route through lockout; too many failures lock the
  supervisor account for K minutes. The lockout module surfaces the
  state from the event log alone.

## 10. Agents ✅ (v2 — multi-agent security + observability)

- `agents.parser` is the deterministic primary parser.
- `agents.supervisor` orchestrates parser → DB match → optional LLM
  fallback → confirmation gate. Now writes `agent.proposal` events
  alongside every model call.
- `agents.lemonade_client` and `agents.flm_client` use stdlib `urllib`
  with hard timeouts. Stateless RPCs — the supervisor decides the
  proposal disposition (accepted / rejected / needs_confirmation /
  unreachable).
- `agents.proposals` is the canonical writer + reader for
  `agent.proposal` events. Every model call lands in the hash chain
  with input, output, confidence, and decision.
- `agents.registry` declares each agent's capability surface (allowed
  kinds + actor roles). Capability checks are enforced via
  `assert_can_emit()` at every proposal write — adding a new
  capability requires editing the registry.
- `agents.qa_agent` is a read-only Q&A agent. Capability-bounded to
  `chat_response`; cannot mutate the cart. Trims operator-only fields
  (PIN counts, tamper detail) from the model's context.
- `agents.summarizer` wraps the EOS report with a natural-language
  paragraph. Falls back to a deterministic template if the model is
  disabled or unreachable so the EOS workflow is never blocked.
- `audit.replay` now surfaces `state.agent_history` from any
  `agent.proposal` events so any UI can render "what the model
  proposed vs. what the supervisor accepted" without depending on the
  agents module.

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
