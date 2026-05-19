"""Policy thresholds and supervisor-PIN gates.

Each policy returns a small dataclass explaining what (if anything) the
caller must do to proceed. The cashier never *blocks*; it requires
attendant or supervisor action.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..core.money import to_money


@dataclass(frozen=True)
class PolicyOutcome:
    allowed: bool
    requires_pin: bool
    reason: str

    @classmethod
    def ok(cls) -> PolicyOutcome:
        return cls(allowed=True, requires_pin=False, reason="")

    @classmethod
    def needs_pin(cls, reason: str) -> PolicyOutcome:
        return cls(allowed=True, requires_pin=True, reason=reason)

    @classmethod
    def deny(cls, reason: str) -> PolicyOutcome:
        return cls(allowed=False, requires_pin=False, reason=reason)


# These defaults match the .env.example file. Real deployments
# override via the supervisor.
DEFAULT_VOID_PIN_THRESHOLD = Decimal("10.00")
DEFAULT_REFUND_PIN_THRESHOLD = Decimal("5.00")
DEFAULT_DISCOUNT_PIN_THRESHOLD = Decimal("3.00")


# All three gates compare the *magnitude* of the change to the threshold.
# A "refund of -$100" is a $100 refund either way — and code that takes
# `abs()` downstream of an unchecked PolicyOutcome would silently bypass
# the supervisor PIN. We normalize via `abs()` at the policy boundary
# so the gate is sign-independent.
def can_void(
    line_total: Decimal,
    *,
    threshold: Decimal = DEFAULT_VOID_PIN_THRESHOLD,
) -> PolicyOutcome:
    amt = abs(to_money(line_total))
    if amt >= to_money(threshold):
        return PolicyOutcome.needs_pin(f"void of ${amt} ≥ ${threshold} requires supervisor")
    return PolicyOutcome.ok()


def can_refund(
    amount: Decimal,
    *,
    threshold: Decimal = DEFAULT_REFUND_PIN_THRESHOLD,
) -> PolicyOutcome:
    amt = abs(to_money(amount))
    if amt >= to_money(threshold):
        return PolicyOutcome.needs_pin(f"refund of ${amt} ≥ ${threshold} requires supervisor")
    return PolicyOutcome.ok()


def can_discount(
    amount: Decimal,
    *,
    threshold: Decimal = DEFAULT_DISCOUNT_PIN_THRESHOLD,
) -> PolicyOutcome:
    amt = abs(to_money(amount))
    if amt >= to_money(threshold):
        return PolicyOutcome.needs_pin(f"discount of ${amt} ≥ ${threshold} requires supervisor")
    return PolicyOutcome.ok()


__all__ = [
    "DEFAULT_DISCOUNT_PIN_THRESHOLD",
    "DEFAULT_REFUND_PIN_THRESHOLD",
    "DEFAULT_VOID_PIN_THRESHOLD",
    "PolicyOutcome",
    "can_discount",
    "can_refund",
    "can_void",
]
