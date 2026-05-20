"""Tests for the FastFlowLM HTTP client's response parsing.

The strict ``json.loads`` of the inner ``response`` field was silently
dropping every reply from small models (e.g. qwen3:0.6b) that ignore
the ``format: "json"`` instruction and wrap their output in a markdown
fence — or that emit one extra brace at the tail. This file pins the
tolerant-parse behavior so the bug can't regress.

The tests use ``monkeypatch`` to swap ``urllib.request.urlopen`` with
a fake context manager that yields a canned response body. No live
model server is touched.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from lemonade_cashier.agents.flm_client import FLMConfig
from lemonade_cashier.agents.flm_client import normalize as flm_normalize


@contextmanager
def _fake_response(body: str) -> Iterator[io.BytesIO]:
    yield io.BytesIO(body.encode("utf-8"))


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, response_body: str) -> None:
    """Patch :func:`urllib.request.urlopen` to return ``response_body``
    for the next call. ``response_body`` is the *full envelope* the
    Ollama-compatible /api/generate endpoint would return — the
    ``{"response": "...inner..."}`` JSON outer.
    """

    def fake(req, timeout=None):
        return _fake_response(response_body)

    from lemonade_cashier.agents import flm_client

    monkeypatch.setattr(flm_client.urllib.request, "urlopen", fake)


def _config() -> FLMConfig:
    return FLMConfig(enabled=True, url="http://127.0.0.1:11434", model="qwen3:0.6b")


# ---------------------------------------------------------------------------
# Happy path — pristine JSON inside the response (Ollama, big models)
# ---------------------------------------------------------------------------


def test_parses_pristine_json_response(monkeypatch: pytest.MonkeyPatch):
    """When the model honors ``format: "json"`` cleanly, the existing
    parse path keeps working byte-for-byte as before."""

    envelope = json.dumps(
        {"response": json.dumps({"candidate": "milk 1 gal", "confidence": 0.91})}
    )
    _patch_urlopen(monkeypatch, envelope)

    r = flm_normalize("milkk", {"items": []}, _config())
    assert r is not None
    assert r.candidate == "milk 1 gal"
    assert abs(r.confidence - 0.91) < 1e-9


# ---------------------------------------------------------------------------
# Tolerant parses
# ---------------------------------------------------------------------------


def test_parses_markdown_fenced_json(monkeypatch: pytest.MonkeyPatch):
    """qwen3:0.6b (and other small models) often wrap their JSON in a
    ``` ```json ... ``` ``` fence, ignoring ``format: "json"``. The
    client must strip the fence and parse what's inside, not silently
    return None."""

    inner = "```json\n{\"candidate\": \"milk 1 gal\", \"confidence\": 0.88}\n```"
    envelope = json.dumps({"response": inner})
    _patch_urlopen(monkeypatch, envelope)

    r = flm_normalize("milkk", {"items": []}, _config())
    assert r is not None, "markdown-fenced JSON must parse"
    assert r.candidate == "milk 1 gal"


def test_parses_response_with_extra_trailing_brace(monkeypatch: pytest.MonkeyPatch):
    """Observed in the wild from qwen3:0.6b: the model emits an extra
    closing brace at the tail (``{...}}``). The first balanced
    ``{...}`` substring is the real payload — peel it out and parse."""

    inner = '{"candidate": "eggs dozen", "confidence": 0.7}}  garbage tail'
    envelope = json.dumps({"response": inner})
    _patch_urlopen(monkeypatch, envelope)

    r = flm_normalize("egz", {"items": []}, _config())
    assert r is not None, "extra-brace JSON must parse to the first balanced object"
    assert r.candidate == "eggs dozen"


def test_parses_markdown_fence_plus_extra_brace(monkeypatch: pytest.MonkeyPatch):
    """Combined: the inner response is markdown-fenced AND has a
    trailing extra brace. Both layers of tolerance must compose."""

    inner = "```json\n{\"candidate\": \"banana\", \"confidence\": 0.95}}\n```"
    envelope = json.dumps({"response": inner})
    _patch_urlopen(monkeypatch, envelope)

    r = flm_normalize("banaan", {"items": []}, _config())
    assert r is not None
    assert r.candidate == "banana"


def test_parses_response_with_thinking_prefix(monkeypatch: pytest.MonkeyPatch):
    """Some small models prepend ``<think>...</think>`` or chain-of-
    thought prose before the JSON. Find the first balanced ``{...}``
    in the response and parse that."""

    inner = (
        "<think>The phrase 'breeed' looks like bread.</think>\n"
        "{\"candidate\": \"bread loaf\", \"confidence\": 0.8}"
    )
    envelope = json.dumps({"response": inner})
    _patch_urlopen(monkeypatch, envelope)

    r = flm_normalize("breeed", {"items": []}, _config())
    assert r is not None
    assert r.candidate == "bread loaf"


# ---------------------------------------------------------------------------
# Still rejected — non-recoverable garbage
# ---------------------------------------------------------------------------


def test_returns_none_when_response_has_no_json_at_all(
    monkeypatch: pytest.MonkeyPatch,
):
    """A response with no ``{`` anywhere can't be salvaged. Return
    None — the supervisor writes an unreachable proposal and the
    deterministic path takes over."""

    envelope = json.dumps({"response": "I refuse to answer."})
    _patch_urlopen(monkeypatch, envelope)

    r = flm_normalize("x", {"items": []}, _config())
    assert r is None


def test_returns_none_when_candidate_field_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    """Even if the inner JSON parses, a missing or empty ``candidate``
    field is treated as no useful proposal."""

    envelope = json.dumps({"response": json.dumps({"confidence": 0.9})})
    _patch_urlopen(monkeypatch, envelope)

    r = flm_normalize("x", {"items": []}, _config())
    assert r is None
