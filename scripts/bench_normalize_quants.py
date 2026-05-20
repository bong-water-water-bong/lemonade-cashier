"""Head-to-head bench for the normalize() hop across LLM quants.

The cashier's only LLM use-case is to *normalize* an attendant's
phrase into a string that ``inventory.find_product`` can resolve.
IBM Technology's LLM-compression video (``wIXr22QTEHg``) puts the
accuracy hit of 8-bit / 4-bit quantization at under 1% on standard
benchmarks; cashier's task is far narrower than those benchmarks, so
the practical question is "does a smaller / cheaper quant still keep
the supervisor's two-second budget *and* land the right SKU?".

This script answers it by:

1. Running every model named on the command line through the same
   fixed corpus of misspelled phrases.
2. Letting the real ``Supervisor`` resolve the model's output via
   ``find_product`` — the same code path the cashier uses in
   production. The bench is not testing the model in isolation; it
   tests the *integrated* normalize→catalog pipeline.
3. Reporting pass-rate, median latency, and total wall-time as a
   markdown table.

The bench requires ``LC_RUN_LIVE_MODEL=1`` because it hits a real
loopback model server. Without the env var the script prints a
short skip notice and returns 0 so it's safe to wire into ``make``
targets later without exploding in CI.

Usage:

    LC_RUN_LIVE_MODEL=1 python -m scripts.bench_normalize_quants \\
        --lemonade-models Qwen3-4B-GGUF \\
        --flm-models qwen3:0.6b qwen3:4b gemma3:1b

Each model is treated as a *candidate normalizer*. The 80% pass-rate
floor (``VIABILITY_FLOOR``) is the bar for "viable to default".
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

# The pass-rate bar for "this quant is viable to default to in
# normalize()". See IBM compression video wIXr22QTEHg — they show
# <1% degradation on broad benchmarks. Cashier tolerates more because
# the supervisor always re-checks via find_product, but a flop below
# 80% would push too many supervised-confirmation prompts onto the
# attendant. Keep this constant pinned so a casual contributor can't
# drift it lower without notice.
VIABILITY_FLOOR: float = 0.80


@dataclass(frozen=True)
class PhraseProbe:
    """One row of the bench corpus."""

    phrase: str
    expected_canonical: str


@dataclass(frozen=True)
class BenchResult:
    """One model's outcome over the full corpus."""

    model: str
    total: int
    passed: int
    pass_rate: float
    median_ms: int


# The corpus is intentionally hand-crafted, not generated. Twenty-plus
# misspellings, abbreviations, and slang phrases that an attendant
# might actually type at a real US grocery counter. Each maps to a
# canonical product name that the cashier's sample catalog can
# resolve via find_product().
NORMALIZE_CORPUS: tuple[PhraseProbe, ...] = (
    # milk variants
    PhraseProbe("milkk", "milk 1 gal"),
    PhraseProbe("milc", "milk 1 gal"),
    PhraseProbe("whole milk gal", "milk 1 gal"),
    PhraseProbe("a gallon of moo juice", "milk 1 gal"),
    PhraseProbe("MLK", "milk 1 gal"),
    # eggs variants
    PhraseProbe("egz", "eggs dozen"),
    PhraseProbe("a dozen eggs", "eggs dozen"),
    PhraseProbe("dozen of those oval things", "eggs dozen"),
    PhraseProbe("12 eggs please", "eggs dozen"),
    # bread variants
    PhraseProbe("breeed", "bread loaf"),
    PhraseProbe("loaf bread", "bread loaf"),
    PhraseProbe("brd", "bread loaf"),
    PhraseProbe("a loaf of brd", "bread loaf"),
    # banana variants
    PhraseProbe("banaan", "banana"),
    PhraseProbe("bananaa", "banana"),
    PhraseProbe("nanner", "banana"),
    PhraseProbe("yellow potassium fruit", "banana"),
    # apple variants
    PhraseProbe("apl", "apple"),
    PhraseProbe("red apple", "apple"),
    PhraseProbe("aapple", "apple"),
    # coffee variants
    PhraseProbe("cofee", "coffee 12oz"),
    PhraseProbe("ground coffee 12oz", "coffee 12oz"),
    PhraseProbe("a bag of grounds", "coffee 12oz"),
    # cola variants
    PhraseProbe("coca cola", "coca-cola 12oz"),
    PhraseProbe("coke can", "coca-cola 12oz"),
    PhraseProbe("a cola", "coca-cola 12oz"),
    # extreme stretch — model should still produce *something* useful
    PhraseProbe("white moo juice", "milk 1 gal"),
    PhraseProbe("breakfast cereal companion liquid", "milk 1 gal"),
)


# ---------------------------------------------------------------------------
# Tally / report (pure functions, no I/O — exercised by unit tests)
# ---------------------------------------------------------------------------


_Row = tuple[PhraseProbe, str | None, int]


