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


def test_merge_downgrades_actor_and_confidence():
    """A merge can lower trust but never raise it."""

    cart = Cart()
    # First add: attendant, full confidence.
    cart.add(make_line(qty=1, actor="attendant", source="typed", confidence=1.0))
    # Second add: agent_auto, lower confidence — should drag merged line down.
    cart.add(make_line(qty=1, actor="agent_auto", source="model_proposed", confidence=0.7))
    assert len(cart.lines) == 1
    merged = cart.lines[0]
    assert merged.quantity == 2
    assert merged.actor == "agent_auto"
    assert merged.source == "model_proposed"
    assert merged.confidence == 0.7


def test_merge_keeps_least_trusted_on_either_order():
    """Merge result is independent of which add came first."""

    cart_a, cart_b = Cart(), Cart()
    cart_a.add(make_line(actor="attendant", source="typed", confidence=1.0))
    cart_a.add(make_line(actor="agent_confirmed", source="fuzzy", confidence=0.6))
    cart_b.add(make_line(actor="agent_confirmed", source="fuzzy", confidence=0.6))
    cart_b.add(make_line(actor="attendant", source="typed", confidence=1.0))

    assert cart_a.lines[0].actor == cart_b.lines[0].actor == "agent_confirmed"
    assert cart_a.lines[0].confidence == cart_b.lines[0].confidence == 0.6


def test_cart_line_rejects_float_unit_price():
    # to_money(float) raises MoneyError, which is a ValueError subclass.
    from lemonade_cashier.core.money import MoneyError

    with pytest.raises((MoneyError, ValueError)):
        CartLine(sku="X", name="x", unit_price=1.50, taxable=True)


def test_cart_add_rejects_price_mismatch():
    """A second add of the same SKU at a different unit_price must
    raise PriceMismatchError, not silently keep the first price."""

    from lemonade_cashier.core.cart import PriceMismatchError

    cart = Cart()
    cart.add(make_line(price="1.00", qty=1))
    with pytest.raises(PriceMismatchError):
        cart.add(make_line(price="1.50", qty=1))


def test_cart_add_same_price_still_merges():
    """Sanity: matching prices still merge quantity."""

    cart = Cart()
    cart.add(make_line(price="1.00", qty=1))
    cart.add(make_line(price="1.00", qty=2))
    assert len(cart.lines) == 1
    assert cart.lines[0].quantity == 3
