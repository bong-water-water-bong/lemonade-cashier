# Safety

This is the long-form rationale for the constraints in
[`AGENTS.md`](../AGENTS.md). Read it before changing anything in
`core/`, `audit/`, or `safety/`.

## Why a deterministic financial core matters

A cashier's job is to turn a stream of physical events ("customer
brought milk to the counter") into an auditable monetary record. The
auditability is the product. If a transaction can't be reconstructed
exactly from its event log, the cashier is, by definition, broken.

This is why:

- The core is `Decimal`. Floats lose pennies. Pennies become quarters.
  Quarters become reconciliation tickets.
- The event log is append-only and hash-chained. A torn file is
  detectable. A re-ordered event is detectable. A silently dropped
  event is detectable.
- The receipt is a *projection*, not a source. If the receipt
  disagrees with `replay()`, the receipt is wrong.

## Why agents must not name prices

LLMs are extraordinarily good at producing fluent, confident output
that is wrong. If a model can pick a SKU, then at scale a model *will*
pick the wrong SKU at a confidence level that fools downstream code.

The cashier sidesteps this entirely: agents *propose normalizations
of attendant text*. They produce a string like `"coca-cola 12oz"` and
nothing else. The deterministic `find_product()` decides whether
that's a real SKU, and the confidence gate decides whether to require
attendant confirmation.

This is also why `agents/` never imports from `core/cart.py` directly
— it goes through `supervisor`, which goes through `parser`, which
goes through `inventory`. Every step is gated.

## Why authority lives in JSON state, not in the agent process

The supervisor agent is a Python class. It can be restarted, swapped,
upgraded, or run on a different host. The transaction is not. The
transaction is a JSON document that exists on disk, with a hash chain
that ties it to the till open. **Authority to close a transaction is
a property of the JSON document, not the process that built it.**

In practice this means: a supervisor agent that crashes mid-cart does
not lose authority. A fresh supervisor can be started, `replay()` the
event log, and pick up at exactly the same line with exactly the same
risk score. No state lives in agent memory that isn't already in the
event log.

## Why untrusted text never sees credentials

The Lemonade and FLM clients send a prompt that includes:

- The current cart contents (already non-secret).
- A constrained JSON-schema response specification.

They do **not** include:

- Attendant IDs, PINs, or PIN hashes.
- Till IDs or safe combinations.
- Customer PII (name, card, loyalty number).
- API keys for any downstream service.

Even a perfect prompt-injection attack against the local model
therefore cannot exfiltrate a credential, because credentials never
reach the model. This is enforced in code: `lemonade_client.normalize()`
takes a `cart` and a `phrase`, full stop. There is no kwargs
fall-through to the HTTP body.

## Why no customer audio or images are persisted

The Phase 2 camera and ASR pipelines will run *inference-only* on
rolling buffers. The cashier records the **inferred event**
(`product_observed`, `text_observed`) but not the raw pixels or
audio. Two reasons:

1. The data is sensitive (customer faces, voices) and the cashier
   should not be the system of record for it.
2. The audit story is cleaner: the cashier replays events, not
   sensor data.

If a customer later disputes a charge, the evidence is the event log
and the receipt, not a video clip.

## Why "no agentic commerce yet"

When agents start initiating payments to other agents, three things
need to be true at the same time:

- **Human intent is visible.** Some affirmative action ties the
  payment to a person.
- **Payment authority is bound to the transaction.** A token can pay
  this transaction, not "anything the agent decides to do".
- **The agent is a facilitator, not a party.** The agent can request
  a charge; it cannot become the merchant of record.

The cashier does not satisfy any of these today. So it does not do
agentic commerce. When it does, those three sentences become tests in
`safety/policy.py`. Until then, this section exists to remind us why.

## Where to put new safety rules

- A new monetary invariant → `tests/test_money.py`.
- A new policy threshold → `safety/policy.py` + `.env.example`.
- A new event type's auditability → `tests/test_replay.py`.
- A new actor → the permission table in [`AGENTS.md`](../AGENTS.md).

