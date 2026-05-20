"""Tests for the normalize-model quant-bench harness (A5).

The bench harness compares two or more LLMs head-to-head on the
``normalize()`` hop. It hits a *real* model server (no value in
unit-testing live inference here), so the bulk of the bench is gated
behind ``LC_RUN_LIVE_MODEL=1``.

This test suite covers the parts that *don't* need a model:

* The phrase corpus is well-formed and large enough to give a
  meaningful pass-rate signal.
* The tally / pass-rate / median-latency math is correct.
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


def test_corpus_expects_real_sku_shape():
    """Each probe names a non-empty expected canonical product phrase
    that find_product will resolve. We don't query the catalog here
    (that's the bench's job); we just sanity-check the shape."""

    for probe in NORMALIZE_CORPUS:
        assert isinstance(probe.phrase, str) and probe.phrase.strip()
        assert isinstance(probe.expected_canonical, str)
        assert probe.expected_canonical.strip()


# ---------------------------------------------------------------------------
# Tally math
# ---------------------------------------------------------------------------


def test_tally_counts_passes_and_failures():
    """tally_results turns a list of (probe, observed_sku, ms) rows into
    a BenchResult with pass_rate and median_ms."""

    probes = [
        PhraseProbe(phrase="milkk", expected_canonical="milk 1 gal"),
        PhraseProbe(phrase="banaan", expected_canonical="banana"),
        PhraseProbe(phrase="zzz-no-such-thing", expected_canonical="apple"),
    ]
    rows = [
        # (probe, observed_canonical_or_None, ms)
        (probes[0], "milk 1 gal", 100),
        (probes[1], "banana", 250),
        (probes[2], None, 1500),
    ]
    r = tally_results(model="qwen3:0.6b", rows=rows)
    assert r.model == "qwen3:0.6b"
    assert r.total == 3
    assert r.passed == 2
    assert abs(r.pass_rate - (2 / 3)) < 1e-9
    assert r.median_ms == 250  # middle of {100, 250, 1500}


def test_tally_empty_is_safe():
    """No probes → zero counts, no division-by-zero."""

    r = tally_results(model="gemma3:1b", rows=[])
    assert r.total == 0
    assert r.passed == 0
    assert r.pass_rate == 0.0
    assert r.median_ms == 0


def test_tally_treats_case_insensitive_match():
    """The model rarely emits perfectly-cased product names. The bench
    accepts a case-insensitive substring match because the supervisor's
    actual consumer (`find_product`) is also case-insensitive."""

    probe = PhraseProbe(phrase="MLK", expected_canonical="milk 1 gal")
    rows = [(probe, "Milk 1 Gal", 80)]
    r = tally_results(model="qwen3:0.6b", rows=rows)
    assert r.passed == 1


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
    # Header row, alignment row, then one row per model.
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines[0].startswith("| model")
    # Column order is fixed: model | pass / total | pass_rate | median_ms.
    headers = [c.strip() for c in lines[0].strip("|").split("|")]
    assert headers == ["model", "pass / total", "pass_rate", "median_ms"]
    # Values are present.
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
    touch any network — it prints a clear skip notice and returns 0
    so it's safe to add to `make all` in the future without exploding."""

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
    rc = main([])  # no models at all
    out = capsys.readouterr().out
    assert rc != 0
    assert "no model" in out.lower() or "no models" in out.lower()


# ---------------------------------------------------------------------------
# Pass-rate floor expectation (documentation-shaped test)
# ---------------------------------------------------------------------------


def test_pass_rate_floor_constant_is_eighty_percent():
    """The IBM compression video (wIXr22QTEHg) says ~1% accuracy hit on
    INT4/INT8 quantization. Cashier's normalize() can tolerate more
    sloppiness than that because the supervisor always re-checks the
    output against find_product. We pin a generous 80% floor as the
    'this quant is viable for normalize()' bar.
    """

    from scripts.bench_normalize_quants import VIABILITY_FLOOR

    assert pytest.approx(0.80) == VIABILITY_FLOOR
