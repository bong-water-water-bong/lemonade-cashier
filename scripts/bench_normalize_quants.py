"""Head-to-head bench for the normalize() hop across LLM quants.

The cashier's only LLM use-case is to *normalize* an attendant's
phrase into a string that ``inventory.find_product`` can resolve.
IBM Technology's LLM-compression video (``wIXr22QTEHg``) puts the
accuracy hit of 8-bit / 4-bit quantization at under 1% on standard
benchmarks; cashier's task is far narrower than those benchmarks, so
the practical question is "does a smaller / cheaper quant still keep
the supervisor's two-second budget *and* land the right SKU?".

The bench answers it by:

1. Running every model named on the command line through the same
   fixed corpus of misspelled / slangy / oblique phrases.
2. Feeding each model output through ``inventory.find_product`` —
   the same code path the cashier uses in production. A row passes
   iff the resolved SKU equals the corpus's ``expected_sku``. This
   matches the supervisor's downstream behavior exactly; the older
   "substring on canonical name" rule understated real performance
   by ~5× (see ``~/Desktop/Shared AI /a5-bench-results-2026-05-20.md``).
3. Reporting pass-rate, median latency, and total wall-time as a
   deterministic markdown table.

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

from lemonade_cashier.core.inventory import find_product

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
    """One row of the bench corpus.

    ``expected_sku`` is the canonical SKU string the model output
    must resolve to via :func:`find_product` for the probe to pass.
    The bench grades on SKU equality, not on the literal product name,
    because that's what the supervisor itself consumes downstream.
    """

    phrase: str
    expected_sku: str


@dataclass(frozen=True)
class BenchResult:
    """One model's outcome over the full corpus."""

    model: str
    total: int
    passed: int
    pass_rate: float
    median_ms: int


# Hand-crafted, not generated. 20+ misspellings, abbreviations, and
# slang phrases an attendant might actually type at a US grocery
# counter. Each maps to a canonical SKU from the sample catalog
# (data/sample_products.csv).
NORMALIZE_CORPUS: tuple[PhraseProbe, ...] = (
    # milk (MLK001 — alias "milk")
    PhraseProbe("milkk", "MLK001"),
    PhraseProbe("milc", "MLK001"),
    PhraseProbe("whole milk gal", "MLK001"),
    PhraseProbe("a gallon of moo juice", "MLK001"),
    PhraseProbe("MLK", "MLK001"),
    # eggs (EGG001 — alias "eggs")
    PhraseProbe("egz", "EGG001"),
    PhraseProbe("a dozen eggs", "EGG001"),
    PhraseProbe("dozen of those oval things", "EGG001"),
    PhraseProbe("12 eggs please", "EGG001"),
    # bread (BRD001 — alias "bread")
    PhraseProbe("breeed", "BRD001"),
    PhraseProbe("loaf bread", "BRD001"),
    PhraseProbe("brd", "BRD001"),
    PhraseProbe("a loaf of brd", "BRD001"),
    # banana (BAN001 — alias "bananas")
    PhraseProbe("banaan", "BAN001"),
    PhraseProbe("bananaa", "BAN001"),
    PhraseProbe("nanner", "BAN001"),
    PhraseProbe("yellow potassium fruit", "BAN001"),
    # apple (APL001 — alias "apple")
    PhraseProbe("apl", "APL001"),
    PhraseProbe("red apple", "APL001"),
    PhraseProbe("aapple", "APL001"),
    # coffee (COF001 — alias "coffee")
    PhraseProbe("cofee", "COF001"),
    PhraseProbe("ground coffee 12oz", "COF001"),
    PhraseProbe("a bag of grounds", "COF001"),
    # cola (COK001 — alias "coke")
    PhraseProbe("coca cola", "COK001"),
    PhraseProbe("coke can", "COK001"),
    PhraseProbe("a cola", "COK001"),
    # extreme stretch — a competent normalizer should still
    # produce something the catalog can resolve
    PhraseProbe("white moo juice", "MLK001"),
    PhraseProbe("breakfast cereal companion liquid", "MLK001"),
)


# ---------------------------------------------------------------------------
# Tally / report (pure functions over inventory lookups)
# ---------------------------------------------------------------------------


_Row = tuple[PhraseProbe, str | None, int]


def tally_results(*, model: str, rows: Sequence[_Row]) -> BenchResult:
    """Reduce a list of ``(probe, observed_canonical_or_None, latency_ms)``
    rows into a :class:`BenchResult`.

    A row passes when :func:`find_product` resolves the observed text
    to the probe's ``expected_sku``. This mirrors the supervisor's
    downstream behavior exactly — a model output that is "close enough"
    for the catalog to land on the right SKU is the only thing that
    matters in production. The older substring-on-canonical-name rule
    underreported small-model performance by ~5× (the 2026-05-20 run
    on qwen3:0.6b showed 4/28 substring vs 22/28 SKU-match).

    A ``None`` observed → no SKU resolution → fail.

    The bench requires a seeded inventory database; call
    :func:`lemonade_cashier.core.inventory.initialize_database` before
    invoking this function. The CLI ``main`` does so.
    """

    if not rows:
        return BenchResult(model=model, total=0, passed=0, pass_rate=0.0, median_ms=0)

    passed = 0
    latencies: list[int] = []
    for probe, observed, ms in rows:
        latencies.append(ms)
        if observed is None:
            continue
        match = find_product(observed)
        if match is None:
            continue
        if match.sku == probe.expected_sku:
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
    the unit tests don't need the package on sys.path.
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

    # Ensure the inventory database is seeded — find_product()
    # otherwise raises on the first call. Idempotent if already seeded.
    from pathlib import Path

    from lemonade_cashier.core.inventory import (
        DEFAULT_CSV_PATH,
        DEFAULT_DB_PATH,
        initialize_database,
    )

    if not Path(DEFAULT_DB_PATH).exists():
        initialize_database(db_path=DEFAULT_DB_PATH, csv_path=DEFAULT_CSV_PATH, force=True)

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
    "BenchResult",
    "NORMALIZE_CORPUS",
    "PhraseProbe",
    "VIABILITY_FLOOR",
    "format_report",
    "main",
    "tally_results",
]


if __name__ == "__main__":
    raise SystemExit(main())
