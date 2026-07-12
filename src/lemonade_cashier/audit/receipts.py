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
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.money import ZERO, money_str, to_money

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

            # Per-line VAT breakdown (when taxable and rate is known)
            if item.get("taxable") and item.get("vat_rate"):
                vat_rate = str(item["vat_rate"])
                vat_amount = str(item.get("vat_amount", "0.00"))
                vat_line = f"  VAT {vat_rate}  ${vat_amount}"
                lines.append(vat_line.rjust(LINE_WIDTH))

    lines.append("-" * LINE_WIDTH)
    subtotal = str(state.get("subtotal", "0.00"))
    tax = str(state.get("tax", "0.00"))
    total = str(state.get("total", "0.00"))
    lines.append(_kv_line("Subtotal", f"${subtotal}"))
    lines.append(_kv_line("Tax", f"${tax}"))
    lines.append(_kv_line("Total", f"${total}"))

    # VAT breakdown by rate bucket (when per-item VAT data is present)
    vat_buckets = _compute_vat_buckets(items)
    if vat_buckets:
        lines.append("-" * LINE_WIDTH)
        lines.append("VAT breakdown".center(LINE_WIDTH))
        for rate_display, vat_total in vat_buckets:
            lines.append(_kv_line(f"  {rate_display}", f"${vat_total}"))

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


def _compute_vat_buckets(items: object) -> list[tuple[str, str]]:
    """Aggregate VAT amounts by rate bucket.

    Returns a list of (rate_display, vat_total) pairs sorted by rate
    descending. Returns empty list when no per-item VAT data is present
    (backward compat with pre-VAT receipts).
    """
    if not isinstance(items, list):
        return []

    buckets: dict[str, Decimal] = {}
    has_vat_data = False
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("taxable"):
            continue
        vat_rate = item.get("vat_rate")
        vat_amount = item.get("vat_amount")
        if vat_rate is None or vat_amount is None:
            continue
        has_vat_data = True
        rate_key = str(vat_rate)
        try:
            amount = to_money(vat_amount)
        except Exception:
            continue
        buckets[rate_key] = buckets.get(rate_key, ZERO) + amount

    if not has_vat_data:
        return []

    sorted_buckets = sorted(buckets.items(), key=lambda x: _rate_sort_key(x[0]), reverse=True)
    return [(rate, money_str(amount)) for rate, amount in sorted_buckets]


def _rate_sort_key(rate_display: str) -> Decimal:
    """Extract numeric rate from display string like '15%' or '0.15'."""
    cleaned = rate_display.rstrip("%")
    try:
        return Decimal(cleaned)
    except Exception:
        return ZERO


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
