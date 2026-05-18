"""Receipt rendering.

A receipt is a *projection* of a closed transaction's events. It is
never authoritative — :mod:`audit.replay` is. The text renderer is
intentionally line-printer friendly (40 columns, no Unicode beyond
ASCII) so it works with a thermal printer over USB.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.money import money_str

if TYPE_CHECKING:  # avoid a runtime circular import
    from .replay import ReplayState

LINE_WIDTH = 40


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    rendered_at: str
    state: dict[str, object]
    text: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": 1,
                "receipt_id": self.receipt_id,
                "rendered_at": self.rendered_at,
                "state": self.state,
                "text": self.text,
            },
            indent=2,
        )


def render_state(state: dict[str, object], *, receipt_id: str | None = None) -> Receipt:
    """Render a state dict (from :func:`audit.replay.replay`) as a receipt."""

    now = datetime.now(UTC).isoformat(timespec="seconds")
    rid = receipt_id or now.replace(":", "-")
    text = _render_text(state)
    return Receipt(receipt_id=rid, rendered_at=now, state=state, text=text)


def render(replay_state: ReplayState, *, receipt_id: str | None = None) -> Receipt:
    """Convenience: render directly from a :class:`ReplayState`."""

    return render_state(replay_state.to_state(), receipt_id=receipt_id)


def save(receipt: Receipt, directory: Path | str) -> Path:
    """Persist ``receipt`` as ``<directory>/<receipt_id>.json``."""

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{receipt.receipt_id}.json"
    path.write_text(receipt.to_json(), encoding="utf-8")
    return path


def _render_text(state: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("Lemonade Cashier".center(LINE_WIDTH))
    lines.append(str(state.get("opened_at", "")).center(LINE_WIDTH))
    lines.append("-" * LINE_WIDTH)

    items = state.get("items", [])
    if isinstance(items, list):
        for item in items:
            assert isinstance(item, dict)
            qty = item.get("quantity", 1)
            name = str(item.get("name", "?"))
            line_total = str(item.get("line_total", "0.00"))
            left = f"{qty}x {name}"
            right = f"${line_total}"
            spaces = max(1, LINE_WIDTH - len(left) - len(right))
            lines.append(left + (" " * spaces) + right)

    lines.append("-" * LINE_WIDTH)
    subtotal = str(state.get("subtotal", "0.00"))
    tax = str(state.get("tax", "0.00"))
    total = str(state.get("total", "0.00"))
    lines.append(_kv_line("Subtotal", f"${subtotal}"))
    lines.append(_kv_line("Tax", f"${tax}"))
    lines.append(_kv_line("Total", f"${total}"))

    tender = state.get("tender")
    change = state.get("change")
    if tender is not None:
        lines.append(_kv_line("Tendered", f"${money_str_from_state(tender)}"))
    if change is not None:
        lines.append(_kv_line("Change", f"${money_str_from_state(change)}"))

    lines.append("-" * LINE_WIDTH)
    closed = state.get("closed_at")
    if closed:
        lines.append(f"closed: {closed}".center(LINE_WIDTH))
    lines.append("thank you".center(LINE_WIDTH))
    return "\n".join(lines)


def _kv_line(label: str, value: str) -> str:
    spaces = max(1, LINE_WIDTH - len(label) - len(value))
    return label + (" " * spaces) + value


def money_str_from_state(value: object) -> str:
    """Be lenient about state shape — receipts must never crash."""

    if isinstance(value, dict) and "change_due" in value:
        return str(value["change_due"])
    if isinstance(value, str):
        return value
    return money_str(value)  # type: ignore[arg-type]


__all__ = ["Receipt", "render", "render_state", "save"]
