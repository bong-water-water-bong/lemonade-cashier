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
    skus = [item["sku"] for item in sup._state()["items"]]
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


def test_void_below_threshold_no_pin_required(seeded_db, event_log):
    """A void of a cheap line (< policy threshold) requires no PIN."""

    sup = Supervisor(event_log, SupervisorConfig(attendant_id="alice"))
    sup.handle_text("apple")  # $0.75 — well below the $10 void threshold
    out = sup.handle_text("remove that")
    assert "removed" in out.message
    assert not out.needs_pin


def test_void_above_threshold_demands_pin(seeded_db, event_log, tmp_path):
    """A void of a $10+ line must demand a supervisor PIN. With no
    PIN supplied the outcome has needs_pin=True; with a wrong PIN the
    outcome is a denial; with the right PIN the void proceeds."""

    from lemonade_cashier.safety import pins

    pin_store = tmp_path / "pins.json"
    pins.set_pin("supervisor", "1234", path=pin_store)

    sup = Supervisor(
        event_log,
        SupervisorConfig(
            attendant_id="alice",
            supervisor_id="supervisor",
            pin_store=pin_store,
        ),
    )
    # Coffee at $8.99, two of those → $17.98 — over the $10 void threshold.
    sup.handle_text("coffee")
    sup.handle_text("two of those")

    # First attempt: no PIN.
    out = sup.handle_text("remove that")
    assert out.needs_pin is True
    assert out.pin_for_action == "void_last_line"

    # Wrong PIN.
    out = sup.handle_text("remove that", pin="9999")
    assert "incorrect" in out.message.lower()

    # Correct PIN.
    out = sup.handle_text("remove that", pin="1234")
    assert "removed" in out.message
    assert not out.needs_pin


def test_remove_named_above_threshold_demands_pin(seeded_db, event_log, tmp_path):
    """`remove coffee` on a $17.98 line must demand a PIN, same as
    `remove that`. Regression test for the independent-reviewer finding
    that only _remove_last hit the policy gate."""

    from lemonade_cashier.safety import pins

    pin_store = tmp_path / "pins.json"
    pins.set_pin("supervisor", "1234", path=pin_store)
    sup = Supervisor(
        event_log,
        SupervisorConfig(attendant_id="alice", supervisor_id="supervisor", pin_store=pin_store),
    )
    sup.handle_text("coffee")
    sup.handle_text("two of those")

    out = sup.handle_text("remove coffee")
    assert out.needs_pin is True
    assert out.pin_for_action == "void_named"

    out = sup.handle_text("remove coffee", pin="1234")
    assert "removed" in out.message


def test_set_quantity_reduction_above_threshold_demands_pin(seeded_db, event_log, tmp_path):
    """Going from `12 of those` ($107.88 of coffee) to `2 of those`
    ($17.98) is a $89.90 partial void — must demand a PIN."""

    from lemonade_cashier.safety import pins

    pin_store = tmp_path / "pins.json"
    pins.set_pin("supervisor", "1234", path=pin_store)
    sup = Supervisor(
        event_log,
        SupervisorConfig(attendant_id="alice", supervisor_id="supervisor", pin_store=pin_store),
    )
    sup.handle_text("coffee")
    sup.handle_text("12 of those")

    out = sup.handle_text("2 of those")
    assert out.needs_pin is True
    assert out.pin_for_action == "void_quantity_reduction"

    # Happy path: correct PIN → reduction actually applies.
    out = sup.handle_text("2 of those", pin="1234")
    assert not out.needs_pin
    assert "set quantity to 2" in out.message
    coffee_line = next(item for item in out.state["items"] if item["sku"] == "COF001")
    assert coffee_line["quantity"] == 2


def test_clear_cart_above_threshold_demands_pin(seeded_db, event_log, tmp_path):
    """`separate order` on a cart whose subtotal exceeds the void
    threshold wipes everything - must demand a PIN. The test cart is
    $17.98 (coffee x 2) - over the default $10 void threshold.

    This was the most dangerous bypass before the gate extraction: the
    operator could erase an arbitrarily large cart with `separate
    order` and zero audit signal."""

    from lemonade_cashier.safety import pins

    pin_store = tmp_path / "pins.json"
    pins.set_pin("supervisor", "1234", path=pin_store)
    sup = Supervisor(
        event_log,
        SupervisorConfig(attendant_id="alice", supervisor_id="supervisor", pin_store=pin_store),
    )
    sup.handle_text("coffee")
    sup.handle_text("two of those")  # $17.98 — over $10 threshold
    out = sup.handle_text("separate order")
    assert out.needs_pin is True
    assert out.pin_for_action == "void_clear_cart"

    # Happy path: correct PIN clears the cart and starts a new order.
    out = sup.handle_text("separate order", pin="1234")
    assert not out.needs_pin
    assert "separate order" in out.message
    assert out.state["items"] == []


def test_clear_empty_cart_no_pin_required(seeded_db, event_log):
    """An empty cart can be `separate order`'d for free — no value at risk."""

    sup = Supervisor(event_log, SupervisorConfig(attendant_id="alice"))
    out = sup.handle_text("separate order")
    assert "separate order" in out.message
    assert not out.needs_pin


def test_supervisor_report_returns_eos_state(seeded_db, event_log):
    sup = Supervisor(event_log, SupervisorConfig(attendant_id="alice"))
    sup.handle_text("apple")
    state = sup.report()
    assert state["schema_version"] == 1
    assert "alice" in state["attendants"]


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
