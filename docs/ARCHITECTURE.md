# Architecture

This document explains *why* the code is organized the way it is.
For *what to do*, see [AGENTS.md](https://github.com/bong-water-water-bong/lemonade-cashier/blob/main/AGENTS.md). For *what to build
next*, see [`BUILD_ORDER.md`](BUILD_ORDER.md).

## Layered model

The code is organized in concentric rings. **Inner rings know nothing
about outer rings.** Outer rings may import inward.

```
                    ┌────────────────────────────────┐
                    │  sensors/  (camera, ASR, fuse) │   ← outermost
                    ├────────────────────────────────┤
                    │  agents/   (parsers, LLM,       │
                    │            supervisor, GAIA)    │
                    ├────────────────────────────────┤
                    │  safety/   (risk, policy, CIT) │
                    ├────────────────────────────────┤
                    │  audit/    (eventlog, replay,  │
                    │            receipts)            │
                    ├────────────────────────────────┤
                    │  core/     (money, inventory,  │
                    │            cart, totals, cash)  │   ← innermost (pure)
                    └────────────────────────────────┘
```

`core/` is pure Python: no network, no clock dependence, no
randomness. `audit/` is the first ring that touches the filesystem.
`safety/` is the first ring that has policy. `agents/` is the first
ring that can talk to a model. `sensors/` is the first ring that can
talk to hardware.

## Why Decimal everywhere

Floats round wrong for money. `0.1 + 0.2 != 0.3`, and the discrepancy
compounds across thousands of cart lines per shift. The cashier uses
`decimal.Decimal` configured with `ROUND_HALF_EVEN` (bankers' rounding)
and quantized to `Decimal("0.01")` only at presentation. Intermediate
math keeps four-place precision so tax-on-tax doesn't drift.

There is a unit test (`tests/test_money.py::test_no_float_money`) that
greps the source tree and **fails the build** if any module under
`core/` references `float` for monetary values. That's intentional.

## Events are the source of truth

State is a *projection* of events. The cashier writes one JSON event
per cart action to `data/events/cashier.jsonl`, each line ending in a
SHA-256 hash that depends on the previous line's hash. To reconstruct
the state of any transaction, `audit.replay.replay(events)` reads the
file and feeds events back through the same `Cart` API the live CLI
uses. There is no other state.

This means:

- Receipts are derivable, not authoritative.
- A corrupt or truncated event log is *detectable*, because the hash
  chain breaks.
- Any future UI (web, mobile, GAIA chat, voice) can render the same
  cart from the same JSONL without depending on Python.

## How agents fit in (without poisoning the core)

`agents/parser.py` is the **primary** parser. It is deterministic,
rule-based, and never calls a model. It produces a `ParsedEvent` with
an `action`.

`agents/supervisor.py` orchestrates:

1. Run `parser.parse_event(text)`. If it returns an `add_product`
   action with a confident DB match → done.
2. If the DB match is below `CONFIDENCE_THRESHOLD` → ask the
   attendant. Never silently escalate to a model.
3. If no DB match at all and a model is configured **and**
   `LC_LEMONADE_ENABLED=true` → ask Lemonade (or FLM) for a candidate
   normalization within a hard timeout. The model's output goes back
   through `parser` and `inventory.find_product()` like any other text.

Notice what the model **cannot** do:

- Pick a SKU.
- Name a price.
- Change a cart.
- Authorize a void or close.

The model is a *normalizer of attendant phrasing*, nothing more.

## Risk scoring

`safety/risk.py` computes a numeric risk score per transaction. Inputs:

- Time-of-day (closing-hour transactions score higher).
- Void rate within the transaction.
- Mix of low-confidence vs. high-confidence adds.
- Cash-tender ratio (large cash >$100 single-bill change-outs).
- Refund pattern.

Above `LC_RISK_WARN` the UI flags the transaction. Above
`LC_RISK_BLOCK` the close requires a supervisor PIN. The thresholds
are configurable in `.env`.

## CIT (cash-in-transit)

`safety/cit.py` tracks:

- Till opens and closes (with starting/ending counts).
- Mid-shift drops to the safe.
- Pickups from the safe to the till.
- Witness sign-offs when a single drop exceeds the two-person
  threshold.

Each CIT event lands in the same JSONL as cart events, with its own
event type and the same hash chain. There is no separate CIT log.

## What the sensors layer will do (later)

`sensors/camera.py`, `sensors/speech.py`, and `sensors/fusion.py` are
*interfaces only* right now. They define the shape of events those
modules will produce when they exist. The shape was designed first so
that whichever model ships those layers can be developed against
recorded fixtures without needing the cashier core to change.

A PoE camera at the counter will eventually emit
`product_observed` events with `(bbox, candidate_skus, confidence)`.
Those events flow into the supervisor exactly like a typed line — and
get gated by the same confirmation logic. No exceptions.

## Local AI stack assumptions

The repo assumes:

- **Lemonade Server 10.4.0** running locally on
  `http://127.0.0.1:8000` (OpenAI-compatible API).
- **FastFlowLM 0.9.42** running locally on
  `http://127.0.0.1:11434` (Ollama-compatible API).
- **GAIA 0.18.1** Python SDK installed in the same environment, only
  if `agents.gaia_bridge` is used.

None of these are required at runtime. If they're missing, the
cashier behaves exactly as it does on a laptop with no NPU.
