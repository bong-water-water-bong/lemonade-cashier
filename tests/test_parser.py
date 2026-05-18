"""Tests for the rule-based parser."""

from __future__ import annotations

from lemonade_cashier.agents.parser import parse_event


def test_product_text_becomes_add_product():
    event = parse_event("apple")
    assert event.action == "add_product"
    assert event.text == "apple"
    assert event.quantity == 1


def test_quantity_phrase():
    event = parse_event("two of those")
    assert event.action == "set_last_quantity"
    assert event.quantity == 2


def test_leading_quantity_word():
    event = parse_event("three apples")
    assert event.action == "add_product"
    assert event.quantity == 3
    assert event.text == "apples"


def test_leading_quantity_digit():
    event = parse_event("3 apples")
    assert event.action == "add_product"
    assert event.quantity == 3


def test_remove_phrases():
    for phrase in ["remove that", "void that", "scratch that", "don't include this"]:
        assert parse_event(phrase).action == "remove_last", phrase


def test_remove_named():
    event = parse_event("remove apple")
    assert event.action == "remove_named"
    assert event.text == "apple"


def test_separate_order():
    assert parse_event("separate order").action == "clear"


def test_tender():
    event = parse_event("cash 5.00")
    assert event.action == "tender"
    assert event.amount == "5.00"


def test_tender_strips_dollar():
    event = parse_event("cash $5.00")
    assert event.action == "tender"
    assert event.amount == "5.00"


def test_tender_rejects_empty_amount():
    # "cash $" or "cash abc" should not silently parse as $0.00 tender.
    assert parse_event("cash $").action == "help"
    assert parse_event("cash abc").action == "help"
    assert parse_event("tender ").action == "help"


def test_close():
    assert parse_event("close").action == "close"
    assert parse_event("done").action == "close"


def test_empty():
    assert parse_event("").action == "noop"
    assert parse_event("   ").action == "noop"


def test_quit_and_state():
    assert parse_event("quit").action == "quit"
    assert parse_event("exit").action == "quit"
    assert parse_event("state").action == "state"
    assert parse_event("cart").action == "state"
