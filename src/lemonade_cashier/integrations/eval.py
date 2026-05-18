"""Deterministic eval runner.

Reads a JSONL scenario file. Each line is a JSON object:

```json
{
  "name": "two apples and a coke",
  "inputs": ["apple", "two of those", "coke"],
  "expected": {
    "item_skus": ["APL001", "COK001"],
    "subtotal": "2.00",
    "total_min": "2.20"
  }
}
```

The runner does not assert byte-equality on the entire state (that's
too brittle as new fields land); it asserts the *shape* the scenario
declares: which SKUs ended up in the cart, what the subtotal was, and
optionally a total range. CI fails if any scenario regresses.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..agents.supervisor import Supervisor, SupervisorConfig
from ..audit.eventlog import EventLog
from ..core.inventory import initialize_database
from ..core.money import to_money


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: str


@dataclass
class EvalSummary:
    results: list[ScenarioResult]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def ok(self) -> bool:
        return self.failed == 0


def run_scenarios(path: Path | str) -> EvalSummary:
    """Run every scenario in ``path`` and return an :class:`EvalSummary`."""

    initialize_database()
    results: list[ScenarioResult] = []
    for scenario in _read_scenarios(Path(path)):
        results.append(_run_one(scenario))
    return EvalSummary(results=results)


def _run_one(scenario: dict[str, object]) -> ScenarioResult:
    name = str(scenario.get("name", "<unnamed>"))
    inputs = scenario.get("inputs", [])
    expected = scenario.get("expected", {})
    if not isinstance(inputs, list) or not isinstance(expected, dict):
        return ScenarioResult(name=name, passed=False, detail="malformed scenario")

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as tmp:
        log_path = Path(tmp.name)

    try:
        log = EventLog(log_path)
        supervisor = Supervisor(log, SupervisorConfig())
        for raw in inputs:
            outcome = supervisor.handle_text(str(raw))
            if outcome.needs_confirmation:
                # Scenario inputs assume non-low-confidence matches; we
                # treat needs_confirmation as a regression.
                return ScenarioResult(
                    name=name,
                    passed=False,
                    detail=f"unexpected confirmation prompt for '{raw}'",
                )
        state = supervisor._state()  # noqa: SLF001 — internal-use ok in tests
    finally:
        log_path.unlink(missing_ok=True)

    return _compare(name, state, expected)


def _compare(
    name: str, state: dict[str, object], expected: dict[str, object]
) -> ScenarioResult:
    actual_skus = tuple(item["sku"] for item in state.get("items", []))  # type: ignore[index]
    want_skus = expected.get("item_skus")
    if want_skus is not None and tuple(want_skus) != actual_skus:  # type: ignore[arg-type]
        return ScenarioResult(
            name=name,
            passed=False,
            detail=f"want skus={want_skus}, got={list(actual_skus)}",
        )

    want_subtotal = expected.get("subtotal")
    if want_subtotal is not None:
        actual_subtotal = to_money(state.get("subtotal", "0.00"))  # type: ignore[arg-type]
        if actual_subtotal != to_money(want_subtotal):  # type: ignore[arg-type]
            return ScenarioResult(
                name=name,
                passed=False,
                detail=(
                    f"want subtotal={want_subtotal}, got={state.get('subtotal')}"
                ),
            )

    total_min = expected.get("total_min")
    if total_min is not None:
        actual_total = to_money(state.get("total", "0.00"))  # type: ignore[arg-type]
        if actual_total < to_money(total_min):  # type: ignore[arg-type]
            return ScenarioResult(
                name=name,
                passed=False,
                detail=(
                    f"want total >= {total_min}, got {state.get('total')}"
                ),
            )

    return ScenarioResult(name=name, passed=True, detail="ok")


def _read_scenarios(path: Path) -> list[dict[str, object]]:
    scenarios: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            scenarios.append(json.loads(line))
    return scenarios


def main() -> None:  # pragma: no cover — CLI helper
    import sys

    target = Path(
        sys.argv[1] if len(sys.argv) > 1 else "data/scenarios.jsonl"
    )
    summary = run_scenarios(target)
    for result in summary.results:
        marker = "ok  " if result.passed else "FAIL"
        print(f"{marker}  {result.name}  ({result.detail})")
    print(f"\n{summary.passed} passed, {summary.failed} failed")
    raise SystemExit(0 if summary.ok() else 1)


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["EvalSummary", "ScenarioResult", "run_scenarios"]
