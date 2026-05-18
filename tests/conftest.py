"""Shared pytest fixtures.

The cashier intentionally has no `pytest` dependency in `core/` itself,
but the tests do. Fixtures here keep each test isolated: a tmp event
log path, a tmp DB, and (optionally) a fresh-seeded inventory.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Iterator

import pytest

from lemonade_cashier.audit.eventlog import EventLog
from lemonade_cashier.core import inventory


SAMPLE_ROWS = [
    {"sku": "APL001", "name": "apple", "price": "0.75", "taxable": "true",
     "aliases": "apples|red apple"},
    {"sku": "BAN001", "name": "banana", "price": "0.50", "taxable": "true",
     "aliases": "bananas"},
    {"sku": "MLK001", "name": "milk 1 gal", "price": "3.49", "taxable": "false",
     "aliases": "milk|whole milk"},
    {"sku": "BRD001", "name": "bread loaf", "price": "2.99", "taxable": "false",
     "aliases": "bread"},
    {"sku": "EGG001", "name": "eggs dozen", "price": "4.25", "taxable": "false",
     "aliases": "eggs|dozen eggs"},
    {"sku": "COF001", "name": "coffee 12oz", "price": "8.99", "taxable": "true",
     "aliases": "coffee|ground coffee"},
    {"sku": "COK001", "name": "coca-cola 12oz", "price": "1.50", "taxable": "true",
     "aliases": "coke|coca cola|cola"},
]


@pytest.fixture()
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a fresh products.db path seeded with the sample rows."""

    csv_path = tmp_path / "products.csv"
    db_path = tmp_path / "products.db"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["sku", "name", "price", "taxable", "aliases"]
        )
        writer.writeheader()
        writer.writerows(SAMPLE_ROWS)

    # Point inventory at our temp DB everywhere.
    monkeypatch.setattr(inventory, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(inventory, "DEFAULT_CSV_PATH", csv_path)
    inventory.initialize_database(db_path=db_path, csv_path=csv_path, force=True)
    return db_path


@pytest.fixture()
def event_log(tmp_path: Path) -> EventLog:
    return EventLog(tmp_path / "events.jsonl")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip LC_* env vars so tests are reproducible."""

    for key in list(os.environ):
        if key.startswith("LC_"):
            monkeypatch.delenv(key, raising=False)
    yield
