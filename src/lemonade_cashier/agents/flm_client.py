"""HTTP client for FastFlowLM (NPU) — Ollama-compatible API.

Same role as :mod:`agents.lemonade_client` (fallback parser) but talks
to FastFlowLM's NPU-accelerated server. Used when Lemonade is busy or
unreachable. The two clients are interchangeable; the supervisor picks
one based on configuration.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .lemonade_client import SYSTEM_PROMPT, NormalizedPhrase, _validate_url


@dataclass(frozen=True)
class FLMConfig:
    url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:4b"
    timeout_sec: float = 2.0
    enabled: bool = False


def normalize(
    phrase: str, cart_shape: dict[str, Any], config: FLMConfig
) -> NormalizedPhrase | None:
    """Ask the local FastFlowLM server to normalize ``phrase``.

    Returns ``None`` on disabled, unreachable, timed-out, or malformed
    responses. Never raises.
    """

    if not config.enabled or not phrase.strip():
        return None
    if not _validate_url(config.url):
        return None

    # FLM follows the Ollama API: /api/generate takes a flat string
    # prompt, not a structured messages array. Compose the system rule,
    # the cart context, and the attendant phrase into one block. The
    # `format: "json"` field tells the model to return JSON.
    try:
        user_payload = json.dumps(
            {"phrase": phrase, "cart_items": cart_shape.get("items", [])}
        )
        body = {
            "model": config.model,
            "prompt": f"{SYSTEM_PROMPT}\n\nINPUT:\n{user_payload}\n\nOUTPUT:",
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 64},
        }
        encoded = json.dumps(body).encode("utf-8")
    except (TypeError, ValueError):
        return None

    try:
        request = urllib.request.Request(
            f"{config.url.rstrip('/')}/api/generate",
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
        parsed = json.loads(envelope.get("response", "{}"))
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


__all__ = ["FLMConfig", "normalize"]
