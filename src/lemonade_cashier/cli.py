"""Lemonade Cashier CLI entrypoint.

Run with::

    python -m lemonade_cashier.cli            # uses default data paths
    LC_EVENT_LOG=/tmp/till.jsonl python -m lemonade_cashier.cli
    python -m lemonade_cashier                # also works (see __main__.py)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .agents.flm_client import FLMConfig
from .agents.lemonade_client import LemonadeConfig
from .agents.supervisor import Supervisor, SupervisorConfig, SupervisorOutcome
from .audit.eventlog import EventLog
from .audit.receipts import Receipt, save
from .core.inventory import initialize_database
from .core.money import to_money

logger = logging.getLogger(__name__)

DEFAULT_EVENT_LOG = "data/events/cashier.jsonl"
DEFAULT_RECEIPT_DIR = "data/receipts"

BANNER = (
    "Lemonade Cashier — local, offline, deterministic. type 'help' for commands, 'quit' to exit."
)


def _config_from_env() -> tuple[Path, Path, str, SupervisorConfig]:
    log_path = Path(os.environ.get("LC_EVENT_LOG", DEFAULT_EVENT_LOG))
    receipt_dir = Path(os.environ.get("LC_RECEIPT_DIR", DEFAULT_RECEIPT_DIR))
    store_id = os.environ.get("LC_STORE_ID", "tie-dye-farms")

    tax_rate = to_money(os.environ.get("LC_TAX_RATE", "0.15"))

    lemonade = LemonadeConfig(
        url=os.environ.get("LC_LEMONADE_URL", "http://127.0.0.1:8000"),
        model=os.environ.get("LC_LEMONADE_MODEL", "Qwen3-4B-GGUF"),
        timeout_sec=float(os.environ.get("LC_LEMONADE_TIMEOUT_SEC", "2.0")),
        enabled=_env_bool("LC_LEMONADE_ENABLED", default=False),
    )
    flm = FLMConfig(
        url=os.environ.get("LC_FLM_URL", "http://127.0.0.1:11434"),
        model=os.environ.get("LC_FLM_MODEL", "qwen3:4b"),
        timeout_sec=float(os.environ.get("LC_FLM_TIMEOUT_SEC", "2.0")),
        enabled=_env_bool("LC_FLM_ENABLED", default=False),
    )
    config = SupervisorConfig(tax_rate=tax_rate, lemonade=lemonade, flm=flm)
    return log_path, receipt_dir, store_id, config


def _env_bool(name: str, *, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:  # pragma: no cover — interactive loop, exercised by smoke test
    log_path, receipt_dir, store_id, config = _config_from_env()
    initialize_database()
    log = EventLog(log_path, store_id=store_id)
    supervisor = Supervisor(log, config)

    print(BANNER)
    print(f"event log: {log_path}")
    print(f"receipts:  {receipt_dir}")
    print()

    while True:
        try:
            raw = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        outcome = supervisor.handle_text(raw)

        if outcome.needs_confirmation and outcome.candidate_match is not None:
            match = outcome.candidate_match
            answer = (
                input(f"add {match.name} at ${match.price} ({match.confidence})? y/n > ")
                .strip()
                .lower()
            )
            if answer == "y":
                outcome = supervisor.handle_text(
                    f"{outcome.candidate_quantity} {match.name}"
                    if outcome.candidate_quantity > 1
                    else match.name,
                    confirmed=True,
                    source_hint=outcome.candidate_source,
                )

        _print_outcome(outcome)

        if outcome.done and not supervisor.cart.lines:
            # Render and save a receipt at clean close.
            from .audit.replay import replay_log

            try:
                state = replay_log(log_path).to_state()
            except Exception:
                logger.error(
                    "replay failed for log %s; falling back to live state",
                    log_path,
                    exc_info=True,
                )
                state = outcome.state
            receipt = render_state_safe(state)
            saved_path = save(receipt, receipt_dir)
            print(f"receipt: {saved_path}")
            break


def render_state_safe(state: dict[str, object]) -> Receipt:
    """Thin wrapper around :func:`audit.receipts.render_state`."""

    from .audit.receipts import render_state

    return render_state(state)


def _print_outcome(outcome: SupervisorOutcome) -> None:
    print(outcome.message)
    if outcome.tender_breakdown:
        print(json.dumps(outcome.tender_breakdown, indent=2))
    if outcome.state.get("items"):
        print(json.dumps(outcome.state, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["main"]
