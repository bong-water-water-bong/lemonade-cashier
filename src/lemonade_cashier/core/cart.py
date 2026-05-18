"""Cart: the durable, JSON-serializable cart object.

A :class:`Cart` holds an ordered list of :class:`CartLine` items. Each
line records *who* added it (``actor``), *how* it was added (``source``,
and at *what* confidence). That triple is the audit primitive — see
``docs/SAFETY.md`` for why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from .money import ZERO, money_str, multiply, to_money

Actor = Literal["attendant", "agent_auto", "agent_confirmed", "customer"]
Source = Literal["typed", "alias", "fuzzy", "model_proposed", "scanned"]


@dataclass
class CartLine:
    """One physical/logical item on the receipt.

    ``confidence`` is the matching confidence (0.0–1.0). For typed
    attendant entries that exactly match a SKU name, this is 1.0.
    """

    sku: str
    name: str
    unit_price: Decimal
    taxable: bool
    quantity: int = 1
    actor: Actor = "attendant"
    source: Source = "typed"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError("quantity must be >= 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        # to_money rejects floats, which is the invariant we want.
        self.unit_price = to_money(self.unit_price)

    @property
    def line_total(self) -> Decimal:
        return multiply(self.unit_price, self.quantity)

    def to_state(self) -> dict[str, object]:
        return {
            "sku": self.sku,
            "name": self.name,
            "quantity": self.quantity,
            "unit_price": money_str(self.unit_price),
            "taxable": self.taxable,
            "line_total": money_str(self.line_total),
            "actor": self.actor,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class Cart:
    """Ordered, mutable collection of :class:`CartLine` entries."""

    lines: list[CartLine] = field(default_factory=list)
    last_sku: str | None = None

    def add(self, line: CartLine) -> None:
        """Add a line, merging quantity if the SKU already exists.

        Merging preserves the *earlier* line's actor/source/confidence
        — once attendant-approved, a SKU stays attendant-approved.
        """

        for existing in self.lines:
            if existing.sku == line.sku:
                existing.quantity += line.quantity
                self.last_sku = existing.sku
                return
        self.lines.append(line)
        self.last_sku = line.sku

    def remove_last(self) -> CartLine | None:
        if not self.last_sku:
            return None
        return self.remove_sku(self.last_sku)

    def remove_sku(self, sku: str) -> CartLine | None:
        for index, line in enumerate(self.lines):
            if line.sku == sku:
                removed = self.lines.pop(index)
                self.last_sku = self.lines[-1].sku if self.lines else None
                return removed
        return None

    def set_quantity(self, sku: str, quantity: int) -> bool:
        if quantity < 1:
            return False
        for line in self.lines:
            if line.sku == sku:
                line.quantity = quantity
                return True
        return False

    def set_last_quantity(self, quantity: int) -> bool:
        if not self.last_sku:
            return False
        return self.set_quantity(self.last_sku, quantity)

    def clear(self) -> None:
        self.lines.clear()
        self.last_sku = None

    def is_empty(self) -> bool:
        return not self.lines

    def subtotal(self) -> Decimal:
        total = ZERO
        for line in self.lines:
            total += line.line_total
        return total

    def taxable_subtotal(self) -> Decimal:
        total = ZERO
        for line in self.lines:
            if line.taxable:
                total += line.line_total
        return total


__all__ = ["Actor", "Cart", "CartLine", "Source"]
