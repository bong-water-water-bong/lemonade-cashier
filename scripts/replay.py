"""Replay an event log and print the resulting state or summary.

Two modes:

* **Default (no flag)** — replay the chain via
  :func:`lemonade_cashier.audit.replay.replay_log` and dump the
  resulting state as JSON. Behavior identical to the original
  one-shot replay script.

* **``--agent-activity``** — run the A3 projection
  (:func:`lemonade_cashier.audit.agent_activity.summarize`) and
  print a plain-text per-session summary of agent.proposal events
  and delegation reconciliation. Sorted keys, byte-stable output.

Modes are mutually exclusive. Future modes (replay-receipts, etc.)
can be added the same way.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from lemonade_cashier.audit.agent_activity import AgentActivitySummary, summarize
from lemonade_cashier.audit.replay import replay_log

_LEGACY_AGENT_ID_LABEL = "(legacy: no agent_id)"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="replay",
        description="Replay a Lemonade Cashier event log.",
    )
    parser.add_argument(
        "log",
        nargs="?",
        help="Path to the JSONL event log.",
    )
    parser.add_argument(
        "--agent-activity",
        dest="agent_activity_log",
        metavar="LOG",
        help=(
            "Print a per-session agent-activity summary instead of "
            "replaying the chain state."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.agent_activity_log is not None:
        if args.log is not None:
            parser.error(
                "pass either --agent-activity LOG or a positional LOG, not both"
            )
        return _run_agent_activity(Path(args.agent_activity_log))

    if not args.log:
        parser.error("missing LOG argument")
        # parser.error exits with code 2; the explicit return below
        # is for the type-checker and for any future test that
        # monkey-patches argparse.
        return 2  # pragma: no cover

    return _run_default_replay(Path(args.log))


def _run_default_replay(path: Path) -> int:
    if not path.exists():
        print(f"replay: log file not found: {path}", file=sys.stderr)
        return 2
    state = replay_log(path).to_state()
    print(json.dumps(state, indent=2))
    return 0


def _run_agent_activity(path: Path) -> int:
    if not path.exists():
        print(
            f"replay --agent-activity: log file not found: {path}",
            file=sys.stderr,
        )
        return 2
    summary = summarize(path)
    print(_render_agent_activity(summary))
    return 0


def _render_agent_activity(summary: AgentActivitySummary) -> str:
    lines: list[str] = [
        f"total proposals: {summary.total_proposals}",
        "by decision:",
    ]
    for decision in sorted(summary.by_decision):
        lines.append(f"  {decision}: {summary.by_decision[decision]}")
    lines.append("by agent:")
    for agent in sorted(summary.by_agent):
        lines.append(f"  {agent}: {summary.by_agent[agent]}")
    lines.append("by agent_id:")
    for agent_id in sorted(summary.by_agent_id, key=_agent_id_sort_key):
        label = _LEGACY_AGENT_ID_LABEL if agent_id is None else agent_id
        lines.append(f"  {label}: {summary.by_agent_id[agent_id]}")
    lines.append(f"delegations minted: {summary.delegations_minted}")
    lines.append(
        f"delegations consumed by cart: {summary.delegations_consumed_by_cart}"
    )
    lines.append(f"orphan delegations: {summary.orphan_delegations}")
    return "\n".join(lines)


def _agent_id_sort_key(value: str | None) -> tuple[int, str]:
    """Sort the ``by_agent_id`` rows alphabetically, with ``None``
    (legacy) pinned LAST so the operator sees the named instances
    first and the legacy gap at the bottom of the list.
    """

    if value is None:
        return (1, "")
    return (0, value)


if __name__ == "__main__":
    raise SystemExit(main())
