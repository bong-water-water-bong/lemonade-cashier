# Runbook

> Local commands, environment variables, port configurations, and CLI workflows for testing, building, and running 'lemonade-cashier'.

## Local Commands & Makefile

The project uses a standard [Makefile](file:///home/bcloud/lemonade-cashier/Makefile) for convenience task runners. Python 3.11+ is required.

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

---

## Environment Variables

The cashier suite respects the following `LC_*` environment variables:

| Variable Name | Default Value | Purpose / Description |
|---|---|---|
| `LC_EVENT_LOG` | `data/events/cashier.jsonl` | Path to the append-only till transaction log. |
| `LC_RECEIPT_DIR` | `data/receipts` | Target directory for generated text receipts. |
| `LC_STORE_ID` | `tie-dye-farms` | Identifier for the local retail outlet. |
| `LC_TAX_RATE` | `0.15` | Default sales tax rate applied to checkout. |
| `LC_LEMONADE_ENABLED` | `false` | Enable/disable LLM-assisted parser fallback. |
| `LC_LEMONADE_URL` | `http://127.0.0.1:8000` | Local address to reach Lemonade Server. |
| `LC_LEMONADE_MODEL` | `Qwen3-4B-GGUF` | Target model name on the Lemonade Server. |
| `LC_LEMONADE_TIMEOUT_SEC`| `2.0` | Timeout threshold for LLM-assisted requests. |
| `LC_FLM_ENABLED` | `false` | Enable/disable FastFlowLM parsing on NPU. |
| `LC_FLM_URL` | `http://127.0.0.1:11434` | Address of local FastFlowLM (Ollama compat). |
| `LC_FLM_MODEL` | `qwen3:4b` | Model name on the FastFlowLM server. |
| `LC_FLM_TIMEOUT_SEC` | `2.0` | Timeout threshold for FastFlowLM. |
| `LC_RISK_WARN` | `0.4` | Threshold above which transaction is flagged in UI. |
| `LC_RISK_BLOCK` | `0.7` | Threshold above which void/refund requires supervisor PIN. |
| `LC_CIT_TWO_PERSON_THRESHOLD` | `200.00` | Cash drops above this amount require a witness signature. |
| `LC_RUN_LIVE_MODEL` | `0` | Set to `1` to run benchmark tests against live models. |

---

## Port Assignments

The local cashier stack relies on dedicated port numbers to prevent workstation collisions:

| Port | Service / Application | Description |
|---|---|---|
| **`13400`** | Embedded `lemond` | Local LLM-assisted parsing subprocess manager, isolated for cashier. |
| **`13305`** | System-wide `lemond` | Core Lemonade Server runtime API default port. |
| **`8000`** | Dev server API | Lemonade Server fallback default port. |
| **`11434`** | Ollama / FastFlowLM | FastFlowLM NPU/CPU local API engine port. |

---

## Related

- [[README]] — Project wiki entry point
- [[architecture]] — High-level architecture and event envelope
- [[conventions]] — Python coding style and development standards
- [[agents]] — Hard rules, safety policy, and safe zones
