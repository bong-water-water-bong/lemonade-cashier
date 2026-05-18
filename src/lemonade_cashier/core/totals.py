"""Totals: tax engine over a :class:`~lemonade_cashier.core.cart.Cart`.

Tax is applied only to lines whose ``taxable`` flag is true. The tax
rate is supplied by the caller (typically from ``LC_TAX_RATE``) so
that the totals function itself remains pure and configurable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .cart import Cart
from .money import money_str, multiply, to_display, to_money


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    taxable_subtotal: Decimal
    tax: Decimal
    total: Decimal

    def to_state(self) -> dict[str, str]:
        return {
            "subtotal": money_str(self.subtotal),
            "taxable_subtotal": money_str(self.taxable_subtotal),
            "tax": money_str(self.tax),
            "total": money_str(self.total),
        }


def compute_totals(cart: Cart, tax_rate: Decimal | str | int) -> Totals:
    """Compute subtotal, tax, and total for ``cart`` at ``tax_rate``."""

    rate = to_money(tax_rate)
    subtotal = cart.subtotal()
    taxable_subtotal = cart.taxable_subtotal()
    tax = multiply(taxable_subtotal, rate)
    total = subtotal + tax
    return Totals(
        subtotal=to_display(subtotal),
        taxable_subtotal=to_display(taxable_subtotal),
        tax=to_display(tax),
        total=to_display(total),
    )


__all__ = ["Totals", "compute_totals"]
