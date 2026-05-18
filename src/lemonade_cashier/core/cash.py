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


class UnmakeableChange(ValueError):
    """Raised when the provided denominations can't sum to the change due.

    This happens only with custom denomination sets that omit a fine
    enough unit (e.g., calling :func:`compute_change` with only
    Decimal("1.00") bills when the change due is $0.37). The default
    US set always satisfies the change.
    """


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

    sorted_denoms = sorted(denominations, reverse=True)
    if any(d <= ZERO for d in sorted_denoms):
        raise ValueError("denominations must all be > 0")

    change_due = to_display(tendered_d - total_d)
    remaining = change_due
    breakdown: list[tuple[Decimal, int]] = []
    for denom in sorted_denoms:
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
    if remaining != ZERO:
        raise UnmakeableChange(
            f"cannot make change for {money_str(change_due)} from "
            f"denominations {sorted_denoms}: "
            f"{money_str(remaining)} remaining"
        )
    return ChangeBreakdown(
        change_due=change_due,
        breakdown=tuple(breakdown),
    )


__all__ = [
    "ChangeBreakdown",
    "DEFAULT_DENOMINATIONS",
    "InsufficientTender",
    "UnmakeableChange",
    "compute_change",
    "is_sufficient",
]
