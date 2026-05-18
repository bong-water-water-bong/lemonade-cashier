"""Tests for product lookup, aliases, and the confidence floor."""

from __future__ import annotations

from lemonade_cashier.core.inventory import find_product


def test_exact_name_match(seeded_db):
    match = find_product("apple", db_path=seeded_db)
    assert match is not None
    assert match.sku == "APL001"
    assert match.confidence == 1.0
    assert match.matched_via == "exact"


def test_alias_match_is_high_confidence(seeded_db):
    match = find_product("coke", db_path=seeded_db)
    assert match is not None
    assert match.sku == "COK001"
    assert match.confidence >= 0.9
    assert match.matched_via == "alias"


def test_substring_match(seeded_db):
    match = find_product("apples", db_path=seeded_db)
    assert match is not None
    assert match.sku == "APL001"
    assert match.confidence >= 0.86


def test_below_floor_returns_none(seeded_db):
    # "xyz" should not match anything plausibly.
    assert find_product("xyz123", db_path=seeded_db) is None


def test_empty_query_returns_none(seeded_db):
    assert find_product("", db_path=seeded_db) is None
    assert find_product("   ", db_path=seeded_db) is None
