"""Tests for cash tender, change, and the insufficient-tender guard."""

from __future__ import annotations

from decimal import Decimal

import pytest

from lemonade_cashier.core.cash import (
    InsufficientTender,
    UnmakeableChange,
    compute_change,
    is_sufficient,
)


def test_sufficient_tender():
    assert is_sufficient("5.00", "5.00")
    assert is_sufficient("5.00", "10.00")
    assert not is_sufficient("5.00", "4.99")


def test_compute_change_makes_correct_denominations():
    change = compute_change("3.62", "5.00")
    assert change.change_due == Decimal("1.38")
    # Greedy on US denominations: $1, 25¢, 10¢, 1¢ x 3
    breakdown_dict = dict(change.breakdown)
    assert breakdown_dict[Decimal("1.00")] == 1
    assert breakdown_dict[Decimal("0.25")] == 1
    assert breakdown_dict[Decimal("0.10")] == 1
    assert breakdown_dict[Decimal("0.01")] == 3


def test_compute_change_zero_change():
    change = compute_change("5.00", "5.00")
    assert change.change_due == Decimal("0.00")
    assert change.breakdown == ()


def test_compute_change_rejects_insufficient_tender():
    with pytest.raises(InsufficientTender):
        compute_change("10.00", "9.99")


def test_compute_change_unmakeable_raises():
    # Only $1 bills available, change due is $0.37 — no way to break.
    with pytest.raises(UnmakeableChange):
        compute_change("0.63", "1.00", denominations=(Decimal("1.00"),))
