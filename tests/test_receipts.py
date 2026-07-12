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
    state = sup._state()

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


class TestVATReceipt:
    """Per-line VAT and rate-bucket summary on receipts."""

    def test_zero_vat_shows_transparent_summary(self, seeded_db, event_log):
        """Zero-rated VAT: transparent $0.00 breakdown visible."""
        sup = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.00")))
        sup.handle_text("apple")
        sup.handle_text("milk")
        state = sup._state()
        receipt = render_state(state, receipt_id="r-zero")
        assert "VAT breakdown" in receipt.text
        assert "0%" in receipt.text

    def test_single_rate_shows_per_line_and_summary(self, seeded_db, event_log):
        """15% VAT: taxable lines show per-item VAT, footer has rate-bucket summary."""
        sup = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.15")))
        sup.handle_text("apple")  # taxable
        state = sup._state()
        receipt = render_state(state, receipt_id="r-vat15")
        assert "VAT 15%" in receipt.text
        assert "VAT breakdown" in receipt.text

    def test_backward_compat_no_vat_data(self, seeded_db, event_log):
        """Receipt without per-item VAT data renders without VAT details."""
        sup = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.15")))
        sup.handle_text("apple")
        state = sup._state()
        for item in state.get("items", []):
            if isinstance(item, dict):
                item.pop("vat_rate", None)
                item.pop("vat_amount", None)
        receipt = render_state(state, receipt_id="r-legacy")
        assert "VAT breakdown" not in receipt.text
        assert "Subtotal" in receipt.text
        assert "Total" in receipt.text

    def test_state_includes_vat_for_taxable(self, seeded_db, event_log):
        """Taxable items have vat_rate and vat_amount in state output."""
        sup = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.15")))
        sup.handle_text("apple")  # taxable
        state = sup._state()
        items = state.get("items", [])
        assert isinstance(items, list)
        for item in items:
            assert isinstance(item, dict)
            if item.get("taxable"):
                assert "vat_rate" in item
                assert "vat_amount" in item
                assert item["vat_rate"] is not None

    def test_vat_round_trip_json(self, seeded_db, event_log, tmp_path):
        """Saved receipt JSON includes VAT fields for taxable items."""
        sup = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.15")))
        sup.handle_text("apple")
        state = sup._state()
        receipt = render_state(state, receipt_id="r-persist")
        path = save(receipt, tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        state_items = payload["state"]["items"]
        for item in state_items:
            if item.get("taxable"):
                assert "vat_rate" in item
                assert "vat_amount" in item
