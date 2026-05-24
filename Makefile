# Lemonade Cashier — convenience targets.
# All targets work with plain Python; no virtualenv required for the core.

PYTHON ?= python3

.PHONY: all help install test test-cov lint type fmt run seed replay clean lemond-setup lemond-start lemond-stop

all: lint type test

help:
	@echo "Targets:"
	@echo "  make install       Install the package (editable) with dev extras"
	@echo "  make test          Run the test suite"
	@echo "  make test-cov      Run tests with coverage"
	@echo "  make lint          Run ruff"
	@echo "  make type          Run mypy"
	@echo "  make fmt           Run ruff format"
	@echo "  make run           Start the cashier CLI"
	@echo "  make seed          Seed the local product database from CSV"
	@echo "  make replay LOG=path  Replay a JSONL event log"
	@echo "  make lemond-setup  Download and extract the embedded lemond runtime"
	@echo "  make lemond-start  Start the embedded lemond on port 13400"
	@echo "  make lemond-stop   Stop the embedded lemond"
	@echo "  make clean         Remove build artifacts and caches"

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

lemond-setup:
	@scripts/setup_lemond.sh

lemond-start:
	@$(PYTHON) -c "from lemonade_cashier.integrations.lemond_process import LemondProcess; \
	import signal, sys; p = LemondProcess(); p.start(); \
	ok = p.wait_healthy(); \
	print('lemond running on port', p.port) if ok else (print('lemond failed to start'), sys.exit(1)); \
	signal.pause()"

lemond-stop:
	@$(PYTHON) -c "import urllib.request; \
	urllib.request.urlopen('http://127.0.0.1:13400/internal/shutdown', timeout=3)" 2>/dev/null \
	&& echo "lemond stopped" || echo "lemond not running"

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
