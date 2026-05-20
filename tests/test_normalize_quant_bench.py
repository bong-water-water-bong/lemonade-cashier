"""Tests for the normalize-model quant-bench harness (A5).

The bench compares two or more LLMs head-to-head on the
``normalize()`` hop. It hits a *real* model server (no value in
unit-testing live inference here), so the bulk of the bench is
gated behind ``LC_RUN_LIVE_MODEL=1``.

This suite covers the parts that don't need a model:

* The phrase corpus is well-formed and large enough to give a
  meaningful pass-rate signal.
* The tally math uses **SKU-match via ``find_product``**, which is
  what the supervisor itself does downstream — not a substring on
  the canonical product name.
* The bench respects the ``LC_RUN_LIVE_MODEL`` gate.
* The bench's report formatting is deterministic.
"""

from __future__ import annotations

import pytest

from scripts.bench_normalize_quants import (
    NORMALIZE_CORPUS,
    BenchResult,
    PhraseProbe,
    format_report,
    tally_results,
)

# ---------------------------------------------------------------------------
# Corpus sanity
# ---------------------------------------------------------------------------


def test_corpus_has_at_least_twenty_phrases():
    """A bench with <20 phrases is statistically noisy. Pin the floor."""

    assert len(NORMALIZE_CORPUS) >= 20


def test_corpus_phrases_are_unique():
    """A duplicate phrase would weight one product more than the others
    and silently skew the pass rate."""

    phrases = [probe.phrase for probe in NORMALIZE_CORPUS]
    assert len(phrases) == len(set(phrases))


def test_corpus_carries_expected_sku_not_phrase():
    """Each probe names an ``expected_sku`` (the canonical SKU string,
    e.g. ``MLK001``) — NOT the canonical product *name*. The bench
    grades against the resolved SKU because that's what the supervisor
    actually consumes downstream, and the substring-match rule the
    previous bench used understated real performance by ~5x."""

    for probe in NORMALIZE_CORPUS:
        assert isinstance(probe.phrase, str) and probe.phrase.strip()
        assert isinstance(probe.expected_sku, str)
        # SKU shape is "XXX###" — three uppercase letters then digits.
        sku = probe.expected_sku
        assert sku == sku.upper()
        assert sku[:3].isalpha()
        assert sku[3:].isdigit()


def test_corpus_skus_all_resolve_in_catalog(seeded_db):
    """Every ``expected_sku`` in the corpus must be findable in the
    sample catalog — otherwise the bench can never get that probe
    right and the failure is a corpus error, not a model failing."""

    from lemonade_cashier.core import inventory

    seen_skus = {probe.expected_sku for probe in NORMALIZE_CORPUS}
    catalog_skus = {product.sku for product in inventory.all_products()}
    missing = seen_skus - catalog_skus
    assert not missing, f"corpus expects SKUs absent from catalog: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Tally math — SKU-match through find_product
# ---------------------------------------------------------------------------


def test_tally_passes_when_observed_resolves_to_expected_sku(seeded_db):
    """A model output that ``find_product`` resolves to the expected
    SKU is a pass — even if the literal string doesn't substring-match
    the canonical product name. This is the *integrated* test the
    supervisor actually performs in production."""

    probes = [
        PhraseProbe(phrase="milkk", expected_sku="MLK001"),
        PhraseProbe(phrase="banaan", expected_sku="BAN001"),
        PhraseProbe(phrase="zzz-no-such-thing", expected_sku="APL001"),
    ]
    rows = [
        # The model echoes the input back (qwen3:0.6b style); the
        # catalog fuzzy matcher resolves it correctly.
        (probes[0], "milkk", 100),
        (probes[1], "banaan", 250),
        # No model output at all → no SKU resolution → fail.
        (probes[2], None, 1500),
    ]
    r = tally_results(model="qwen3:0.6b", rows=rows)
    assert r.model == "qwen3:0.6b"
    assert r.total == 3
    assert r.passed == 2
    assert abs(r.pass_rate - (2 / 3)) < 1e-9
    assert r.median_ms == 250  # middle of {100, 250, 1500}


def test_tally_fails_when_observed_resolves_to_wrong_sku(seeded_db):
    """The previous substring rule would falsely pass any output
    containing the canonical name. The SKU rule catches mis-resolution.

    ``a bag of grounds`` was observed in the wild resolving to ``CHP001``
    (potato chips, via the "bag of chips" alias) instead of ``COF001``
    (coffee). That's a fail, not a pass."""

    probe = PhraseProbe(phrase="a bag of grounds", expected_sku="COF001")
    rows = [(probe, "a bag of grounds", 90)]
    r = tally_results(model="qwen3:0.6b", rows=rows)
    assert r.passed == 0, "wrong-SKU fuzzy match must count as a fail"


