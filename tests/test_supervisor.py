"""End-to-end tests of the multi-agent supervisor."""

from __future__ import annotations

from lemonade_cashier.agents.supervisor import Supervisor, SupervisorConfig
from lemonade_cashier.core.money import to_money


def test_supervisor_adds_via_alias(seeded_db, event_log):
    sup = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.00")))
    outcome = sup.handle_text("coke")
    assert not outcome.needs_confirmation
    assert "coca-cola" in outcome.message.lower()
    skus = [item["sku"] for item in outcome.state["items"]]
    assert skus == ["COK001"]


def test_supervisor_no_match_message(seeded_db, event_log):
    sup = Supervisor(event_log, SupervisorConfig())
    outcome = sup.handle_text("xyz123 nonsense")
    assert "no product matched" in outcome.message
    assert outcome.state["items"] == []


def test_lemonade_rejects_non_http_url(seeded_db, event_log):
    """A misconfigured `file://` or `javascript:` URL in .env must not
    cause the Lemonade client to make any call. It silently disables."""

    from lemonade_cashier.agents.lemonade_client import LemonadeConfig, normalize

    for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://x", ""):
        result = normalize(
            "anything",
            {"items": []},
            LemonadeConfig(url=bad, enabled=True, timeout_sec=0.1),
        )
        assert result is None, f"expected None for {bad!r}"


def test_lemonade_unreachable_does_not_hang(seeded_db, event_log):
    """If Lemonade is enabled but the URL is unreachable, the supervisor
    must degrade quickly and never raise."""

    from lemonade_cashier.agents.lemonade_client import LemonadeConfig

    config = SupervisorConfig(
        lemonade=LemonadeConfig(
            url="http://127.0.0.1:1",  # nothing here
            timeout_sec=0.25,
            enabled=True,
        ),
    )
    sup = Supervisor(event_log, config)
    outcome = sup.handle_text("totally not a product")
    assert "no product matched" in outcome.message


def test_supervisor_tender_records_change(seeded_db, event_log):
    sup = Supervisor(event_log, SupervisorConfig(tax_rate=to_money("0.00")))
    sup.handle_text("apple")  # 0.75
    sup.handle_text("apple")  # another → merges, qty 2 → $1.50
    outcome = sup.handle_text("cash 5.00")
    assert outcome.tender_breakdown is not None
    assert outcome.tender_breakdown["change_due"] == "3.50"


def test_supervisor_clear_resets_cart(seeded_db, event_log):
    sup = Supervisor(event_log, SupervisorConfig())
    sup.handle_text("apple")
    sup.handle_text("separate order")
    sup.handle_text("milk")
    skus = [item["sku"] for item in sup._state()["items"]]  # noqa: SLF001
    assert skus == ["MLK001"]
