"""Tests for the per-transaction risk score."""

from __future__ import annotations

from lemonade_cashier.core.cart import Cart, CartLine
from lemonade_cashier.safety.risk import RiskInputs, score


def cart_with(lines: list[dict]) -> Cart:
    cart = Cart()
    for kw in lines:
        cart.add(CartLine(**kw))
    return cart


def test_empty_transaction_has_low_score():
    inputs = RiskInputs(
        cart=Cart(),
        voids_in_txn=0,
        tender=None,
        closing_hour_local=12,
    )
    assert score(inputs).value == 0.0


def test_low_confidence_lines_raise_score():
    cart = cart_with([
        {"sku": "X", "name": "x", "unit_price": "1.00", "taxable": True,
         "confidence": 0.5, "source": "fuzzy"},
        {"sku": "Y", "name": "y", "unit_price": "1.00", "taxable": True,
         "confidence": 0.5, "source": "fuzzy"},
    ])
    inputs = RiskInputs(cart=cart, voids_in_txn=0, tender=None, closing_hour_local=12)
    assert score(inputs).value > 0.05


def test_closing_window_adds_factor():
    inputs = RiskInputs(
        cart=Cart(), voids_in_txn=0, tender=None, closing_hour_local=23
    )
    result = score(inputs)
    assert any(name == "closing_window" for name, _ in result.factors)


def test_score_is_capped_at_one():
    cart = cart_with(
        [
            {"sku": f"X{n}", "name": f"x{n}", "unit_price": "1.00",
             "taxable": True, "confidence": 0.1, "source": "model_proposed"}
            for n in range(50)
        ]
    )
    inputs = RiskInputs(
        cart=cart, voids_in_txn=5, tender="500.00", closing_hour_local=0
    )
    assert score(inputs).value <= 1.0
