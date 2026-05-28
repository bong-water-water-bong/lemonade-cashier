"""Deterministic financial core.

Modules in this package are pure: no network, no clock dependence
(except where a timestamp is *passed in*), no randomness, no I/O. All
money math is :class:`decimal.Decimal`.
"""

from __future__ import annotations

from .errors import CashierError

__all__ = ["CashierError"]

