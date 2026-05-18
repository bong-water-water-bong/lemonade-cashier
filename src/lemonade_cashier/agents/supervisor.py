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
from ..safety import lockout, pins, policy
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
    # If set, the supervisor will demand a PIN before high-risk close
    # and before removing a high-value cart line. Defaults to
    # "supervisor"; the matching PIN must exist in the pin store.
    supervisor_id: str = "supervisor"
    # Path to the PIN store JSON. None → use safety.pins.DEFAULT_PIN_STORE.
    pin_store: object = None  # Path | str | None at runtime


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
    # When set, the caller must prompt for a supervisor PIN and re-invoke
    # handle_text(...) with pin=<entered pin>. The handler that needed
    # the gate is named in ``pin_for_action`` so the CLI can show the
    # right prompt ("PIN to void large item:").
    needs_pin: bool = False
    pin_for_action: str | None = None


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

    def handle_text(
        self, raw_text: str, *, confirmed: bool = False, pin: str | None = None
    ) -> SupervisorOutcome:
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
            return self._remove_last(pin=pin)
        if event.action == "remove_named":
            return self._remove_named(event.text)
        if event.action == "set_last_quantity":
            return self._set_last_quantity(event.quantity)
        if event.action == "tender":
            return self._tender(event.amount or "0")
        if event.action == "close":
            return self._close()
        if event.action == "bag.seal":
            return self._bag_seal(event.amount or "0")
        if event.action == "bag.handoff":
            return self._bag_handoff(event.bag_id or "", event.carrier_id or "")
        if event.action == "bag.receive":
            return self._bag_receive(
                event.bag_id or "", event.carrier_id or "", event.amount or "0"
            )
        if event.action == "bag.reconcile":
            return self._bag_reconcile(event.bag_id or "")
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

    def _remove_last(self, *, pin: str | None = None) -> SupervisorOutcome:
        if not self.cart.last_sku:
            return self._outcome("nothing to remove")
        # Compute the line total of the would-be-removed item and ask
        # the policy layer if that triggers a supervisor-PIN gate.
        last_line = next(
            (line for line in self.cart.lines if line.sku == self.cart.last_sku),
            None,
        )
        if last_line is not None:
            policy_outcome = policy.can_void(last_line.line_total)
            if policy_outcome.requires_pin:
                pin_outcome = self._check_supervisor_pin(pin, "void_last_line")
                if pin_outcome is not None:
                    return pin_outcome
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

    def _close(self, *, pin: str | None = None) -> SupervisorOutcome:
        self.log.append("transaction.close", {})
        outcome = self._outcome("transaction closed", done=True)
        self.cart.clear()
        self._opened = False
        self._voids_in_txn = 0
        return outcome

    # ------------------------------------------------------------------
    # Supervisor-PIN gate
    # ------------------------------------------------------------------

    def _check_supervisor_pin(
        self, pin: str | None, action: str
    ) -> SupervisorOutcome | None:
        """Verify a supervisor PIN before a privileged action.

        Returns:
            ``None`` if no PIN gate is needed *or* the supplied PIN is
            correct — the caller should proceed.
            A populated :class:`SupervisorOutcome` (with ``needs_pin``
            or a denial message) otherwise — the caller must abort and
            return the outcome verbatim.
        """

        # First: is the supervisor account locked out?
        lockout_state = lockout.state_for(self.log, self.config.supervisor_id)
        if lockout_state.is_locked:
            return self._outcome(
                f"{self.config.supervisor_id!r} is locked out until "
                f"{lockout_state.locked_until!s}; cannot {action}"
            )

        if pin is None:
            return SupervisorOutcome(
                message=f"supervisor PIN required to {action}",
                state=self._state(),
                needs_pin=True,
                pin_for_action=action,
            )

        ok = pins.verify_pin(
            self.config.supervisor_id, pin, path=self.config.pin_store
        )
        try:
            lockout.record_pin_attempt(
                self.log, self.config.supervisor_id, success=ok
            )
        except lockout.LockoutError as exc:
            # Reached the lockout limit on this attempt; surface it.
            return self._outcome(f"PIN attempt rejected: {exc}")
        if not ok:
            return self._outcome("incorrect supervisor PIN")
        return None  # success — caller proceeds

    # ------------------------------------------------------------------
    # End-of-shift report
    # ------------------------------------------------------------------

    def report(self) -> dict[str, Any]:
        """Build and return the end-of-shift report from the event log."""

        from ..safety.report import build

        return build(self.log).state

    # ------------------------------------------------------------------
    # CIT bag handlers
    # ------------------------------------------------------------------

    def _bag_seal(self, amount: str) -> SupervisorOutcome:
        """`bag seal <amount>` — manifest broken into standard US denominations.

        Uses the same greedy-break algorithm as :func:`core.cash.compute_change`
        so the manifest *exactly* equals the requested amount, regardless of
        whether ``amount`` is a round dollar value. Previously this verb
        truncated to whole $100 bills, which made any non-round amount
        appear as a discrepancy at receive time — a fraudulent audit
        signal. The current implementation guarantees
        ``manifest.total == amount`` to four-decimal precision.

        For richer or non-US manifests use the bags API directly.
        """

        from ..core.money import MoneyError
        from ..safety.bags import BagError, DenominationCount, Manifest, seal_bag

        try:
            amt = to_money(amount)
        except MoneyError:
            return self._outcome(f"seal rejected: invalid amount {amount!r}")

        manifest = _build_us_manifest(amt)
        try:
            event = seal_bag(self.log, self.config.attendant_id, manifest)
        except BagError as exc:
            return self._outcome(f"seal rejected: {exc}")
        bag_id = str(event.payload.get("bag_id", ""))
        return self._outcome(f"sealed bag {bag_id} for ${money_str(amt)}")

    def _bag_handoff(self, bag_id: str, carrier_id: str) -> SupervisorOutcome:
        from ..safety.bags import BagError, handoff_bag

        if not bag_id or not carrier_id:
            return self._outcome("usage: bag handoff <bag_id> <carrier_id>")
        try:
            handoff_bag(
                self.log,
                bag_id,
                attendant_id=self.config.attendant_id,
                carrier_id=carrier_id,
            )
        except BagError as exc:
            return self._outcome(f"handoff rejected: {exc}")
        return self._outcome(f"handed off {bag_id} to {carrier_id}")

    def _bag_receive(
        self, bag_id: str, carrier_id: str, counted_amount: str
    ) -> SupervisorOutcome:
        """Carrier records the counted total, then we automatically emit
        reconciled or discrepancy based on the comparison to the
        manifest. This is convenience: a real counting authority would
        call receive_bag and then reconcile_bag / flag_discrepancy on
        their own."""

        from ..core.money import MoneyError
        from ..safety.bags import (
            BagError,
            bags_from_events,
            flag_discrepancy,
            receive_bag,
            reconcile_bag,
        )

        if not bag_id or not carrier_id:
            return self._outcome("usage: bag receive <bag_id> <carrier_id> <counted>")
        try:
            counted = to_money(counted_amount)
        except MoneyError:
            return self._outcome(f"receive rejected: invalid amount {counted_amount!r}")
        try:
            receive_bag(self.log, bag_id, carrier_id=carrier_id, counted_total=counted)
        except BagError as exc:
            return self._outcome(f"receive rejected: {exc}")

        # Decide reconciled vs discrepancy by looking at the freshly
        # updated event log — the manifest_total is recorded on the
        # original cit.bag.sealed event.
        snapshot = bags_from_events(self.log.read_all()).get(bag_id)
        if snapshot is None or snapshot.manifest_total is None:
            return self._outcome(f"received {bag_id} but no manifest found")
        delta = counted - snapshot.manifest_total
        if delta == Decimal("0.0000"):
            reconcile_bag(self.log, bag_id)
            return self._outcome(f"reconciled {bag_id}: ${money_str(counted)} matches manifest")
        flag_discrepancy(self.log, bag_id, delta=delta)
        sign = "over" if delta > 0 else "short"
        return self._outcome(
            f"discrepancy on {bag_id}: counted ${money_str(counted)} vs manifest "
            f"${money_str(snapshot.manifest_total)} ({sign} ${money_str(abs(delta))})"
        )

    def _bag_reconcile(self, bag_id: str) -> SupervisorOutcome:
        from ..safety.bags import BagError, reconcile_bag

        if not bag_id:
            return self._outcome("usage: bag reconcile <bag_id>")
        try:
            reconcile_bag(self.log, bag_id)
        except BagError as exc:
            return self._outcome(f"reconcile rejected: {exc}")
        return self._outcome(f"reconciled {bag_id}")

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


def _build_us_manifest(amount: Decimal):
    """Greedy-break ``amount`` into US denominations as a bag manifest.

    Uses the same denomination set and algorithm as
    :func:`core.cash.compute_change` so the manifest total *exactly*
    equals ``amount``. We don't reuse compute_change directly because
    its return type (ChangeBreakdown) isn't what bags wants — but the
    math is identical.
    """

    from ..core.cash import DEFAULT_DENOMINATIONS
    from ..core.money import to_display, ZERO as MONEY_ZERO
    from ..safety.bags import DenominationCount, Manifest

    remaining = to_display(amount)
    entries: list[DenominationCount] = []
    for denom in sorted(DEFAULT_DENOMINATIONS, reverse=True):
        if remaining < denom:
            continue
        count = int(remaining // denom)
        if count == 0:
            continue
        entries.append(DenominationCount(denomination=denom, count=count))
        remaining -= denom * count
        remaining = to_display(remaining)
        if remaining == MONEY_ZERO:
            break
    return Manifest(entries=tuple(entries))


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
