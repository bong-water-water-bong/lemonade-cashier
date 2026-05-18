"""HTTP client for the local Lemonade Server (OpenAI-compatible API).

Used as a **fallback** parser when the rule-based path doesn't produce
a match. The client:

* Uses :mod:`urllib.request` from the standard library — no extra deps.
* Honors a hard ``timeout_sec`` (default 2s) and a hard token budget.
* Returns ``None`` on *any* network error. Callers must degrade
  gracefully.
* Sends only the cart shape and the attendant phrase. Never sends
  identifiers or PINs.

Lemonade Server 10.4.0 listens on ``http://127.0.0.1:8000`` by default
(see ``~/notes/upstream-fixes/lemonade-server`` for the local memlock
fix that lets it actually load NPU models).
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _validate_url(url: str) -> bool:
    """Return True iff ``url`` parses cleanly and uses http(s).

    Without this guard a misconfigured ``LC_LEMONADE_URL=file:///etc/passwd``
    in .env would cause :func:`urllib.request.urlopen` to read a local
    file. This module is supposed to be a network client, nothing else.
    """

    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in _ALLOWED_SCHEMES and bool(parsed.netloc)


@dataclass(frozen=True)
class LemonadeConfig:
    url: str = "http://127.0.0.1:8000"
    model: str = "Qwen3-4B-GGUF"
    timeout_sec: float = 2.0
    max_tokens: int = 64
    enabled: bool = False


@dataclass(frozen=True)
class NormalizedPhrase:
    """A model's proposed normalization of an attendant phrase."""

    candidate: str
    confidence: float
    raw: dict[str, Any]


SYSTEM_PROMPT = (
    "You are a cashier-helper. The attendant typed a short phrase. "
    "Produce a single normalized product phrase that names one item, "
    "lowercase, no quantity, no punctuation. If the phrase already "
    "names a product, return it unchanged. Output JSON only: "
    '{"candidate": "<phrase>", "confidence": <0..1>}.'
)


def normalize(phrase: str, cart_shape: dict[str, Any], config: LemonadeConfig) -> NormalizedPhrase | None:
    """Ask the local Lemonade Server to normalize ``phrase``.

    Returns ``None`` on disabled, unreachable, timed-out, or malformed
    responses. Never raises.
    """

    if not config.enabled or not phrase.strip():
        return None
    if not _validate_url(config.url):
        return None

    body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"phrase": phrase, "cart_items": cart_shape.get("items", [])}
                ),
            },
        ],
        "max_tokens": config.max_tokens,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    try:
        encoded = json.dumps(body).encode("utf-8")
    except (TypeError, ValueError):
        return None

    try:
        request = urllib.request.Request(
            f"{config.url.rstrip('/')}/v1/chat/completions",
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=config.timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
        return None

    try:
        envelope = json.loads(raw)
        content = envelope["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, ValueError, TypeError):
        return None

    candidate = str(parsed.get("candidate", "")).strip().lower()
    if not candidate:
        return None
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return NormalizedPhrase(candidate=candidate, confidence=confidence, raw=parsed)


__all__ = ["LemonadeConfig", "NormalizedPhrase", "SYSTEM_PROMPT", "normalize"]
