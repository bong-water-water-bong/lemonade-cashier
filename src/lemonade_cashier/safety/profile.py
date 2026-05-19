"""Per-attendant rolling safety profile.

A *profile* aggregates one attendant's behavior from the event log into
counters that the risk engine and the EOS report can consume:

* ``total_transactions``    — how many ``transaction.open`` events.
* ``voids``                 — ``cart.remove_last`` + ``cart.remove_sku``.
* ``low_conf_adds``         — cart lines with confidence < 0.8.
* ``model_proposed_adds``   — cart lines with source == "model_proposed".
* ``cit_drops`` / ``cit_pickups`` / ``cit_drops_witnessed``.
* ``bag_discrepancies``     — ``cit.bag.discrepancy`` events.
* ``pin_failures``          — ``safety.pin.failed`` events.

The profile is **pure** — it derives entirely from the event list. No
mutable state. Two cashier processes therefore produce identical
profiles from the same log.

Attendant identity is canonicalized (strip + casefold) to match the
convention from :mod:`safety.bags` and :mod:`safety.pins`, so the
profile for ``Alice`` and ``alice`` collapses into one entry.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import cast

from ..audit.eventlog import Event


@dataclass(frozen=True)
class AttendantProfile:
    """One attendant's behavioral roll-up."""

    actor_id: str
    total_transactions: int = 0
    voids: int = 0
    low_conf_adds: int = 0
    model_proposed_adds: int = 0
    cit_drops: int = 0
    cit_drops_witnessed: int = 0
    cit_pickups: int = 0
    bag_discrepancies: int = 0
    pin_failures: int = 0
    bags_sealed: int = 0

    @property
    def void_rate(self) -> float:
        """Voids per transaction. Returns 0.0 if no transactions yet."""

        if not self.total_transactions:
            return 0.0
        return self.voids / self.total_transactions

    @property
    def discrepancy_rate(self) -> float:
        """Bag discrepancies per sealed bag. 0.0 if none sealed."""

        if not self.bags_sealed:
            return 0.0
        return self.bag_discrepancies / self.bags_sealed

    def to_state(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "total_transactions": self.total_transactions,
            "voids": self.voids,
            "low_conf_adds": self.low_conf_adds,
            "model_proposed_adds": self.model_proposed_adds,
            "cit_drops": self.cit_drops,
            "cit_drops_witnessed": self.cit_drops_witnessed,
            "cit_pickups": self.cit_pickups,
            "bag_discrepancies": self.bag_discrepancies,
            "bags_sealed": self.bags_sealed,
            "pin_failures": self.pin_failures,
            "void_rate": round(self.void_rate, 4),
            "discrepancy_rate": round(self.discrepancy_rate, 4),
        }


def profiles_from_events(events: Iterable[Event]) -> dict[str, AttendantProfile]:
    """Build a ``{actor_id: AttendantProfile}`` dict from ``events``."""

    # Materialize once. The discrepancy handler below has to scan
    # backwards to find the bag's sealer, and we can't do that against
    # a generator-style iterable (would either crash or skip events).
    # Also lets us pre-index bag-id → sealer so the discrepancy
    # attribution is O(n) total, not O(n^2).
    events_list = list(events)
    bag_sealers: dict[str, str] = {}
    for event in events_list:
        if event.type == "cit.bag.sealed":
            bag_id = event.payload.get("bag_id") if event.payload else None
            attendant = event.payload.get("attendant") if event.payload else None
            if isinstance(bag_id, str) and isinstance(attendant, str):
                bag_sealers[bag_id] = attendant

    counters: dict[str, _Counter] = {}

    def bump(actor: str | None, field_name: str, delta: int = 1) -> None:
        if not isinstance(actor, str) or not actor.strip():
            return
        canon = actor.strip().casefold()
        counter = counters.setdefault(canon, _Counter(actor_id=canon))
        counter.values[field_name] = counter.values.get(field_name, 0) + delta

    for event in events_list:
        payload = cast("dict[str, object]", event.payload or {})
        attendant = payload.get("attendant")
        actor_id = payload.get("actor_id")
        attendant_id = attendant if isinstance(attendant, str) else None
        actor_id_str = actor_id if isinstance(actor_id, str) else None
        if event.type == "transaction.open":
            bump(attendant_id, "total_transactions")
        elif event.type == "cart.remove_last" or event.type == "cart.remove_sku":
            # We don't know which attendant from the event itself; tag
            # everything in the same transaction window. The supervisor
            # writes the attendant id only on transaction.open and
            # cit.* events, so we attribute voids to the most-recent
            # transaction's attendant via a small "current attendant"
            # tracker.
            current = _last_attendant(counters)
            bump(current, "voids")
        elif event.type == "cart.add":
            conf = payload.get("confidence")
            if isinstance(conf, (int, float)) and conf < 0.8:
                bump(_last_attendant(counters), "low_conf_adds")
            if payload.get("source") == "model_proposed":
                bump(_last_attendant(counters), "model_proposed_adds")
        elif event.type == "cit.drop":
            bump(attendant_id, "cit_drops")
        elif event.type == "cit.drop.witnessed":
            bump(attendant_id, "cit_drops_witnessed")
        elif event.type == "cit.pickup":
            bump(attendant_id, "cit_pickups")
        elif event.type == "cit.bag.sealed":
            bump(attendant_id, "bags_sealed")
        elif event.type == "cit.bag.discrepancy":
            # The discrepancy isn't tied to a specific attendant on its
            # own payload — credit it to whoever sealed the bag.
            bag_id = payload.get("bag_id")
            sealer = bag_sealers.get(bag_id) if isinstance(bag_id, str) else None
            bump(sealer, "bag_discrepancies")
        elif event.type == "safety.pin.failed":
            bump(actor_id_str, "pin_failures")

    return {actor: c.freeze() for actor, c in counters.items()}


def profile_for(events: Iterable[Event], actor_id: str) -> AttendantProfile:
    """Convenience: return one attendant's profile, empty if not seen."""

    canon = actor_id.strip().casefold()
    profiles = profiles_from_events(events)
    return profiles.get(canon, AttendantProfile(actor_id=canon))


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


@dataclass
class _Counter:
    actor_id: str
    values: dict[str, int] = field(default_factory=dict)

    def freeze(self) -> AttendantProfile:
        v = self.values
        return AttendantProfile(
            actor_id=self.actor_id,
            total_transactions=v.get("total_transactions", 0),
            voids=v.get("voids", 0),
            low_conf_adds=v.get("low_conf_adds", 0),
            model_proposed_adds=v.get("model_proposed_adds", 0),
            cit_drops=v.get("cit_drops", 0),
            cit_drops_witnessed=v.get("cit_drops_witnessed", 0),
            cit_pickups=v.get("cit_pickups", 0),
            bag_discrepancies=v.get("bag_discrepancies", 0),
            bags_sealed=v.get("bags_sealed", 0),
            pin_failures=v.get("pin_failures", 0),
        )


def _last_attendant(counters: dict[str, _Counter]) -> str | None:
    """Best-effort: the most-recently-seen attendant by transaction count.

    This is heuristic — single-attendant shifts are common, but if two
    cashiers are active on the same till the void attribution can drift.
    For honest attribution the supervisor should write the attendant id
    onto every cart.* event payload (a worthy follow-up).
    """

    if not counters:
        return None
    return max(counters.values(), key=lambda c: c.values.get("total_transactions", 0)).actor_id


__all__ = ["AttendantProfile", "profile_for", "profiles_from_events"]
