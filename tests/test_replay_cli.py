"""Tests for the replay CLI (`scripts/replay.py`).

Covers the new ``--agent-activity`` mode that wires the A3 projection
(:mod:`lemonade_cashier.audit.agent_activity`) into the CLI, plus
the additive guarantees for the existing default mode.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lemonade_cashier.agents import proposals
from lemonade_cashier.audit.eventlog import EventLog
from scripts.replay import main


def _seed_proposal_log(path: Path) -> None:
    log = EventLog(path)
    proposals.write(
        log,
        agent="lemonade",
        agent_id="lemonade@http://127.0.0.1:8000#qwen3:4b",
        kind="normalize",
        input={"phrase": "milkk"},
        output={"phrase": "milk 1 gal"},
        confidence=0.95,
        decision="accepted",
    )
    proposals.write(
        log,
        agent="flm",
        agent_id="flm@http://127.0.0.1:11434#qwen3:4b",
        kind="normalize",
        input={"phrase": "egz"},
        output=None,
        confidence=0.0,
        decision="unreachable",
    )


# ---------------------------------------------------------------------------
# --agent-activity mode
# ---------------------------------------------------------------------------


def test_agent_activity_prints_summary_and_exits_zero(tmp_path: Path, capsys):
    """A populated log → summary printed to stdout, exit code 0."""

    log_path = tmp_path / "events.jsonl"
    _seed_proposal_log(log_path)

    rc = main(["--agent-activity", str(log_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "total proposals: 2" in out
    assert "by decision:" in out
    assert "accepted: " in out
    assert "unreachable: " in out
    assert "by agent:" in out
    assert "lemonade: 1" in out
    assert "flm: 1" in out
    assert "by agent_id:" in out
    assert "lemonade@http://127.0.0.1:8000#qwen3:4b: 1" in out
    assert "delegations minted:" in out
    assert "orphan delegations:" in out


def test_agent_activity_on_empty_log_reports_zero(tmp_path: Path, capsys):
    """An empty (just-created) log → ``total proposals: 0`` and exit 0.
    The output must not crash or hide the zero — operators run the
    command on fresh tills routinely.
    """

    log_path = tmp_path / "events.jsonl"
    log_path.touch()  # zero bytes

    rc = main(["--agent-activity", str(log_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "total proposals: 0" in out


def test_agent_activity_renders_legacy_agent_id_as_explicit_label(
    tmp_path: Path, capsys
):
    """A proposal payload without ``agent_id`` counts under the ``None``
    bucket in the projection. The CLI renders that bucket as
    ``(legacy: no agent_id)`` so the output is grep-friendly — empty
    parentheses or ``None`` would be ambiguous."""

    log_path = tmp_path / "events.jsonl"
    log = EventLog(log_path)
    # legacy event: no agent_id key
    log.append(
        proposals.EVENT_TYPE,
        {
            "agent": "lemonade",
            "kind": "normalize",
            "input": {"phrase": "x"},
            "output": {"phrase": "x"},
            "confidence": 0.5,
            "decision": "rejected",
        },
    )

    rc = main(["--agent-activity", str(log_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "(legacy: no agent_id)" in out
    assert "None" not in out  # the literal "None" must not leak


def test_agent_activity_output_is_byte_stable(tmp_path: Path, capsys):
    """Two consecutive runs on the same log produce identical output —
    no timestamps, no dict-order randomness."""

    log_path = tmp_path / "events.jsonl"
    _seed_proposal_log(log_path)

    rc1 = main(["--agent-activity", str(log_path)])
    out1 = capsys.readouterr().out

    rc2 = main(["--agent-activity", str(log_path)])
    out2 = capsys.readouterr().out

    assert rc1 == 0 and rc2 == 0
    assert out1 == out2


def test_agent_activity_sorts_breakdowns_alphabetically(tmp_path: Path, capsys):
    """Bucket keys are emitted in alphabetical order so the output is
    diff-stable and easy to compare across runs."""

    log_path = tmp_path / "events.jsonl"
    log = EventLog(log_path)
    # Write proposals in a deliberately non-alphabetical order.
    for agent, decision in [
        ("flm", "rejected"),
        ("lemonade", "accepted"),
        ("flm", "accepted"),
        ("lemonade", "rejected"),
    ]:
        proposals.write(
            log,
            agent=agent,
            kind="normalize",
            input={}, output={}, confidence=0.5,
            decision=decision,
        )

    rc = main(["--agent-activity", str(log_path)])
    out = capsys.readouterr().out
    assert rc == 0
    # by decision: "accepted" before "rejected" (alphabetical)
    assert out.find("accepted: ") < out.find("rejected: ")
    # by agent: "flm" before "lemonade" (alphabetical)
    assert out.find("flm: ") < out.find("lemonade: ")


# ---------------------------------------------------------------------------
# Default replay mode still works
# ---------------------------------------------------------------------------


def test_default_replay_mode_unchanged(tmp_path: Path, capsys):
    """Passing a path without any mode flag → default behavior (JSON
    state dump) is preserved exactly as before. This PR is additive."""

    log_path = tmp_path / "events.jsonl"
    log = EventLog(log_path)
    log.append("transaction.open", {"attendant": "alice", "tax_rate": "0.15"})

    rc = main([str(log_path)])
    out = capsys.readouterr().out

    assert rc == 0
    # JSON shape: contains the keys to_state() emits
    assert "items" in out
    assert "subtotal" in out or "schema_version" in out


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def test_no_args_fails_with_usage_hint(capsys):
    """No path at all → non-zero exit + a clear usage hint mentioning
    LOG. argparse's ``parser.error`` raises ``SystemExit`` (the standard
    CLI convention), so this catches it and asserts the exit code +
    error message rather than expecting a plain ``int`` return."""

    with pytest.raises(SystemExit) as exc:
        main([])
    err = capsys.readouterr().err
    assert exc.value.code != 0
    assert "usage" in err.lower() or "log" in err.lower()


def test_missing_log_file_fails_loudly(tmp_path: Path, capsys):
    """A path that doesn't exist → non-zero exit, error names the
    missing file so the operator can fix the typo."""

    missing = tmp_path / "does_not_exist.jsonl"
    rc = main(["--agent-activity", str(missing)])
    err = capsys.readouterr().err
    out = capsys.readouterr().out
    combined = err + out
    assert rc != 0
    assert str(missing) in combined or "does_not_exist" in combined
