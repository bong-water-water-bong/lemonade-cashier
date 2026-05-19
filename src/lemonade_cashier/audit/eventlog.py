"""Append-only, hash-chained JSONL event log.

Each line in the log is a JSON object containing:

* ``seq``     — monotonically increasing integer starting at 1.
* ``ts``      — ISO-8601 timestamp (UTC, with timezone marker).
* ``type``    — event type string ("cart.add", "cit.drop", etc.).
* ``payload`` — opaque type-specific dict.
* ``prev``    — hex SHA-256 of the previous record's serialized
                ``{seq, ts, type, payload, prev}`` triple. The genesis
                event has ``prev = "0" * 64``.
* ``hash``    — hex SHA-256 of this record's
                ``{seq, ts, type, payload, prev}`` JSON.

The hash chain means tampering with any past event invalidates all
subsequent hashes. Verifying integrity is O(n) with no state beyond the
file itself.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

GENESIS_PREV = "0" * 64
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Event:
    seq: int
    ts: str
    type: str
    payload: dict[str, object]
    prev: str
    hash: str

    def to_json_line(self) -> str:
        # Preserve key order for stable hashing across implementations.
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


class EventLogError(RuntimeError):
    """Raised when the event log is malformed or fails verification."""


class EventLog:
    """Open an append-only event log at ``path``.

    The file is created if missing. Concurrent writers are *not*
    supported (one cashier process per till).
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_seq, self._last_hash = self._scan_tail()

    def append(
        self,
        event_type: str,
        payload: dict[str, object],
        *,
        ts: str | None = None,
    ) -> Event:
        """Append a new event and return the resulting :class:`Event`."""

        seq = self._last_seq + 1
        timestamp = ts if ts is not None else _utc_now_iso()
        prev = self._last_hash if self._last_hash else GENESIS_PREV
        body = {
            "seq": seq,
            "ts": timestamp,
            "type": event_type,
            "payload": payload,
            "prev": prev,
        }
        body_hash = _hash_body(body)
        event = Event(
            seq=seq,
            ts=timestamp,
            type=event_type,
            payload=payload,
            prev=prev,
            hash=body_hash,
        )
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(event.to_json_line())
            fh.write("\n")
        self._last_seq = seq
        self._last_hash = body_hash
        return event

    def read_all(self) -> list[Event]:
        return list(self.iter_events())

    def iter_events(self) -> Iterator[Event]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    yield Event(**record)
                except (json.JSONDecodeError, TypeError) as exc:
                    raise EventLogError(f"malformed event at line {line_number}: {exc}") from exc

    def verify(self) -> None:
        """Walk the chain and raise :class:`EventLogError` on tamper.

        Also checks ``ts`` monotonicity: timestamps must be
        non-decreasing along the chain. Without this, a backdated event
        appended out-of-order would still pass the hash check (the hash
        chain only covers the *content* of each event, not the relative
        order of timestamps).
        """

        prev = GENESIS_PREV
        prev_ts = ""
        for index, event in enumerate(self.iter_events(), start=1):
            if event.seq != index:
                raise EventLogError(f"out-of-order seq: expected {index}, got {event.seq}")
            if event.prev != prev:
                raise EventLogError(f"hash chain broken at seq {event.seq}")
            expected_hash = _hash_body(
                {
                    "seq": event.seq,
                    "ts": event.ts,
                    "type": event.type,
                    "payload": event.payload,
                    "prev": event.prev,
                }
            )
            if expected_hash != event.hash:
                raise EventLogError(f"hash mismatch at seq {event.seq}")
            # ISO-8601 lex-compare is correct for monotonically
            # increasing UTC timestamps as long as offsets match (we
            # write Z/+00:00 exclusively).
            if prev_ts and event.ts < prev_ts:
                raise EventLogError(f"non-monotonic ts at seq {event.seq}: {event.ts} < {prev_ts}")
            prev = event.hash
            prev_ts = event.ts

    def _scan_tail(self) -> tuple[int, str | None]:
        last_seq = 0
        last_hash: str | None = None
        if not self.path.exists():
            return last_seq, last_hash
        for event in self.iter_events():
            last_seq = event.seq
            last_hash = event.hash
        return last_seq, last_hash


def replay_events(events: Iterable[Event]) -> list[Event]:
    """Materialize an iterable of events into a list. Pure pass-through.

    Lives here so :mod:`audit.replay` can stay thin.
    """

    return list(events)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _hash_body(body: dict[str, object]) -> str:
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


__all__ = [
    "GENESIS_PREV",
    "SCHEMA_VERSION",
    "Event",
    "EventLog",
    "EventLogError",
    "replay_events",
]
