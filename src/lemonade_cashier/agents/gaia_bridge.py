"""Optional GAIA SDK bridge.

GAIA 0.18.1 ships a Python SDK that provides chat, RAG, MCP, voice,
and a fleet of integration agents (Blender, Jira, Docker, email, …).
The cashier doesn't depend on any of that, but if GAIA is installed
this module can route an attendant's natural-language question
("what was my last transaction?") to a GAIA agent without leaking
state outside the cashier process.

If GAIA isn't importable, the bridge silently disables itself.
"""

from __future__ import annotations

from dataclasses import dataclass

try:  # pragma: no cover — exercised only when GAIA is installed
    import gaia  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — exercised by the default test env
    gaia = None  # type: ignore[assignment]


@dataclass(frozen=True)
class GAIABridge:
    available: bool

    def ask(self, prompt: str, *, cart_state: dict[str, object]) -> str | None:
        """Send a prompt to a local GAIA agent and return its reply.

        Returns ``None`` if GAIA isn't available, the call fails, or
        anything looks unsafe (long responses, fenced code blocks). The
        caller must treat the response as untrusted text.
        """

        if not self.available or gaia is None:  # pragma: no cover
            return None
        try:
            # The exact entrypoint differs by GAIA minor version; this
            # is the documented 0.18.x shape. Wrap in a broad except so
            # we never crash the cashier if GAIA changes.
            client = gaia.Client()  # type: ignore[attr-defined]
            reply = client.chat(
                prompt=prompt,
                context={"cart": cart_state},
                stream=False,
                tools=[],
            )
            return str(reply.text)[:2000]
        except Exception:
            return None


def discover() -> GAIABridge:
    """Return a :class:`GAIABridge` that's ``available`` iff GAIA imports."""

    return GAIABridge(available=gaia is not None)


__all__ = ["GAIABridge", "discover"]
