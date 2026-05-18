"""Tests for the void/refund/discount policy gates."""

from __future__ import annotations

from decimal import Decimal

from lemonade_cashier.safety.policy import can_discount, can_refund, can_void


def test_small_void_is_ok():
    outcome = can_void(Decimal("1.00"))
    assert outcome.allowed and not outcome.requires_pin


def test_large_void_requires_pin():
    outcome = can_void(Decimal("100.00"))
    assert outcome.allowed and outcome.requires_pin


def test_refund_threshold():
    assert not can_refund(Decimal("4.99")).requires_pin
    assert can_refund(Decimal("5.00")).requires_pin


def test_discount_threshold():
    assert not can_discount(Decimal("2.99")).requires_pin
    assert can_discount(Decimal("3.00")).requires_pin


def test_negative_void_still_gated():
    """abs() at the gate prevents a 'void of -$100' from bypassing the
    threshold check."""

    outcome = can_void(Decimal("-100.00"))
    assert outcome.requires_pin


def test_negative_refund_still_gated():
    outcome = can_refund(Decimal("-50.00"))
    assert outcome.requires_pin


def test_negative_discount_still_gated():
    outcome = can_discount(Decimal("-25.00"))
    assert outcome.requires_pin
