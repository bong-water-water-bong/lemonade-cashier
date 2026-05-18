"""Cash: tender, change, and denomination breakdown.

This module is intentionally narrow: it knows about US-style currency
denominations (you can override) and returns a deterministic breakdown.
It does *not* know about payment processors, card readers, or any
network operation. Cash math is local arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .money import ZERO, money_str, to_display, to_money

# Largest-to-smallest order. Greedy change-making iterates largest-first
# (we also sort defensively in compute_change to keep this independent of
# tuple order if a caller passes a custom set of denominations).
DEFAULT_DENOMINATIONS: tuple[Decimal, ...] = (
    Decimal("100.00"),
    Decimal("50.00"),
    Decimal("20.00"),
    Decimal("10.00"),
    Decimal("5.00"),
    Decimal("1.00"),
    Decimal("0.25"),
    Decimal("0.10"),
    Decimal("0.05"),
    Decimal("0.01"),
)


class InsufficientTender(ValueError):
    """Raised when ``tendered`` is less than ``total``."""


@dataclass(frozen=True)
class ChangeBreakdown:
    """The composition of change due, in canonical US denominations."""

    change_due: Decimal
    breakdown: tuple[tuple[Decimal, int], ...]

    def to_state(self) -> dict[str, object]:
        return {
            "change_due": money_str(self.change_due),
            "breakdown": [
                {"denomination": money_str(d), "count": n}
                for d, n in self.breakdown
            ],
        }


def is_sufficient(total: Decimal, tendered: Decimal) -> bool:
    """Return True iff ``tendered`` covers ``total``."""

    return to_money(tendered) >= to_money(total)


def compute_change(
    total: Decimal,
    tendered: Decimal,
    *,
    denominations: tuple[Decimal, ...] = DEFAULT_DENOMINATIONS,
) -> ChangeBreakdown:
    """Greedy-break ``tendered - total`` into ``denominations``.

    Raises :class:`InsufficientTender` if the tender doesn't cover the
    total. For US denominations the greedy algorithm is optimal; for
    custom denominations the breakdown is still correct (it sums to the
    change due) but is not guaranteed minimal-count.
    """

    total_d = to_money(total)
    tendered_d = to_money(tendered)
    if tendered_d < total_d:
        raise InsufficientTender(
            f"tendered {money_str(tendered_d)} < total {money_str(total_d)}"
        )

    remaining = to_display(tendered_d - total_d)
    breakdown: list[tuple[Decimal, int]] = []
    for denom in sorted(denominations, reverse=True):
        if remaining < denom:
            continue
        count = int(remaining // denom)
        if count == 0:
            continue
        breakdown.append((denom, count))
        remaining -= denom * count
        remaining = to_display(remaining)
        if remaining == ZERO:
            break
    return ChangeBreakdown(
        change_due=to_display(tendered_d - total_d),
        breakdown=tuple(breakdown),
    )


__all__ = [
    "ChangeBreakdown",
    "DEFAULT_DENOMINATIONS",
    "InsufficientTender",
    "compute_change",
    "is_sufficient",
]
