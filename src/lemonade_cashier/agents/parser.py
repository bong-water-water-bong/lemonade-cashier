"""Rule-based parser: deterministic, no model needed.

This is the **primary** parser. Even when an LLM is configured, the
supervisor calls this first. The parser converts a raw text line into a
:class:`ParsedEvent` whose ``action`` drives the cashier's state
machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

NUMBER_WORDS: Final[dict[str, int]] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "a": 1,
    "an": 1,
}

QUIT_PHRASES: Final = frozenset({"quit", "exit", "bye"})
STATE_PHRASES: Final = frozenset({"state", "total", "cart", "show", "show cart"})
CLEAR_PHRASES: Final = frozenset(
    {"separate order", "new order", "next order", "next customer", "clear"}
)
REMOVE_LAST_PHRASES: Final = frozenset(
    {
        "remove that",
        "remove last",
        "delete that",
        "void that",
        "scratch that",
        "don't include this",
        "dont include this",
        "do not include this",
    }
)
HELP_PHRASES: Final = frozenset({"help", "?"})


@dataclass(frozen=True)
class ParsedEvent:
    action: str
    text: str = ""
    quantity: int = 1
    sku: str | None = None
    amount: str | None = None  # money string ("5.00") for tender actions
    bag_id: str | None = None
    carrier_id: str | None = None
    args: tuple[str, ...] = ()  # extra positional tokens (e.g. denominations)


def parse_event(raw_text: str) -> ParsedEvent:
    """Convert a raw input line into a :class:`ParsedEvent`."""

    text = raw_text.strip().lower()
    if not text:
        return ParsedEvent(action="noop")

    if text in QUIT_PHRASES:
        return ParsedEvent(action="quit")
    if text in HELP_PHRASES:
        return ParsedEvent(action="help")
    if text in STATE_PHRASES:
        return ParsedEvent(action="state")
    if text in CLEAR_PHRASES:
        return ParsedEvent(action="clear")
    if text in REMOVE_LAST_PHRASES:
        return ParsedEvent(action="remove_last")

    if text == "cash" or text == "tender" or text.startswith(("cash ", "tender ")):
        # The amount is everything after the verb. Reject empty or
        # non-numeric amounts ("cash", "cash $", "tender abc") so the
        # supervisor doesn't silently treat them as $0.00.
        parts = text.split(maxsplit=1)
        amount = parts[1].lstrip("$").strip() if len(parts) == 2 else ""
        if amount:
            from decimal import Decimal, InvalidOperation
            try:
                Decimal(amount)
                return ParsedEvent(action="tender", amount=amount)
            except InvalidOperation:
                pass
        return ParsedEvent(action="help")

    if text.startswith("remove "):
        candidate = text[len("remove ") :].strip()
        if candidate:
            return ParsedEvent(action="remove_named", text=candidate)

    if text in {"close", "done", "checkout"}:
        return ParsedEvent(action="close")

    # CIT bag verbs. Grammar:
    #   bag seal <amount>                            (auto-generated bag_id + seal_id)
    #   bag handoff <bag_id> <carrier_id>
    #   bag receive <bag_id> <carrier_id> <counted>
    #   bag reconcile <bag_id>
    #
    # Critically: only the FOUR known bag verbs intercept. Anything else
    # ("bag of chips", "bag of coffee" — both valid product aliases)
    # falls through to add_product so the inventory lookup can run.
    # See the cashier-agent-recommendations memo: schema-bounded matching
    # beats vibes-bounded matching; the parser must not pre-empt the
    # catalog.
    _BAG_VERBS = {"seal", "handoff", "receive", "reconcile"}
    if text.startswith("bag "):
        tokens = text.split()
        if len(tokens) >= 2 and tokens[1] in _BAG_VERBS:
            verb = tokens[1]
            rest = tokens[2:]
            if verb == "seal" and len(rest) == 1:
                amount = rest[0].lstrip("$")
                return ParsedEvent(action="bag.seal", amount=amount)
            if verb == "handoff" and len(rest) == 2:
                return ParsedEvent(
                    action="bag.handoff", bag_id=rest[0], carrier_id=rest[1]
                )
            if verb == "receive" and len(rest) == 3:
                return ParsedEvent(
                    action="bag.receive",
                    bag_id=rest[0],
                    carrier_id=rest[1],
                    amount=rest[2].lstrip("$"),
                )
            if verb == "reconcile" and len(rest) == 1:
                return ParsedEvent(action="bag.reconcile", bag_id=rest[0])
            return ParsedEvent(action="help")
        # Not a bag verb — fall through to add_product so "bag of chips"
        # can still resolve via the alias table.

    words = text.split()
    if len(words) >= 3 and words[-2:] == ["of", "those"]:
        qty = _quantity_from_word(words[0])
        if qty is not None:
            return ParsedEvent(action="set_last_quantity", quantity=qty)

    if len(words) >= 2:
        qty = _quantity_from_word(words[0])
        if qty is not None:
            return ParsedEvent(
                action="add_product",
                text=" ".join(words[1:]),
                quantity=qty,
            )

    return ParsedEvent(action="add_product", text=text)


def _quantity_from_word(word: str) -> int | None:
    if word.isdigit():
        n = int(word)
        return n if 1 <= n <= 999 else None
    return NUMBER_WORDS.get(word)


__all__ = ["ParsedEvent", "parse_event"]
