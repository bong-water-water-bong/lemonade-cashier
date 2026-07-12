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

from .errors import CashierError
from .money import ZERO, money_str, multiply, to_money

Actor = Literal["attendant", "agent_auto", "agent_confirmed", "customer"]
Source = Literal["typed", "alias", "fuzzy", "model_proposed", "scanned"]


class PriceMismatchError(CashierError):
    """Raised when :meth:`Cart.add` tries to merge a SKU at a different price."""


@dataclass
class CartLine:
    """One physical/logical item on the receipt.

    ``confidence`` is the matching confidence (0.0-1.0). For typed
    attendant entries that exactly match a SKU name, this is 1.0.

    ``tax_rate`` is the VAT rate applied to this line. When ``None``,
    the supervisor's global rate is used. Set to a specific
    :class:`Decimal` for multi-rate VAT scenarios (e.g. zero-rated
    essentials vs standard-rated goods).
    """

    sku: str
    name: str
    unit_price: Decimal
    taxable: bool
    quantity: int = 1
    actor: Actor = "attendant"
    source: Source = "typed"
    confidence: float = 1.0
    tax_rate: Decimal | None = None

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError("quantity must be >= 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        self.unit_price = to_money(self.unit_price)
        if self.tax_rate is not None:
            self.tax_rate = to_money(self.tax_rate)

    @property
    def line_total(self) -> Decimal:
        return multiply(self.unit_price, self.quantity)

    def vat_amount(self, default_rate: Decimal | None = None) -> Decimal | None:
        """VAT for this line, or None if the line is not taxable."""
        if not self.taxable:
            return None
        rate = self.tax_rate if self.tax_rate is not None else default_rate
        if rate is None:
            return None
        return multiply(self.line_total, rate)

    def vat_rate_display(self, default_rate: Decimal | None = None) -> str | None:
        """Human-readable VAT rate (e.g. '15%'), or None if not taxable."""
        if not self.taxable:
            return None
        rate = self.tax_rate if self.tax_rate is not None else default_rate
        if rate is None:
            return None
        return f"{int(rate * 100)}%"

    def to_state(self) -> dict[str, object]:
        state: dict[str, object] = {
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
        if self.tax_rate is not None:
            state["vat_rate"] = self.vat_rate_display()
        if self.taxable:
            vat = self.vat_amount()
            if vat is not None:
                state["vat_amount"] = money_str(vat)
        return state


@dataclass
class Cart:
    """Ordered, mutable collection of :class:`CartLine` entries."""

    lines: list[CartLine] = field(default_factory=list)
    last_sku: str | None = None

    def add(self, line: CartLine) -> None:
        """Add a line, merging quantity if the SKU already exists.

        Merging is **audit-faithful**: a merge can only *downgrade*
        provenance, never upgrade it. The merged line keeps the
        less-trusted actor/source and the *minimum* confidence of the
        two adds. The event log still records each add separately, so
        the full provenance trail is preserved there — this rule just
        ensures the in-memory snapshot never overstates trust.

        Raises :class:`PriceMismatchError` if the SKU is already in the
        cart at a different ``unit_price``. The customer must be charged
        the same price for every unit of the same SKU in a single
        transaction; a silent merge that takes the first price would
        hide a catalog edit or a model-proposed stale price.
        """

        for existing in self.lines:
            if existing.sku == line.sku:
                if existing.unit_price != line.unit_price:
                    raise PriceMismatchError(
                        f"cannot merge {line.sku}: existing unit_price "
                        f"{existing.unit_price} != new {line.unit_price}. "
                        "Remove the existing line and re-add at the new price."
                    )
                existing.quantity += line.quantity
                existing.actor = _least_trusted_actor(existing.actor, line.actor)
                existing.source = _least_trusted_source(existing.source, line.source)
                existing.confidence = min(existing.confidence, line.confidence)
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

    def item_count(self) -> int:
        """Total number of individual items across all lines."""
        return sum(line.quantity for line in self.lines)

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

    def to_state(self) -> dict[str, object]:
        """Snapshot of the full cart, suitable for logging and replay."""
        return {
            "items": [line.to_state() for line in self.lines],
            "item_count": self.item_count(),
            "subtotal": money_str(self.subtotal()),
            "taxable_subtotal": money_str(self.taxable_subtotal()),
            "last_sku": self.last_sku,
        }


# Ordering used by `Cart.add` to pick the *less* trusted actor/source on
# merge. The list is most-trusted → least-trusted. Anything not listed is
# treated as more trusted than anything that is, except `customer` which
# is always the least trusted.
_ACTOR_TRUST: tuple[Actor, ...] = ("attendant", "agent_confirmed", "agent_auto", "customer")
_SOURCE_TRUST: tuple[Source, ...] = ("typed", "scanned", "alias", "fuzzy", "model_proposed")


def _least_trusted_actor(a: Actor, b: Actor) -> Actor:
    return max((a, b), key=_ACTOR_TRUST.index)


def _least_trusted_source(a: Source, b: Source) -> Source:
    return max((a, b), key=_SOURCE_TRUST.index)


__all__ = ["Actor", "Cart", "CartLine", "PriceMismatchError", "Source"]
