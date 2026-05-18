"""Tests for the Decimal-only money primitives.

The most important test in this file is :func:`test_no_float_money_in_core`
which scans the source tree and fails the build if any module under
``core/`` uses ``float`` for monetary values.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from lemonade_cashier.core.money import (
    MoneyError,
    money_str,
    multiply,
    to_display,
    to_money,
)


def test_to_money_accepts_string_and_decimal_and_int():
    assert to_money("1.23") == Decimal("1.2300")
    assert to_money(5) == Decimal("5.0000")
    assert to_money(Decimal("0.10")) == Decimal("0.1000")


def test_to_money_rejects_float():
    with pytest.raises(MoneyError):
        to_money(0.1)


def test_to_money_rejects_garbage():
    with pytest.raises(MoneyError):
        to_money("not money")


def test_multiply_uses_decimal_math():
    # The float trap: 0.1 * 3 == 0.30000000000000004 with floats.
    price = to_money("0.10")
    assert multiply(price, 3) == Decimal("0.3000")


def test_money_str_is_two_places():
    # Bankers' rounding (round-half-even):
    # 1.005 → 1.00 (0 is even), 1.015 → 1.02 (2 is even).
    assert money_str(to_money("1.005")) == "1.00"
    assert money_str(to_money("1.015")) == "1.02"
    # Any value > 1.005 (when first quantized to 4 places) rounds up:
    # 1.00500001 → 1.0050 → 1.00 (still half-even, lands on even).
    # 1.0051 → 1.0051 → 1.01 (above the midpoint, so it rounds up).
    assert money_str(to_money("1.0051")) == "1.01"


def test_display_quantization():
    assert to_display(Decimal("1.2350")) == Decimal("1.24")
    assert to_display(Decimal("1.2250")) == Decimal("1.22")


def test_no_float_money_in_core():
    """No `float` for money in core/. Find a 'price' or 'amount' bound to a float.

    This is intentionally heuristic — it catches the common patterns
    (`price: float`, `Decimal(1.0)`, `total = 0.0`) without trying to
    parse Python. If you legitimately need a float in core/ (you don't),
    add a `# allow-float` comment on the offending line.
    """

    core_dir = Path(__file__).resolve().parents[1] / "src" / "lemonade_cashier" / "core"
    forbidden_patterns = [
        re.compile(r"\b(price|amount|total|subtotal|tax)\s*:\s*float\b"),
        re.compile(r"Decimal\s*\(\s*\d+\.\d+\s*\)"),
    ]
    offenses: list[str] = []
    for path in core_dir.rglob("*.py"):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "# allow-float" in line:
                continue
            for pattern in forbidden_patterns:
                if pattern.search(line):
                    offenses.append(f"{path}:{line_number}: {line.strip()}")
    assert not offenses, "float used for money in core/:\n" + "\n".join(offenses)
