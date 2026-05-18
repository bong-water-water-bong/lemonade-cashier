"""Agent capability registry.

Each agent in the system has a single declared **capability surface** —
the set of proposal kinds it's allowed to emit and the set of actor
roles its outputs can claim. The registry is the single source of
truth.

::

    "lemonade":   {kinds: {normalize},      actors: {agent_auto, agent_confirmed}}
    "flm":        {kinds: {normalize},      actors: {agent_auto, agent_confirmed}}
    "qa":         {kinds: {chat_response},  actors: {}}        # read-only
    "summarizer": {kinds: {summarize},      actors: {}}        # presentation only
    "gaia":       {kinds: {chat_response},  actors: {}}        # read-only Q&A

Adding a new capability to an existing agent — or introducing a new
agent — requires editing this table *and* updating the corresponding
tests. The check is centralized so future contributors can't quietly
let, say, the Q&A agent start emitting ``cart.add`` proposals.

The registry is **enforced** by :func:`assert_can_emit` which the
agent modules call before writing any ``agent.proposal`` event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet


@dataclass(frozen=True)
class Capability:
    """One agent's permitted proposal-kinds and actor-roles."""

    kinds: FrozenSet[str]
    actors: FrozenSet[str]


# The deny-list is intentionally implicit: "if it's not in this dict, the
# agent doesn't exist." Adding a new agent requires editing the table.
REGISTRY: dict[str, Capability] = {
    "lemonade": Capability(
        kinds=frozenset({"normalize"}),
        actors=frozenset({"agent_auto", "agent_confirmed"}),
    ),
    "flm": Capability(
        kinds=frozenset({"normalize"}),
        actors=frozenset({"agent_auto", "agent_confirmed"}),
    ),
    "qa": Capability(
        kinds=frozenset({"chat_response"}),
        actors=frozenset(),  # read-only — no cart actor
    ),
    "summarizer": Capability(
        kinds=frozenset({"summarize"}),
        actors=frozenset(),  # presentation only
    ),
    "gaia": Capability(
        kinds=frozenset({"chat_response"}),
        actors=frozenset(),
    ),
}


class CapabilityError(RuntimeError):
    """Raised when an agent attempts a proposal outside its capability surface."""


def assert_can_emit(agent: str, kind: str) -> None:
    """Raise :class:`CapabilityError` unless ``agent`` is allowed to emit ``kind``.

    Called at the top of every agent's proposal-writing path. Lifting
    the check out of the agents themselves and into a shared helper
    means a future contributor can't quietly bypass the registry — the
    bypass would be locally visible at the call site.
    """

    cap = REGISTRY.get(agent)
    if cap is None:
        raise CapabilityError(
            f"unknown agent {agent!r}; add it to agents.registry.REGISTRY first"
        )
    if kind not in cap.kinds:
        raise CapabilityError(
            f"agent {agent!r} is not permitted to emit kind={kind!r}; "
            f"its allowed kinds are {sorted(cap.kinds)}"
        )


def assert_actor_allowed(agent: str, actor: str) -> None:
    """Raise if ``actor`` is outside ``agent``'s permitted actor set."""

    cap = REGISTRY.get(agent)
    if cap is None:
        raise CapabilityError(f"unknown agent {agent!r}")
    if actor not in cap.actors:
        raise CapabilityError(
            f"agent {agent!r} cannot author cart lines with actor={actor!r}; "
            f"its allowed actors are {sorted(cap.actors) or '(none — read-only)'}"
        )


__all__ = [
    "Capability",
    "CapabilityError",
    "REGISTRY",
    "assert_actor_allowed",
    "assert_can_emit",
]
