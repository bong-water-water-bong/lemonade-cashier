"""Optional GAIA SDK bridge.

GAIA 0.18.1 ships a Python SDK that provides chat, RAG, MCP, voice,
and a fleet of integration agents (Blender, Jira, Docker, email, …).
The cashier doesn't depend on any of that, but if GAIA is installed
this module can route an attendant's natural-language question
("what was my last transaction?") to a GAIA agent without leaking
state outside the cashier process.

If GAIA isn't importable, the bridge silently disables itself.

All calls are wrapped in a thread-level timeout so a hung GAIA process
can never stall the cashier. The default mirrors
``LC_LEMONADE_TIMEOUT_SEC``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover — exercised only when GAIA is installed
    import gaia as _gaia  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — exercised by the default test env
    gaia: Any | None = None
else:  # pragma: no cover — exercised only when GAIA is installed
    gaia = _gaia


DEFAULT_TIMEOUT_SEC = 2.0

# Keys that must never appear in any payload we send to GAIA (or any
# other external agent). The list is intentionally generous — if a key
# name looks like it could carry a secret, we refuse the call rather
# than risk exfiltration via prompt injection.
_SENSITIVE_KEYS = frozenset(
    {
        "attendant_id",
        "attendantid",
        "pin",
        "pin_hash",
        "pinhash",
        "till_key",
        "tillkey",
        "safe_combo",
        "safecombo",
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
        "card_number",
        "cardnumber",
        "cvv",
    }
)


def _contains_sensitive(payload: object) -> bool:
    """Walk ``payload`` and return True if any key name is sensitive."""

    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and key.lower().replace("-", "_") in _SENSITIVE_KEYS:
                return True
            if _contains_sensitive(value):
                return True
    elif isinstance(payload, (list, tuple)):
        return any(_contains_sensitive(item) for item in payload)
    return False


@dataclass(frozen=True)
class GAIABridge:
    available: bool
    timeout_sec: float = DEFAULT_TIMEOUT_SEC

    def ask(self, prompt: str, *, cart_state: dict[str, object]) -> str | None:
        """Send a prompt to a local GAIA agent and return its reply.

        ``cart_state`` is sent to GAIA verbatim. It MUST NOT contain
        attendant IDs, PIN hashes, till keys, or any other secret —
        ``_SENSITIVE_KEYS`` enumerates the names we refuse. Callers are
        expected to pass the cart's *public* shape only (items,
        totals); see :meth:`~lemonade_cashier.agents.supervisor.Supervisor._cart_shape`.

        Returns ``None`` if GAIA isn't available, ``cart_state`` would
        leak a credential, the call fails, or the call exceeds
        ``timeout_sec``. The caller must treat the response as
        untrusted text.
        """

        if not self.available or gaia is None:  # pragma: no cover
            return None
        if _contains_sensitive(cart_state):
            return None

        def _call() -> str:
            client = gaia.Client()
            reply = client.chat(
                prompt=prompt,
                context={"cart": cart_state},
                stream=False,
                tools=[],
            )
            return str(reply.text)[:2000]

        # Use a thread pool to give us a hard wall-clock timeout even
        # when the GAIA SDK doesn't accept a timeout kwarg.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            try:
                return future.result(timeout=self.timeout_sec)
            except FuturesTimeout:  # pragma: no cover — hard to exercise w/o GAIA
                future.cancel()
                return None
            except Exception:
                return None


def discover(timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> GAIABridge:
    """Return a :class:`GAIABridge` that's ``available`` iff GAIA imports."""

    return GAIABridge(available=gaia is not None, timeout_sec=timeout_sec)


__all__ = ["DEFAULT_TIMEOUT_SEC", "GAIABridge", "add_sensitive_key", "discover"]


def add_sensitive_key(name: str) -> frozenset[str]:
    """Return a new frozenset with ``name`` added to the sensitive deny-list."""

    global _SENSITIVE_KEYS
    _SENSITIVE_KEYS = _SENSITIVE_KEYS | {name.lower().replace("-", "_")}
    return _SENSITIVE_KEYS
