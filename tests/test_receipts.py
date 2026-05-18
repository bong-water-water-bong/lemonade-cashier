"""Tests for receipt rendering and persistence."""

from __future__ import annotations

import json

from lemonade_cashier.agents.supervisor import Supervisor, SupervisorConfig
from lemonade_cashier.audit.receipts import render_state, save
from lemonade_cashier.audit.replay import replay_log
from lemonade_cashier.core.money import to_money


def test_receipt_text_contains_totals(seeded_db, event_log, tmp_path):
    sup = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.00")))
    sup.handle_text("apple")
    sup.handle_text("milk")
    state = sup._state()  # noqa: SLF001

    receipt = render_state(state, receipt_id="r-test")
    assert "Subtotal" in receipt.text
    assert "Total" in receipt.text

    path = save(receipt, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["receipt_id"] == "r-test"


def test_receipt_from_replay(seeded_db, event_log, tmp_path):
    sup = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.00")))
    sup.handle_text("apple")
    sup.handle_text("cash 1.00")

    state = replay_log(event_log.path).to_state()
    receipt = render_state(state, receipt_id="r-replay")
    assert "Total" in receipt.text
