"""Inventory: SQLite-backed product catalog with alias-aware matching.

A product has a primary ``name`` and zero or more pipe-separated
``aliases`` ("coke|coca cola|coca-cola"). Lookup tries:

1. **Exact name match** → confidence 1.0.
2. **Exact alias match** → confidence 0.95.
3. **Substring match** (name or alias contains query, or vice versa) →
   confidence 0.86.
4. **Fuzzy match** (:class:`difflib.SequenceMatcher`) → ratio.

Below ``DEFAULT_CONFIDENCE_FLOOR`` the lookup returns ``None`` and the
caller must surface the miss to the attendant; it must never guess.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Final

from .money import to_money

PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
DATA_DIR: Final = PROJECT_ROOT / "data"
DEFAULT_DB_PATH: Final = DATA_DIR / "products.db"
DEFAULT_CSV_PATH: Final = DATA_DIR / "sample_products.csv"
DEFAULT_CONFIDENCE_FLOOR: Final = 0.55


@dataclass(frozen=True)
class Product:
    """A row in the product catalog."""

    sku: str
    name: str
    price: Decimal
    taxable: bool
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductMatch:
    """The result of a single :func:`find_product` lookup."""

    sku: str
    name: str
    price: Decimal
    taxable: bool
    confidence: float
    matched_via: str  # "exact" | "alias" | "substring" | "fuzzy"


def initialize_database(
    db_path: Path = DEFAULT_DB_PATH,
    csv_path: Path = DEFAULT_CSV_PATH,
    *,
    force: bool = False,
) -> None:
    """Create and seed the product DB from ``csv_path``.

    Idempotent: if the products table already has rows and ``force`` is
    False, this is a no-op.
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                sku TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price TEXT NOT NULL,
                taxable INTEGER NOT NULL,
                aliases TEXT NOT NULL DEFAULT ''
            )
            """
        )
        if force:
            connection.execute("DELETE FROM products")
        count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count and not force:
            return
        if not csv_path.exists():
            return
        with csv_path.open(newline="", encoding="utf-8") as product_file:
            rows = csv.DictReader(product_file)
            connection.executemany(
                "INSERT OR REPLACE INTO products "
                "(sku, name, price, taxable, aliases) VALUES (?, ?, ?, ?, ?)",
                (_csv_row_to_db(row) for row in rows),
            )


def all_products(db_path: Path = DEFAULT_DB_PATH) -> list[Product]:
    """Return every row from the products table, ordered by SKU.

    The explicit ORDER BY is what makes :func:`find_product` deterministic
    on ties: when two products score identically, the first one in SKU
    order wins. Without the ORDER BY, SQLite is free to return rows in
    any order and the "best match" becomes non-reproducible.
    """

    initialize_database(db_path)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT sku, name, price, taxable, aliases FROM products "
            "ORDER BY sku"
        ).fetchall()
    return [_row_to_product(row) for row in rows]


def find_product(
    query: str,
    db_path: Path = DEFAULT_DB_PATH,
    *,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> ProductMatch | None:
    """Return the best :class:`ProductMatch` for ``query`` or ``None``."""

    cleaned = query.strip().lower()
    if not cleaned:
        return None

    products = all_products(db_path)
    if not products:
        return None

    best: ProductMatch | None = None
    for product in products:
        candidate = _score_product(cleaned, product)
        if candidate is None:
            continue
        if best is None or candidate.confidence > best.confidence:
            best = candidate

    if best is None or best.confidence < confidence_floor:
        return None
    return best


def _score_product(query: str, product: Product) -> ProductMatch | None:
    name = product.name.lower()
    aliases = [a.lower() for a in product.aliases if a]

    if query == name:
        return _match(product, 1.0, "exact")
    if query in aliases:
        return _match(product, 0.95, "alias")

    candidate_score = 0.0
    candidate_via = "fuzzy"
    if query in name or name in query:
        candidate_score = 0.86
        candidate_via = "substring"
    else:
        for alias in aliases:
            if query in alias or alias in query:
                candidate_score = 0.86
                candidate_via = "substring"
                break

    fuzzy_score = SequenceMatcher(None, query, name).ratio()
    for alias in aliases:
        fuzzy_score = max(
            fuzzy_score, SequenceMatcher(None, query, alias).ratio()
        )

    # Whichever scorer wins also names the provenance. Without this the
    # match could be reported as "substring" when the fuzzy score was
    # actually higher (and vice versa).
    if fuzzy_score > candidate_score:
        final, matched_via = fuzzy_score, "fuzzy"
    else:
        final, matched_via = candidate_score, candidate_via
    if final == 0.0:
        return None
    return _match(product, round(final, 2), matched_via)


def _match(product: Product, confidence: float, via: str) -> ProductMatch:
    return ProductMatch(
        sku=product.sku,
        name=product.name,
        price=product.price,
        taxable=product.taxable,
        confidence=confidence,
        matched_via=via,
    )


def _csv_row_to_db(row: dict[str, str]) -> tuple[str, str, str, int, str]:
    return (
        row["sku"].strip(),
        row["name"].strip().lower(),
        str(to_money(row["price"])),
        1 if row["taxable"].strip().lower() == "true" else 0,
        row.get("aliases", "").strip().lower(),
    )


def _row_to_product(row: tuple[str, str, str, int, str]) -> Product:
    aliases_field = row[4] or ""
    aliases = tuple(a.strip() for a in aliases_field.split("|") if a.strip())
    return Product(
        sku=row[0],
        name=row[1],
        price=to_money(row[2]),
        taxable=bool(row[3]),
        aliases=aliases,
    )


def main() -> None:  # pragma: no cover — CLI helper, exercised by Makefile
    """``python -m lemonade_cashier.core.inventory --seed`` (idempotent)."""

    import sys

    if "--seed" in sys.argv:
        initialize_database(force=True)
        print(f"Seeded {len(all_products())} products at {DEFAULT_DB_PATH}")
    elif "--list" in sys.argv:
        for product in all_products():
            print(
                f"{product.sku:8s}  ${product.price:>6}  "
                f"{'tax' if product.taxable else '   '}  {product.name}"
            )
    else:
        print(
            "usage: python -m lemonade_cashier.core.inventory [--seed | --list]"
        )


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = [
    "DEFAULT_CONFIDENCE_FLOOR",
    "DEFAULT_CSV_PATH",
    "DEFAULT_DB_PATH",
    "Product",
    "ProductMatch",
    "all_products",
    "find_product",
    "initialize_database",
]
