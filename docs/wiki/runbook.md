# Runbook

> Local commands, environment variables, port configurations, and CLI workflows for testing, building, and running 'lemonade-cashier'.

## Local Commands & Makefile

The project uses a standard [Makefile](../../Makefile) for convenience task runners. Python 3.11+ is required.

### Quality Verification
```bash
# Run lint, type check, and tests in sequence
make all

# Run Ruff code analysis
make lint

# Run Mypy static type verification
make type

# Run the pytest suite
make test
```

### Setup & Local Server commands
```bash
# Seed the local SQLite product database from sample CSV
make seed

# Run the cashier CLI for manual testing
make run

# Download lemonade-embeddable 10.6.0 tarball resources
make lemond-setup

# Start the embedded lemond daemon process on port 13400
make lemond-start

# Stop the embedded lemond process
make lemond-stop
```

#### Code & File Attributions
- `make seed`: Seeds from `data/sample_products.csv` into `data/products.db` using the initialization routines in [inventory.py](../../src/lemonade_cashier/core/inventory.py).
- `make run`: Executes the CLI loop defined in [__main__.py](../../src/lemonade_cashier/__main__.py) and [cli.py](../../src/lemonade_cashier/cli.py).
- `make lemond-setup`: Invokes [setup_lemond.sh](../../scripts/setup_lemond.sh) to download and extract `lemond` version `10.6.0`.
- `make lemond-start` / `lemond-stop`: Manages the local `lemond` subprocess via [lemond_process.py](../../src/lemonade_cashier/integrations/lemond_process.py).

---

## Environment Variables

The cashier suite respects the following `LC_*` environment variables loaded via [cli.py](../../src/lemonade_cashier/cli.py):

| Variable Name | Default Value | Purpose / Description |
|---|---|---|
| `LC_EVENT_LOG` | `data/events/cashier.jsonl` | Path to the append-only till transaction log. |
| `LC_RECEIPT_DIR` | `data/receipts` | Target directory for generated text receipts. |
| `LC_STORE_ID` | `tie-dye-farms` | Identifier for the local retail outlet. |
| `LC_TAX_RATE` | `0.15` | Default sales tax rate applied to checkout. |
| `LC_LEMONADE_ENABLED` | `false` | Enable/disable LLM-assisted parser fallback. |
| `LC_LEMONADE_URL` | `http://127.0.0.1:13305` | Local address to reach system-wide Lemonade Server. |
| `LC_LEMONADE_MODEL` | `granite-3.3-2b-instruct-GGUF-Q4_K_M` | Target model name on the Lemonade Server. |
| `LC_LEMONADE_TIMEOUT_SEC`| `2.0` | Timeout threshold for LLM-assisted requests. |
| `LC_FLM_ENABLED` | `false` | Enable/disable FastFlowLM parsing on NPU. |
| `LC_FLM_URL` | `http://127.0.0.1:11434` | Address of local FastFlowLM (Ollama compat). |
| `LC_FLM_MODEL` | `qwen3:4b` | Model name on the FastFlowLM server. |
| `LC_FLM_TIMEOUT_SEC` | `2.0` | Timeout threshold for FastFlowLM. |

### Future/Roadmap Environment Variables (Unimplemented)
The following variables are documented as future design policies from [AGENTS.md](../../AGENTS.md) / [policy.py](../../src/lemonade_cashier/safety/policy.py) and are **not parsed** or active in the current prototype codebase:
- `LC_RISK_WARN` (default: `0.4`): Intended threshold for UI risk warnings.
- `LC_RISK_BLOCK` (default: `0.7`): Intended threshold to block closing high-risk transactions. (Note: PIN checks gate on line-item currency magnitude, not risk score).
- `LC_CIT_TWO_PERSON_THRESHOLD` (default: `200.00`): Cash-in-transit witness threshold is currently hardcoded as `DEFAULT_TWO_PERSON_THRESHOLD = Decimal("200.00")` in [cit.py](../../src/lemonade_cashier/safety/cit.py) without environment overrides.
- `LC_RUN_LIVE_MODEL` (default: `0`): Benchmarking toggle for live LLM execution.

---

## Port Assignments

The local cashier stack relies on the following dedicated port numbers to prevent workstation collisions:

| Port | Service / Application | Code Reference / Source |
|---|---|---|
| **`13400`** | Embedded `lemond` | Port for the local subprocess daemon managed by [lemond_process.py](../../src/lemonade_cashier/integrations/lemond_process.py#L48). |
| **`13305`** | System-wide `lemond` | Programmatic default server API port defined in [lemonade_client.py](../../src/lemonade_cashier/agents/lemonade_client.py#L74) (`LemonadeConfig.url`). |
| **`8000`** | Dev server API (historical) | Legacy/historical default API port referenced in agent stubs/comments. |
| **`11434`** | Ollama / FastFlowLM | FastFlowLM port configured in [cli.py](../../src/lemonade_cashier/cli.py#L49) (`FLMConfig.url`). |

---

## Related

- [README](README.md) — Project wiki entry point
- [architecture](architecture.md) — High-level architecture and event envelope
- [conventions](conventions.md) — Python coding style and development standards
- [agents](agents.md) — Hard rules, safety policy, and safe zones
