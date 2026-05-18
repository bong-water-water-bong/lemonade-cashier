"""Supervisor: the multi-agent orchestrator.

Sequence of decisions for any input line:

1. Run :func:`agents.parser.parse_event`. If the action is non-product
   (quit, state, clear, remove_last, etc.), execute it directly.
2. For an ``add_product`` action, run :func:`core.inventory.find_product`.
3. If the match is at or above ``confidence_threshold``, add it.
4. If the match is below the threshold but above the
   :func:`core.inventory.find_product` floor, ask for attendant
   confirmation.
5. If there is no match at all, optionally ask the local LLM
   (Lemonade first, then FLM) for a *normalized phrase* and re-run
   step 2 once with the normalized phrase. The model never names a
   SKU; it only proposes a better string to match against the catalog.
6. On any miss, surface a clear "no match" outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..audit.eventlog import EventLog
from ..core.cart import Cart, CartLine
from ..core.inventory import ProductMatch, find_product
from ..core.money import money_str, to_money
from ..core.totals import compute_totals
from .flm_client import FLMConfig, normalize as flm_normalize
from .lemonade_client import LemonadeConfig, normalize as lemonade_normalize
from .parser import ParsedEvent, parse_event


CONFIDENCE_THRESHOLD = 0.8


@dataclass
class SupervisorConfig:
    tax_rate: Decimal = field(default_factory=lambda: to_money("0.15"))
    confidence_threshold: float = CONFIDENCE_THRESHOLD
    lemonade: LemonadeConfig = field(default_factory=LemonadeConfig)
    flm: FLMConfig = field(default_factory=FLMConfig)
    attendant_id: str = "attendant-1"


@dataclass
class SupervisorOutcome:
    """The result of one supervisor decision."""

    message: str
    state: dict[str, Any]
    needs_confirmation: bool = False
    candidate_match: ProductMatch | None = None
    candidate_quantity: int = 1
    done: bool = False
    tender_breakdown: dict[str, Any] | None = None


class Supervisor:
    def __init__(self, log: EventLog, config: SupervisorConfig | None = None):
        self.log = log
        self.config = config or SupervisorConfig()
        self.cart = Cart()
        self._opened = False
        self._voids_in_txn = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_transaction(self) -> None:
        if self._opened:
            return
        self.log.append(
            "transaction.open",
            {
                "attendant": self.config.attendant_id,
                "tax_rate": str(self.config.tax_rate),
            },
        )
        self._opened = True

    def handle_text(self, raw_text: str, *, confirmed: bool = False) -> SupervisorOutcome:
        self.open_transaction()
        event = parse_event(raw_text)

        if event.action == "noop":
            return self._outcome("")
        if event.action == "help":
            return self._outcome(
                "commands: <product>, N of those, remove that, remove <name>, "
                "cash <amount>, state, separate order, quit"
            )
        if event.action == "quit":
            return self._outcome("goodbye", done=True)
        if event.action == "state":
            return self._outcome("current transaction")
        if event.action == "clear":
            self.cart.clear()
            self.log.append("cart.clear", {})
            return self._outcome("started a separate order")
        if event.action == "remove_last":
            return self._remove_last()
        if event.action == "remove_named":
            return self._remove_named(event.text)
        if event.action == "set_last_quantity":
            return self._set_last_quantity(event.quantity)
        if event.action == "tender":
            return self._tender(event.amount or "0")
        if event.action == "close":
            return self._close()
        if event.action == "add_product":
            return self._add_product(event, confirmed=confirmed)

        return self._outcome(f"unknown action: {event.action}")

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _add_product(self, event: ParsedEvent, *, confirmed: bool) -> SupervisorOutcome:
        match = find_product(event.text)
        actor = "attendant"
        source: str = "typed"

        if match is None or match.confidence < self.config.confidence_threshold:
            # Try LLM fallbacks in order: Lemonade, then FLM. Each is a
            # *normalizer*; the result re-enters find_product.
            cart_shape = self._cart_shape()
            normalized = lemonade_normalize(event.text, cart_shape, self.config.lemonade)
            if normalized is None:
                normalized = flm_normalize(event.text, cart_shape, self.config.flm)

            if normalized is not None and normalized.candidate != event.text:
                normalized_match = find_product(normalized.candidate)
                if normalized_match is not None:
                    match = normalized_match
                    source = "model_proposed"

        if match is None:
            return self._outcome(
                f"no product matched '{event.text}'. try a clearer name."
            )

        if match.confidence < self.config.confidence_threshold and not confirmed:
            return SupervisorOutcome(
                message=(
                    f"low-confidence match: '{event.text}' → {match.name} "
                    f"at {match.confidence}. confirm?"
                ),
                state=self._state(),
                needs_confirmation=True,
                candidate_match=match,
                candidate_quantity=event.quantity,
            )

        # Decide actor with explicit precedence: a model-proposed match
        # *always* wins over the typed/fuzzy case because the source has
        # already been overridden upstream. Within model_proposed, the
        # confirmed flag distinguishes attendant-approved (agent_confirmed)
        # from auto-applied (agent_auto). For typed/fuzzy, confirmation of
        # a low-confidence match is the only way actor leaves "attendant".
        if source == "model_proposed":
            actor = "agent_confirmed" if confirmed else "agent_auto"
        elif confirmed and match.confidence < self.config.confidence_threshold:
            actor = "agent_confirmed"
            source = "fuzzy"

        line = CartLine(
            sku=match.sku,
            name=match.name,
            unit_price=match.price,
            taxable=match.taxable,
            quantity=event.quantity,
            actor=actor,  # type: ignore[arg-type]
            source=source,  # type: ignore[arg-type]
            confidence=match.confidence,
        )
        self.cart.add(line)
        self.log.append("cart.add", _line_payload(line))
        return self._outcome(f"added {match.name} x{event.quantity}")

    def _remove_last(self) -> SupervisorOutcome:
        removed = self.cart.remove_last()
        if removed is None:
            return self._outcome("nothing to remove")
        self._voids_in_txn += 1
        self.log.append("cart.remove_last", {"sku": removed.sku})
        return self._outcome(f"removed {removed.name}")

    def _remove_named(self, name: str) -> SupervisorOutcome:
        match = find_product(name)
        if match is None:
            return self._outcome(f"no product matched '{name}'")
        removed = self.cart.remove_sku(match.sku)
        if removed is None:
            return self._outcome(f"{match.name} is not in the cart")
        self._voids_in_txn += 1
        self.log.append("cart.remove_sku", {"sku": match.sku})
        return self._outcome(f"removed {match.name}")

    def _set_last_quantity(self, quantity: int) -> SupervisorOutcome:
        if not self.cart.last_sku:
            return self._outcome("no item to adjust")
        changed = self.cart.set_last_quantity(quantity)
        if not changed:
            return self._outcome("could not set quantity")
        self.log.append(
            "cart.set_quantity",
            {"sku": self.cart.last_sku, "quantity": quantity},
        )
        return self._outcome(f"set quantity to {quantity}")

    def _tender(self, amount: str) -> SupervisorOutcome:
        from ..core.cash import InsufficientTender, compute_change

        totals = compute_totals(self.cart, self.config.tax_rate)
        try:
            change = compute_change(totals.total, to_money(amount))
        except InsufficientTender as exc:
            return self._outcome(str(exc))

        self.log.append(
            "transaction.tender",
            {
                "tender": str(to_money(amount)),
                "total": money_str(totals.total),
                "change": money_str(change.change_due),
            },
        )
        return SupervisorOutcome(
            message=f"change due: ${money_str(change.change_due)}",
            state=self._state(),
            tender_breakdown=change.to_state(),
        )

    def _close(self) -> SupervisorOutcome:
        self.log.append("transaction.close", {})
        outcome = self._outcome("transaction closed", done=True)
        self.cart.clear()
        self._opened = False
        self._voids_in_txn = 0
        return outcome

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _outcome(self, message: str, *, done: bool = False) -> SupervisorOutcome:
        return SupervisorOutcome(message=message, state=self._state(), done=done)

    def _state(self) -> dict[str, Any]:
        totals = compute_totals(self.cart, self.config.tax_rate)
        return {
            "schema_version": 1,
            "items": [line.to_state() for line in self.cart.lines],
            **totals.to_state(),
            "voids_in_txn": self._voids_in_txn,
        }

    def _cart_shape(self) -> dict[str, Any]:
        return {"items": [line.to_state() for line in self.cart.lines]}


def _line_payload(line: CartLine) -> dict[str, Any]:
    return {
        "sku": line.sku,
        "name": line.name,
        "unit_price": money_str(line.unit_price),
        "taxable": line.taxable,
        "quantity": line.quantity,
        "actor": line.actor,
        "source": line.source,
        "confidence": line.confidence,
    }


__all__ = [
    "CONFIDENCE_THRESHOLD",
    "Supervisor",
    "SupervisorConfig",
    "SupervisorOutcome",
]
