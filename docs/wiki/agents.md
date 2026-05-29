# Agent Safety Policies & Safe Zones

> Safety guidelines, actor authority limits, supervisor PIN override thresholds, and forbidden paths for AI agents working in the `lemonade-cashier` repository.

## Supervisor PIN Thresholds

Supervisor-level operations require a `PBKDF2-SHA256` hashed PIN authorization when transaction changes equal or exceed specific magnitudes. While default thresholds for voids, refunds, and discounts are defined in [policy.py](../../src/lemonade_cashier/safety/policy.py), their implementation status in the codebase differs:

- **Void Threshold**: `Decimal('10.00')` (`DEFAULT_VOID_PIN_THRESHOLD`). Active and enforced via `_gate_void` in [supervisor.py](../../src/lemonade_cashier/agents/supervisor.py).
- **Refund Threshold**: `Decimal('5.00')` (`DEFAULT_REFUND_PIN_THRESHOLD`). **Unused/Placeholder**: Refunds are not yet implemented in the cashier core or supervisor.
- **Discount Threshold**: `Decimal('3.00')` (`DEFAULT_DISCOUNT_PIN_THRESHOLD`). **Unused/Placeholder**: Discounts are not yet implemented in the cashier core or supervisor.

> [!IMPORTANT]
> The thresholds compare the absolute *magnitude* of the changes. Downstream applications must normalize values via `abs()` to guarantee that sign-independent bypasses do not occur.

---

## Actor Permission States

Actor roles represent the serialized origin of actions recorded inside cart line metadata (see `Actor` literal in [cart.py](../../src/lemonade_cashier/core/cart.py)), tracking event authority within the append-only event log.

Permissions per role:

| Actor | Can add cart line? | Can void? | Can close transaction? |
|---|---|---|---|
| `attendant` | ✅ | ✅ | ✅ |
| `agent_confirmed` | ✅ | ❌ | ❌ |
| `agent_auto` | ✅ | ❌ | ❌ |
| `customer` | ❌ | ❌ | ❌ |

### Runtime Enforcement & Session Model
- **Single Attendant Session**: In the current CLI prototype, the supervisor process runs in a linear CLI environment representing a single active `attendant`. As a result, role authority constraints are not dynamically enforced on incoming user text commands; `Supervisor.handle_text` in [supervisor.py](../../src/lemonade_cashier/agents/supervisor.py) executes command actions uniformly.
- **`agent_auto`**: LLM proposals with a confidence score equal to or exceeding `CONFIDENCE_THRESHOLD = 0.8` (configured in [supervisor.py](../../src/lemonade_cashier/agents/supervisor.py)) are auto-applied directly.
- **`agent_confirmed`**: LLM proposals with confidence below `0.8` are presented to the attendant for manual confirmation.
- **`customer`**: A self-service placeholder role. While defined in [cart.py](../../src/lemonade_cashier/core/cart.py#L17), it is currently unused in transaction flows.

---

## Hard Rules & Prohibited Paths

AI agents are strictly forbidden from implementing or modifying:

- **Third-Party Payment Gateways**: Absolutely no Stripe, credit card readers, or online processors in core logic. Only cash and CIT are supported.
- **Privacy Intrusion**: Persistent logging or saving of customer ASR audio feeds or camera pictures is prohibited. Rolling memory buffers must be inference-only.
- **Self-Modifying Code**: AI models must not write self-updating loop systems or modify their prompt configurations.
- **Bypassing Audits**: Every inventory change and checkout operation must pass through event log serialization and replay.

---

## Safe Zones

When contributing:
- **`docs/wiki/`**: Agents may add/edit documentation pages to capture system behaviors.
- **`src/lemonade_cashier/core/`**: Core financial math (must remain stdlib-only, no dependencies).
- **`tests/`**: Creating unit tests for validation.

---

## Related

- [README](README.md) — project wiki entry point
- [architecture](architecture.md) — high-level system view and event envelope
- [conventions](conventions.md) — coding style standards
- [runbook](runbook.md) — commands and ports
