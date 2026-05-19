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


def test_gaia_bridge_refuses_sensitive_state():
    """gaia_bridge.ask refuses any cart_state that contains a sensitive
    key name, even when GAIA isn't available — the check fires first."""

    from lemonade_cashier.agents.gaia_bridge import GAIABridge, _contains_sensitive

    bridge = GAIABridge(available=False)
    # Even unavailable, ask() returns None for sensitive payloads.
    assert bridge.ask("hi", cart_state={"items": [], "pin_hash": "x"}) is None
    assert _contains_sensitive({"items": [{"sku": "X", "pin": "1234"}]}) is True
    assert _contains_sensitive({"items": [{"sku": "X"}], "total": "1.00"}) is False


def test_bag_seal_exact_manifest_no_false_discrepancy(seeded_db, event_log):
    """Sealing $250.50 and receiving $250.50 must reconcile cleanly — not
    flag a fraudulent discrepancy from a truncated manifest. Regression
    test for the independent-reviewer finding on the demo manifest."""

    from lemonade_cashier.audit.replay import replay

    sup = Supervisor(event_log, SupervisorConfig(attendant_id="alice"))
    sup.handle_text("bag seal 250.50")
    events = event_log.read_all()
    bag_id = next(e.payload["bag_id"] for e in events if e.type == "cit.bag.sealed")

    sup.handle_text(f"bag handoff {bag_id} bob")
    out = sup.handle_text(f"bag receive {bag_id} bob 250.50")
    assert "reconciled" in out.message
    assert "discrepancy" not in out.message

    state = replay(event_log.read_all()).to_state()
    bag = state["bags"][bag_id]
    assert bag["status"] == "reconciled"
    assert bag["manifest_total"] == "250.50"
    assert bag["counted_total"] == "250.50"


def test_bag_prefixed_alias_resolves_to_product(seeded_db, event_log):
    """End-to-end: 'bag of chips' must hit the inventory and add the
    CHP001 SKU at $2.49, not be intercepted by the bag-verb parser."""

    sup = Supervisor(event_log, SupervisorConfig(attendant_id="alice"))
    out = sup.handle_text("bag of chips")
    assert "potato chips" in out.message.lower()
    items = out.state["items"]
    assert len(items) == 1
    assert items[0]["sku"] == "CHP001"


def test_bag_seal_rejects_invalid_amount(seeded_db, event_log):
    """A typo like 'bag seal abx' returns a clean error, not an
    uncaught MoneyError out of the supervisor."""

    sup = Supervisor(event_log, SupervisorConfig(attendant_id="alice"))
    out = sup.handle_text("bag seal abx")
    assert "invalid amount" in out.message


def test_bag_receive_rejects_invalid_amount(seeded_db, event_log):
    sup = Supervisor(event_log, SupervisorConfig(attendant_id="alice"))
    sup.handle_text("bag seal 100.00")
    events = event_log.read_all()
    bag_id = next(e.payload["bag_id"] for e in events if e.type == "cit.bag.sealed")
    sup.handle_text(f"bag handoff {bag_id} bob")
    out = sup.handle_text(f"bag receive {bag_id} bob notanumber")
    assert "invalid amount" in out.message


def test_lemonade_rejects_non_loopback_host(seeded_db, event_log):
    """LC_LEMONADE_URL pointing at a remote host must be refused unless
    allow_remote is explicitly set."""

    from lemonade_cashier.agents.lemonade_client import LemonadeConfig, normalize

    bad_urls = [
        "http://attacker.example.com:8000",
        "http://127.0.0.1@evil.com",  # userinfo masking
        "http://192.168.1.50:8000",
        "https://example.org",
    ]
    for url in bad_urls:
        result = normalize(
            "anything",
            {"items": []},
            LemonadeConfig(url=url, enabled=True, timeout_sec=0.1),
        )
        assert result is None, f"expected None for {url!r}"


def test_lemonade_allows_loopback():
    """Loopback hosts pass the validator."""

    from lemonade_cashier.agents.lemonade_client import _validate_url

    assert _validate_url("http://127.0.0.1:8000")
    assert _validate_url("http://localhost:8000")
    assert _validate_url("http://[::1]:8000")
