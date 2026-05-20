"""HTTP client for FastFlowLM (NPU) — Ollama-compatible API.

Same role as :mod:`agents.lemonade_client` (fallback parser) but talks
to FastFlowLM's NPU-accelerated server. Used when Lemonade is busy or
unreachable. The two clients are interchangeable; the supervisor picks
one based on configuration.
"""

from __future__ import annotations

import json
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
    allow_remote: bool = False


def normalize(
    phrase: str, cart_shape: dict[str, Any], config: FLMConfig
) -> NormalizedPhrase | None:
    """Ask the local FastFlowLM server to normalize ``phrase``.

    Returns ``None`` on disabled, unreachable, timed-out, or malformed
    responses. Never raises.
    """

    if not config.enabled or not phrase.strip():
        return None
    if not _validate_url(config.url, allow_remote=config.allow_remote):
        return None

    # FLM follows the Ollama API: /api/generate takes a flat string
    # prompt, not a structured messages array. Compose the system rule,
    # the cart context, and the attendant phrase into one block. The
    # `format: "json"` field tells the model to return JSON.
    try:
        user_payload = json.dumps({"phrase": phrase, "cart_items": cart_shape.get("items", [])})
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
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None

    try:
        envelope = json.loads(raw)
    except (ValueError, TypeError):
        return None
    parsed = _parse_inner_json(envelope.get("response", "{}"))
    if parsed is None:
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


def _parse_inner_json(text: str) -> dict[str, Any] | None:
    """Parse the ``response`` field of an Ollama-compatible /api/generate
    envelope into a dict, tolerating three common malformations seen
    from small models (e.g. qwen3:0.6b) that ignore ``format: "json"``:

    1. **Pristine JSON** — fast path. ``json.loads`` straight up.
    2. **Markdown-fenced JSON** — ``"```json\\n{...}\\n```"`` or just
       ``"```\\n{...}\\n```"``. Strip the fence and retry.
    3. **First-balanced-object** — model prepended chain-of-thought
       prose or appended garbage / extra braces. Walk the string,
       extract the first ``{...}`` substring with balanced braces
       (string-literal-aware so a brace inside ``"..."`` doesn't
       count), and parse that.

    Returns the parsed dict, or ``None`` if no recoverable JSON
    object is present. This is a *tolerance* layer, not a sanitizer
    — the caller still checks for the ``candidate`` field.
    """

    if not isinstance(text, str) or not text.strip():
        return None

    # 1. Pristine JSON.
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except (ValueError, TypeError):
        pass

    # 2. Markdown fence — accept ```json, ```JSON, or bare ```.
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the opening fence (with optional language tag) and the
        # closing fence, then retry.
        first_newline = stripped.find("\n")
        if first_newline != -1:
            inner = stripped[first_newline + 1 :]
            if inner.endswith("```"):
                inner = inner[:-3]
            try:
                result = json.loads(inner.strip())
                return result if isinstance(result, dict) else None
            except (ValueError, TypeError):
                pass

    # 3. First balanced ``{...}`` (string-literal-aware).
    obj = _first_balanced_object(text)
    if obj is None:
        return None
    try:
        result = json.loads(obj)
        return result if isinstance(result, dict) else None
    except (ValueError, TypeError):
        return None


def _first_balanced_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` substring in ``text`` whose
    braces are balanced, treating brace characters inside double-
    quoted JSON strings as opaque content (i.e. ``{"a":"}"}`` is
    one object, not malformed).

    Returns ``None`` if no opening brace is present or no balanced
    closing brace is found.
    """

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


__all__ = ["FLMConfig", "normalize"]
