"""Replay an event log and print the resulting state."""

from __future__ import annotations

import json
import sys

from lemonade_cashier.audit.replay import replay_log


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/replay.py LOG.jsonl", file=sys.stderr)
        raise SystemExit(2)
    state = replay_log(sys.argv[1]).to_state()
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
