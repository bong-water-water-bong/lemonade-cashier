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
