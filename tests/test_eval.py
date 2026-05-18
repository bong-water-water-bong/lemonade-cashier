"""Smoke-test the eval runner against the shipped scenarios.jsonl."""

from __future__ import annotations

from pathlib import Path

from lemonade_cashier.integrations.eval import run_scenarios


def test_shipped_scenarios_pass(seeded_db):
    repo_root = Path(__file__).resolve().parents[1]
    scenarios = repo_root / "data" / "scenarios.jsonl"
    summary = run_scenarios(scenarios)
    failed = [r for r in summary.results if not r.passed]
    assert not failed, "scenarios regressed:\n" + "\n".join(
        f"  - {r.name}: {r.detail}" for r in failed
    )
