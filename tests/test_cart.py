"""Tests for the Cart object."""

from __future__ import annotations

from decimal import Decimal

import pytest

from lemonade_cashier.core.cart import Cart, CartLine


def make_line(sku="APL001", name="apple", price="0.75", taxable=True, qty=1, **kw):
    return CartLine(
        sku=sku,
        name=name,
        unit_price=price,
        taxable=taxable,
        quantity=qty,
        **kw,
    )


def test_add_and_merge_same_sku():
    cart = Cart()
    cart.add(make_line(qty=2))
    cart.add(make_line(qty=3))
    assert len(cart.lines) == 1
    assert cart.lines[0].quantity == 5


def test_remove_last():
    cart = Cart()
    cart.add(make_line())
    cart.add(make_line(sku="MLK001", name="milk", price="3.49", taxable=False))
    removed = cart.remove_last()
    assert removed is not None
    assert removed.sku == "MLK001"
    assert cart.last_sku == "APL001"


def test_set_last_quantity_rejects_zero():
    cart = Cart()
    cart.add(make_line())
    assert cart.set_last_quantity(0) is False


def test_subtotal_uses_decimal():
    cart = Cart()
    cart.add(make_line(price="0.10", qty=3))
    # The classic float bug: 0.1 * 3 != 0.3 in float; in Decimal it is.
    assert cart.subtotal() == Decimal("0.3000")


def test_taxable_subtotal_only_taxable():
    cart = Cart()
    cart.add(make_line(price="1.00", qty=1, taxable=True))
    cart.add(make_line(sku="MLK001", name="milk", price="2.00", taxable=False))
    assert cart.subtotal() == Decimal("3.0000")
    assert cart.taxable_subtotal() == Decimal("1.0000")


def test_cart_line_rejects_float_unit_price():
    with pytest.raises(Exception):
        CartLine(sku="X", name="x", unit_price=1.50, taxable=True)
