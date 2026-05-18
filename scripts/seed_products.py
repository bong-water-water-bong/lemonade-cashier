"""Seed the product database from the CSV (idempotent, forces refresh)."""

from __future__ import annotations

from lemonade_cashier.core.inventory import (
    DEFAULT_DB_PATH,
    all_products,
    initialize_database,
)


def main() -> None:
    initialize_database(force=True)
    print(f"seeded {len(all_products())} products at {DEFAULT_DB_PATH}")


if __name__ == "__main__":
    main()
