"""Tests for the totals engine."""

from __future__ import annotations

from decimal import Decimal

from lemonade_cashier.core.cart import Cart, CartLine
from lemonade_cashier.core.totals import compute_totals


def test_compute_totals_basic():
    cart = Cart()
    cart.add(CartLine(sku="APL001", name="apple", unit_price="1.00", taxable=True, quantity=2))
    cart.add(CartLine(sku="MLK001", name="milk", unit_price="3.00", taxable=False))

    totals = compute_totals(cart, "0.15")
    assert totals.subtotal == Decimal("5.00")
    assert totals.taxable_subtotal == Decimal("2.00")
    assert totals.tax == Decimal("0.30")
    assert totals.total == Decimal("5.30")


def test_compute_totals_zero_rate():
    cart = Cart()
    cart.add(CartLine(sku="A", name="a", unit_price="1.00", taxable=True))
    totals = compute_totals(cart, "0.00")
    assert totals.tax == Decimal("0.00")
    assert totals.total == Decimal("1.00")


def test_compute_totals_empty_cart():
    totals = compute_totals(Cart(), "0.15")
    assert totals.subtotal == Decimal("0.00")
    assert totals.tax == Decimal("0.00")
    assert totals.total == Decimal("0.00")


def test_compute_totals_high_precision_does_not_drift():
    """Three lines at $0.10 with 15% tax should be exact."""

    cart = Cart()
    for _ in range(3):
        cart.add(
            CartLine(
                sku=f"X{_}",
                name=f"x{_}",
                unit_price="0.10",
                taxable=True,
            )
        )
    totals = compute_totals(cart, "0.15")
    assert totals.subtotal == Decimal("0.30")
    # 0.30 * 0.15 = 0.045 → rounds to 0.04 (bankers' rounding, 4 is even).
    assert totals.tax == Decimal("0.04")
    assert totals.total == Decimal("0.34")
