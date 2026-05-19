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
# Loopback only by default. The whole design of this module is "talk to
# a local model server on this box"; allowing the URL to point anywhere
# else turns the cashier into a credential-exfil vector via .env. An
# operator who *really* wants a remote endpoint can override by setting
# LC_REMOTE_LLM_OK=1, which surfaces in the system memory + audit log.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _validate_url(url: str, *, allow_remote: bool = False) -> bool:
    """Return True iff ``url`` parses cleanly, uses http(s), and (unless
    ``allow_remote`` is True) points at a loopback host.

    Catches four classes of misconfiguration:

    * Non-http schemes (``file://``, ``javascript:``, ``ftp://``).
    * Empty netloc.
    * Embedded userinfo, which would let ``http://127.0.0.1@evil.com/``
      slip past a naive substring check while actually resolving to
      evil.com.
    * Non-loopback hostnames when ``allow_remote`` is False.
    """

    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False
    if not parsed.netloc:
        return False
    # urllib parses `user:pass@host` into parsed.username/parsed.hostname;
    # any non-None username means the URL is trying to mask its real host.
    if parsed.username is not None or parsed.password is not None:
        return False
    if allow_remote:
        return True
    host = (parsed.hostname or "").lower()
    return host in _LOOPBACK_HOSTS


@dataclass(frozen=True)
class LemonadeConfig:
    url: str = "http://127.0.0.1:8000"
    model: str = "Qwen3-4B-GGUF"
    timeout_sec: float = 2.0
    max_tokens: int = 64
    enabled: bool = False
    allow_remote: bool = False  # set True only if you intentionally use a non-loopback URL


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


def chat_completions(
    messages: list[dict[str, str]],
    config: LemonadeConfig,
    *,
    response_format: dict[str, str] | None = None,
) -> str | None:
    """Generic chat-completions RPC against the local Lemonade Server.

    Returns the raw assistant content string, or ``None`` on any
    failure (disabled, unreachable, timeout, malformed response, etc.).
    Never raises.

    This is the single entry point for every agent that needs to talk
    to a local LLM. Each agent passes its OWN system prompt so the
    Q&A agent, summarizer, and cart normalizer don't share a contract
    — that distinction is what the registry layer enforces structurally,
    and the prompt layer reflects.
    """

    if not config.enabled:
        return None
    if not _validate_url(config.url, allow_remote=config.allow_remote):
        return None

    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "max_tokens": config.max_tokens,
        "temperature": 0.0,
    }
    if response_format is not None:
        body["response_format"] = response_format

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
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    # An explicit null/missing content is "model returned nothing useful" —
    # return None rather than the literal string "None". Empty string is
    # also "nothing", treated the same way.
    if content is None or content == "":
        return None
    return str(content)


def normalize(phrase: str, cart_shape: dict[str, Any], config: LemonadeConfig) -> NormalizedPhrase | None:
    """Ask the local Lemonade Server to normalize ``phrase``.

    Returns ``None`` on disabled, unreachable, timed-out, or malformed
    responses. Never raises.
    """

    if not phrase.strip():
        return None

    content = chat_completions(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"phrase": phrase, "cart_items": cart_shape.get("items", [])}
                ),
            },
        ],
        config=config,
        response_format={"type": "json_object"},
    )
    if content is None:
        return None

    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
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
