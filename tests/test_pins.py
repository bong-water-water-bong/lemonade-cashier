"""Tests for the hashed PIN store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemonade_cashier.safety.pins import (
    DEFAULT_ITERATIONS,
    MAX_PIN_LENGTH,
    MIN_PIN_LENGTH,
    PinError,
    remove_pin,
    set_pin,
    store_state,
    verify_pin,
)


def test_set_then_verify(tmp_path: Path):
    store = tmp_path / "pins.json"
    set_pin("alice", "1234", path=store)
    assert verify_pin("alice", "1234", path=store)
    assert not verify_pin("alice", "0000", path=store)


def test_verify_unknown_actor(tmp_path: Path):
    store = tmp_path / "pins.json"
    assert not verify_pin("ghost", "1234", path=store)


def test_set_pin_rejects_short(tmp_path: Path):
    with pytest.raises(PinError, match="length"):
        set_pin("alice", "1", path=tmp_path / "pins.json")


def test_set_pin_rejects_long(tmp_path: Path):
    with pytest.raises(PinError, match="length"):
        set_pin("alice", "x" * (MAX_PIN_LENGTH + 1), path=tmp_path / "pins.json")


def test_actor_id_is_canonicalized(tmp_path: Path):
    store = tmp_path / "pins.json"
    set_pin("Alice", "1234", path=store)
    # Lookup by 'alice' (different case + whitespace) still matches.
    assert verify_pin("  ALICE  ", "1234", path=store)
    state = store_state(store)
    assert state.actors == ("alice",)


def test_pin_never_appears_in_store(tmp_path: Path):
    store = tmp_path / "pins.json"
    set_pin("alice", "0451", path=store)
    raw = store.read_text(encoding="utf-8")
    assert "0451" not in raw
    # The store should look like a hex key + hex salt; no plaintext.
    data = json.loads(raw)
    entry = data["pins"]["alice"]
    assert len(bytes.fromhex(entry["key"])) == 32  # KEY_BYTES
    assert len(bytes.fromhex(entry["salt"])) == 16  # SALT_BYTES


def test_iterations_recorded(tmp_path: Path):
    store = tmp_path / "pins.json"
    set_pin("alice", "1234", path=store)
    state = store_state(store)
    assert state.iterations == DEFAULT_ITERATIONS


def test_remove_pin(tmp_path: Path):
    store = tmp_path / "pins.json"
    set_pin("alice", "1234", path=store)
    assert remove_pin("alice", path=store) is True
    assert not verify_pin("alice", "1234", path=store)
    # Idempotent second-remove returns False, no error.
    assert remove_pin("alice", path=store) is False


def test_overwrite_pin(tmp_path: Path):
    store = tmp_path / "pins.json"
    set_pin("alice", "1234", path=store)
    set_pin("alice", "5678", path=store)
    assert not verify_pin("alice", "1234", path=store)
    assert verify_pin("alice", "5678", path=store)


def test_corrupt_store_raises_pinerror(tmp_path: Path):
    store = tmp_path / "pins.json"
    store.write_text("not json at all", encoding="utf-8")
    with pytest.raises(PinError):
        verify_pin("alice", "1234", path=store)


def test_pin_min_length():
    # Sanity that the constant exists and is sane.
    assert MIN_PIN_LENGTH >= 4
