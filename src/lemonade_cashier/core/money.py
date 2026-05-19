"""Decimal-only money primitives.

Every monetary value in the cashier passes through this module. The
rules are:

* Internally, money is :class:`decimal.Decimal` quantized to four
  decimal places (``Q_INTERNAL``). Tax and per-line math stay at four
  places so that compound operations don't drift.
* At a display or persistence boundary, values are re-quantized to two
  decimal places (``Q_DISPLAY``) using bankers' rounding
  (``ROUND_HALF_EVEN``). That's the IRS / FASB default and the one
  fewest people argue about.
* Parsing and serialization go through :func:`to_money` and
  :func:`money_str`. Nothing else should call ``Decimal(...)`` directly.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from typing import Final

Q_INTERNAL: Final = Decimal("0.0001")
Q_DISPLAY: Final = Decimal("0.01")
ZERO: Final = Decimal("0.00")


class MoneyError(ValueError):
    """Raised when a value cannot be interpreted as money."""


def to_money(value: object) -> Decimal:
    """Coerce ``value`` to a :class:`Decimal` quantized for internal math.

    Accepts ``int``, ``Decimal``, or string-like values. ``float`` is
    rejected explicitly — using floats for money is the bug this module
    exists to prevent.
    """

    if isinstance(value, float):
        raise MoneyError("float values are not allowed for money; use Decimal or a string")
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, int):
        candidate = Decimal(value)
    elif isinstance(value, str):
        try:
            candidate = Decimal(value.strip())
        except InvalidOperation as exc:
            raise MoneyError(f"cannot parse {value!r} as money") from exc
    else:
        raise MoneyError(f"unsupported money type: {type(value).__name__}")

    return _quantize(candidate, Q_INTERNAL)


def to_display(value: Decimal) -> Decimal:
    """Quantize a value to the two-place display form."""

    return _quantize(value, Q_DISPLAY)


def money_str(value: Decimal) -> str:
    """Render a value as a fixed two-place string (no currency symbol)."""

    return f"{to_display(value):.2f}"


def add(*values: Decimal) -> Decimal:
    """Sum a sequence of money values, preserving four-place precision."""

    total = ZERO
    for v in values:
        total += v
    return _quantize(total, Q_INTERNAL)


def multiply(value: Decimal, factor: int | Decimal) -> Decimal:
    """Multiply a money value by an integer quantity or a Decimal rate."""

    if isinstance(factor, float):
        raise MoneyError("float factor is not allowed; use int or Decimal")
    result = value * Decimal(factor) if isinstance(factor, int) else value * factor
    return _quantize(result, Q_INTERNAL)


def _quantize(value: Decimal, exponent: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.rounding = ROUND_HALF_EVEN
        return value.quantize(exponent)


__all__ = [
    "Q_DISPLAY",
    "Q_INTERNAL",
    "ZERO",
    "MoneyError",
    "add",
    "money_str",
    "multiply",
    "to_display",
    "to_money",
]
