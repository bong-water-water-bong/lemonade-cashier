"""Hashed PIN store for supervisor-PIN-required operations.

Design constraints (see ``docs/SAFETY.md``):

* PINs **never** appear in cleartext anywhere on disk or in the event
  log. Only ``(salt, derived_key)`` pairs are stored.
* PIN verification uses PBKDF2-HMAC-SHA256 with a high iteration
  count, so brute-forcing a stolen ``pins.json`` is costly enough that
  even a 4-digit PIN takes meaningful time per guess.
* PIN setting and verification are **side-effect-free for the event
  log**. The lockout module (:mod:`safety.lockout`) is responsible for
  writing ``safety.pin.failed`` / ``safety.pin.ok`` events; this module
  just answers "does this PIN match?". This split keeps the secret
  surface and the audit surface separate.
* No PIN value is ever passed to a network client. The
  :mod:`agents.gaia_bridge` deny-list already includes ``pin`` and
  ``pin_hash``; this module never produces output that an LLM could
  see.

The store is a JSON file:

::

    {
      "version": 1,
      "kdf": "pbkdf2_sha256",
      "iterations": 200000,
      "pins": {
        "alice":     {"salt": "<hex>", "key": "<hex>"},
        "manager-1": {"salt": "<hex>", "key": "<hex>"}
      }
    }

By convention ``data/pins.json`` is .gitignore'd. The file path is
configurable so tests use a tmp file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
DEFAULT_PIN_STORE: Final = PROJECT_ROOT / "data" / "pins.json"

# PBKDF2 iterations. 200_000 is the OWASP 2023 recommended minimum for
# PBKDF2-SHA256. Bumping later is safe — the store records the count
# used per-entry so old entries still verify.
DEFAULT_ITERATIONS: Final = 200_000
SALT_BYTES: Final = 16
KEY_BYTES: Final = 32
MIN_PIN_LENGTH: Final = 4
MAX_PIN_LENGTH: Final = 32


class PinError(ValueError):
    """Raised when PIN setting or verification has a precondition error.

    Note: a *wrong* PIN does NOT raise PinError — it returns False from
    :func:`verify_pin`. PinError is for misuse (PIN too short, store
    file corrupt, etc.), not for unauthorized access attempts.
    """


@dataclass(frozen=True)
class PinStoreState:
    """Read-only summary of who has a PIN configured. PIN values are NOT exposed."""

    actors: tuple[str, ...]
    iterations: int


def _resolve_path(path: Path | str | None) -> Path | str:
    """Return ``path`` if supplied, otherwise the *current* module default.

    Resolved at *call* time so that monkey-patching ``DEFAULT_PIN_STORE``
    (in tests, or for per-shift PIN stores at runtime) works as users
    intuitively expect. If we defaulted to ``DEFAULT_PIN_STORE`` in the
    signature itself, Python would capture the constant value at module
    import — a classic footgun.
    """

    if path is not None:
        return path
    return DEFAULT_PIN_STORE


def set_pin(
    actor_id: str, pin: str, *, path: Path | str | None = None
) -> None:
    """Store ``pin`` for ``actor_id``. Overwrites any prior entry."""

    actor_id = _validate_actor_id(actor_id)
    _validate_pin(pin)

    target = _resolve_path(path)
    store = _load(target)
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(pin, salt, store.get("iterations", DEFAULT_ITERATIONS))
    store.setdefault("pins", {})[actor_id] = {
        "salt": salt.hex(),
        "key": key.hex(),
    }
    _save(target, store)


def verify_pin(
    actor_id: str, pin: str, *, path: Path | str | None = None
) -> bool:
    """Return True iff ``pin`` matches the stored value for ``actor_id``.

    Returns False on any of: actor not in store, PIN mismatch, missing
    store file. Never raises for the wrong-PIN case — only for store
    corruption.
    """

    actor_id = _validate_actor_id(actor_id)
    try:
        _validate_pin(pin)
    except PinError:
        # Bad PIN shape isn't a verification error; it's still "no match".
        return False

    target = _resolve_path(path)
    store = _load(target)
    entry = store.get("pins", {}).get(actor_id)
    if not entry:
        return False
    try:
        stored_key = bytes.fromhex(entry["key"])
        salt = bytes.fromhex(entry["salt"])
    except (KeyError, ValueError) as exc:
        raise PinError(f"pin store entry for {actor_id!r} is corrupt: {exc}") from exc

    iterations = store.get("iterations", DEFAULT_ITERATIONS)
    candidate = _derive(pin, salt, iterations)
    # Constant-time comparison — the timing of a wrong-PIN return must
    # not leak any bits of the stored key.
    return hmac.compare_digest(candidate, stored_key)


def remove_pin(
    actor_id: str, *, path: Path | str | None = None
) -> bool:
    """Delete an actor's PIN entry. Returns True if an entry was removed."""

    actor_id = _validate_actor_id(actor_id)
    target = _resolve_path(path)
    store = _load(target)
    pins = store.get("pins", {})
    if actor_id not in pins:
        return False
    del pins[actor_id]
    _save(target, store)
    return True


def store_state(path: Path | str | None = None) -> PinStoreState:
    """Return the *list of actors* with PINs configured, no PIN data."""

    store = _load(_resolve_path(path))
    return PinStoreState(
        actors=tuple(sorted(store.get("pins", {}).keys())),
        iterations=int(store.get("iterations", DEFAULT_ITERATIONS)),
    )


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


def _validate_actor_id(actor_id: str) -> str:
    if not isinstance(actor_id, str):
        raise PinError(f"actor_id must be a string; got {type(actor_id).__name__}")
    cleaned = actor_id.strip().casefold()
    if not cleaned:
        raise PinError("actor_id must be non-empty")
    return cleaned


def _validate_pin(pin: str) -> None:
    if not isinstance(pin, str):
        raise PinError(f"pin must be a string; got {type(pin).__name__}")
    if not MIN_PIN_LENGTH <= len(pin) <= MAX_PIN_LENGTH:
        raise PinError(
            f"pin length must be in [{MIN_PIN_LENGTH}, {MAX_PIN_LENGTH}]"
        )


def _derive(pin: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations, KEY_BYTES)


def _load(path: Path | str) -> dict:
    p = Path(path)
    if not p.exists():
        return {
            "version": 1,
            "kdf": "pbkdf2_sha256",
            "iterations": DEFAULT_ITERATIONS,
            "pins": {},
        }
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PinError(f"pin store {p} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("kdf") != "pbkdf2_sha256":
        raise PinError(f"pin store {p} has unknown shape or KDF")
    return raw


def _save(path: Path | str, store: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file in the same directory then atomic rename.
    # If the cashier crashes mid-write, the existing pins.json stays
    # intact rather than becoming a truncated string.
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
    os.replace(tmp, p)


__all__ = [
    "DEFAULT_ITERATIONS",
    "DEFAULT_PIN_STORE",
    "MAX_PIN_LENGTH",
    "MIN_PIN_LENGTH",
    "PinError",
    "PinStoreState",
    "remove_pin",
    "set_pin",
    "store_state",
    "verify_pin",
]
