# Agent Safety Policies & Safe Zones

> Safety guidelines, actor authority limits, supervisor PIN override thresholds, and forbidden paths for AI agents working in the `lemonade-cashier` repository.

## Supervisor PIN Thresholds

Supervisor-level operations (voids, refunds, discounts) require a PBKDF2-SHA256 hashed PIN authorization when transaction changes equal or exceed the following magnitudes defined in [policy.py](../../src/lemonade_cashier/safety/policy.py):

- **Void Threshold**: `Decimal('10.00')` (`DEFAULT_VOID_PIN_THRESHOLD`)
- **Refund Threshold**: `Decimal('5.00')` (`DEFAULT_REFUND_PIN_THRESHOLD`)
- **Discount Threshold**: `Decimal('3.00')` (`DEFAULT_DISCOUNT_PIN_THRESHOLD`)

> [!IMPORTANT]
> The thresholds compare the absolute *magnitude* of the changes. Downstream applications must normalize values via `abs()` to guarantee that sign-independent bypasses do not occur.

---

## Actor Permission States

Authority is transactional and follows the JSON state, not the agent process. Permissions per role:

| Actor | Can add cart line? | Can void? | Can close transaction? |
|---|---|---|---|
| `attendant` | ✅ | ✅ | ✅ |
| `agent_confirmed` | ✅ | ❌ | ❌ |
| `agent_auto` | ✅ | ❌ | ❌ |
| `customer` | ❌ | ❌ | ❌ |

- **`agent_confirmed`**: LLM proposal, manually approved by attendant.
- **`agent_auto`**: LLM proposal with confidence $\ge$ threshold, auto-applied.
- **`customer`**: Self-service role, restricted from modifications.

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

- [[README]] — project wiki entry point
- [[architecture]] — high-level system view and event envelope
- [[conventions]] — coding style standards
- [[runbook]] — commands and ports