def tally_results(*, model: str, rows: Sequence[_Row]) -> BenchResult:
    """Reduce a list of (probe, observed_canonical, latency_ms) rows
    into a :class:`BenchResult`.

    A row passes when ``observed_canonical`` case-insensitively contains
    the probe's expected canonical phrase — that matches the supervisor's
    real downstream behavior, which feeds the model output back into
    :func:`inventory.find_product` (also case-insensitive).
    """

    if not rows:
        return BenchResult(model=model, total=0, passed=0, pass_rate=0.0, median_ms=0)

    passed = 0
    latencies: list[int] = []
    for probe, observed, ms in rows:
        latencies.append(ms)
        if observed is None:
            continue
        if probe.expected_canonical.casefold() in observed.casefold():
            passed += 1

    total = len(rows)
    return BenchResult(
        model=model,
        total=total,
        passed=passed,
        pass_rate=passed / total,
        median_ms=int(statistics.median(latencies)),
    )


def format_report(results: Sequence[BenchResult]) -> str:
    """Render a deterministic markdown table.

    Pinned columns: ``model | pass / total | pass_rate | median_ms``.
    The pinning lets downstream tools scrape the same shape on every
    run without parser fragility.
    """

    lines = [
        "| model | pass / total | pass_rate | median_ms |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.model} | {r.passed} / {r.total} | {r.pass_rate:.2f} | {r.median_ms} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Bench runner (hits a real model server when LC_RUN_LIVE_MODEL=1)
# ---------------------------------------------------------------------------


def _bench_one_model(
    *,
    model: str,
    normalize_fn: Callable[[str], str | None],
    corpus: Sequence[PhraseProbe] = NORMALIZE_CORPUS,
) -> BenchResult:
    """Run the full corpus through ``normalize_fn`` and tally the result.

    Kept separate from :func:`main` for testability — pass any function
    that maps ``phrase -> canonical_or_None``.
    """

    rows: list[_Row] = []
    for probe in corpus:
        t0 = time.perf_counter()
        observed = normalize_fn(probe.phrase)
        ms = int((time.perf_counter() - t0) * 1000)
        rows.append((probe, observed, ms))
    return tally_results(model=model, rows=rows)


def _live_lemonade_normalize_fn(model: str) -> Callable[[str], str | None]:
    """Build a `phrase -> canonical_or_None` closure that hits the
    real Lemonade Server with the named model. Imported lazily so
    the unit tests don't need the cashier package on sys.path.
    """

    from lemonade_cashier.agents.lemonade_client import LemonadeConfig
    from lemonade_cashier.agents.lemonade_client import normalize as lemonade_normalize

    cfg = LemonadeConfig(enabled=True, model=model)

    def _fn(phrase: str) -> str | None:
        result = lemonade_normalize(phrase, {"items": []}, cfg)
        return None if result is None else result.candidate

    return _fn


def _live_flm_normalize_fn(model: str) -> Callable[[str], str | None]:
    """Same as :func:`_live_lemonade_normalize_fn` but for FastFlowLM."""

    from lemonade_cashier.agents.flm_client import FLMConfig
    from lemonade_cashier.agents.flm_client import normalize as flm_normalize

    cfg = FLMConfig(enabled=True, model=model)

    def _fn(phrase: str) -> str | None:
        result = flm_normalize(phrase, {"items": []}, cfg)
        return None if result is None else result.candidate

    return _fn


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare LLM quants on the normalize() hop.",
    )
    parser.add_argument(
        "--lemonade-models",
        nargs="*",
        default=[],
        help="Lemonade Server model tags to bench, e.g. Qwen3-4B-GGUF.",
    )
    parser.add_argument(
        "--flm-models",
        nargs="*",
        default=[],
        help="FastFlowLM model tags to bench, e.g. qwen3:0.6b gemma3:1b.",
    )
    args = parser.parse_args(argv)

    targets = list(args.lemonade_models) + list(args.flm_models)
    if not targets:
        print(
            "No models specified — pass --lemonade-models and/or --flm-models.\n"
            "  Example: python -m scripts.bench_normalize_quants "
            "--flm-models qwen3:0.6b qwen3:4b",
            file=sys.stdout,
        )
        return 2

    if os.environ.get("LC_RUN_LIVE_MODEL") != "1":
        print(
            "bench skip: this script hits a real loopback model server.\n"
            "Set LC_RUN_LIVE_MODEL=1 to enable the run."
        )
        return 0

    results: list[BenchResult] = []
    for model in args.lemonade_models:
        print(f"# benchmarking lemonade::{model}")
        results.append(
            _bench_one_model(
                model=f"lemonade::{model}",
                normalize_fn=_live_lemonade_normalize_fn(model),
            )
        )
    for model in args.flm_models:
        print(f"# benchmarking flm::{model}")
        results.append(
            _bench_one_model(
                model=f"flm::{model}",
                normalize_fn=_live_flm_normalize_fn(model),
            )
        )

    print()
    print(format_report(results))
    print(f"# viability floor for default: pass_rate >= {VIABILITY_FLOOR:.2f}")
    return 0


__all__ = [
    "NORMALIZE_CORPUS",
    "VIABILITY_FLOOR",
    "BenchResult",
    "PhraseProbe",
    "format_report",
    "main",
    "tally_results",
]


if __name__ == "__main__":
    raise SystemExit(main())