def test_tally_fails_when_observed_does_not_resolve_at_all(seeded_db):
    """If the model output is something the catalog can't resolve to
    any SKU (``find_product`` returns ``None``), that's a fail —
    regardless of how creatively the output describes the product."""

    probe = PhraseProbe(phrase="white moo juice", expected_sku="MLK001")
    rows = [(probe, "white moo juice", 90)]
    r = tally_results(model="qwen3:0.6b", rows=rows)
    assert r.passed == 0


def test_tally_passes_when_observed_is_case_inverted(seeded_db):
    """``find_product`` is case-insensitive, so the tally inherits
    that property — uppercase / mixed-case model outputs that resolve
    to the right SKU still pass."""

    probe = PhraseProbe(phrase="MLK", expected_sku="MLK001")
    rows = [(probe, "MILK", 80)]
    r = tally_results(model="qwen3:0.6b", rows=rows)
    assert r.passed == 1


def test_tally_empty_is_safe():
    """No probes → zero counts, no division-by-zero."""

    r = tally_results(model="gemma3:1b", rows=[])
    assert r.total == 0
    assert r.passed == 0
    assert r.pass_rate == 0.0
    assert r.median_ms == 0


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def test_report_renders_a_markdown_table():
    """The bench prints a markdown table for easy paste into the PR
    body / analysis file. Pin the columns so a future contributor
    can't accidentally rearrange them and break downstream scrapers."""

    results = [
        BenchResult(model="qwen3:0.6b", total=20, passed=17, pass_rate=0.85, median_ms=120),
        BenchResult(model="qwen3:4b", total=20, passed=19, pass_rate=0.95, median_ms=520),
    ]
    out = format_report(results)
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines[0].startswith("| model")
    headers = [c.strip() for c in lines[0].strip("|").split("|")]
    assert headers == ["model", "pass / total", "pass_rate", "median_ms"]
    assert "qwen3:0.6b" in out
    assert "qwen3:4b" in out
    assert "17 / 20" in out
    assert "0.85" in out
    assert "0.95" in out
    assert "120" in out
    assert "520" in out


# ---------------------------------------------------------------------------
# Live gate
# ---------------------------------------------------------------------------


def test_bench_skips_when_live_model_env_unset(monkeypatch, capsys):
    """Running the bench module without LC_RUN_LIVE_MODEL=1 must not
    touch any network — it prints a clear skip notice and returns 0."""

    from scripts.bench_normalize_quants import main

    monkeypatch.delenv("LC_RUN_LIVE_MODEL", raising=False)
    rc = main(["--lemonade-models", "qwen3:0.6b"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "LC_RUN_LIVE_MODEL" in out
    assert "skip" in out.lower()


def test_bench_refuses_to_run_without_any_model_target(monkeypatch, capsys):
    """If the operator forgets to pass any --lemonade-models or
    --flm-models, the bench should fail loudly rather than print an
    empty report."""

    from scripts.bench_normalize_quants import main

    monkeypatch.setenv("LC_RUN_LIVE_MODEL", "1")
    rc = main([])
    out = capsys.readouterr().out
    assert rc != 0
    assert "no model" in out.lower() or "no models" in out.lower()


# ---------------------------------------------------------------------------
# Pass-rate floor expectation
# ---------------------------------------------------------------------------


def test_pass_rate_floor_constant_is_eighty_percent():
    """IBM compression video (wIXr22QTEHg) says ~1% accuracy hit on
    INT4/INT8 quantization. Cashier's normalize() can tolerate more
    sloppiness than that because the supervisor always re-checks the
    output against find_product. We pin a generous 80% floor as the
    'this quant is viable for normalize()' bar."""

    from scripts.bench_normalize_quants import VIABILITY_FLOOR

    assert pytest.approx(0.80) == VIABILITY_FLOOR


# ---------------------------------------------------------------------------
# Repro of the 2026-05-20 live finding
# ---------------------------------------------------------------------------


def test_substring_rule_would_have_understated_qwen3_0_6b(seeded_db):
    """Documentation-shaped regression: on the 2026-05-20 live bench
    against qwen3:0.6b, the substring-match rule reported 4/28 while
    SKU-match reported 22/28. Pin a sample of those outcomes so a
    future contributor reverting to substring-match would break this
    test loudly."""

    cases: list[tuple[str, str, str]] = [
        # (phrase, model_output_observed, expected_sku) — SKU-match passes
        ("milkk", "milkk", "MLK001"),
        ("egz", "egz", "EGG001"),
        ("breeed", "breeed", "BRD001"),
        ("cofee", "cofee", "COF001"),
        ("coca cola", "coca cola", "COK001"),
    ]
    probes = [PhraseProbe(phrase=p, expected_sku=sku) for p, _, sku in cases]
    rows = [(probes[i], cases[i][1], 100 + i) for i in range(len(cases))]
    r = tally_results(model="qwen3:0.6b", rows=rows)
    assert r.passed == len(cases), (
        "SKU-match should pass all of these; the old substring rule would have"
        " failed every one because 'milkk' doesn't substring-contain"
        " 'milk 1 gal'."
    )
