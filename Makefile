# Lemonade Cashier — convenience targets.
# All targets work with plain Python; no virtualenv required for the core.

PYTHON ?= python3

.PHONY: help install dev test test-cov lint type fmt run seed replay clean

help:
	@echo "Targets:"
	@echo "  make install     Install the package (editable) with dev extras"
	@echo "  make test        Run the test suite"
	@echo "  make test-cov    Run tests with coverage"
	@echo "  make lint        Run ruff"
	@echo "  make type        Run mypy"
	@echo "  make fmt         Run ruff format"
	@echo "  make run         Start the cashier CLI"
	@echo "  make seed        Seed the local product database from CSV"
	@echo "  make replay LOG=path  Replay a JSONL event log"
	@echo "  make clean       Remove build artifacts and caches"

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

test-cov:
	$(PYTHON) -m pytest --cov=lemonade_cashier --cov-report=term-missing

lint:
	$(PYTHON) -m ruff check src tests

type:
	$(PYTHON) -m mypy

fmt:
	$(PYTHON) -m ruff format src tests

run:
	$(PYTHON) -m lemonade_cashier.cli

seed:
	$(PYTHON) -m lemonade_cashier.core.inventory --seed

replay:
	$(PYTHON) -m lemonade_cashier.audit.replay $(LOG)

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
