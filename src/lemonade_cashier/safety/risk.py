"""Per-transaction risk scoring.

The score is a float in [0.0, 1.0]. Inputs that move it upward:

* Low-confidence cart lines (model-proposed or fuzzy-matched).
* High void rate within the transaction.
* Cash tender greater than ``LC_RISK_LARGE_CASH``.
* Off-hours timestamps (open at the start, busy mid-day, suspicious
  near close — but we only ding the close window because mornings are
  noisy in legitimate ways).

Outputs above ``warn`` show a UI flag; outputs above ``block`` require
a supervisor PIN to close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ..core.cart import Cart
from ..core.money import to_money


@dataclass(frozen=True)
class RiskInputs:
    cart: Cart
    voids_in_txn: int
    tender: Decimal | None
    closing_hour_local: int  # 0-23; the local clock hour of close


@dataclass(frozen=True)
class RiskScore:
    value: float
    factors: tuple[tuple[str, float], ...]

    def warn(self, threshold: float) -> bool:
        return self.value >= threshold

    def block(self, threshold: float) -> bool:
        return self.value >= threshold

    def to_state(self) -> dict[str, object]:
        return {
            "value": round(self.value, 3),
            "factors": [
                {"name": name, "delta": round(delta, 3)}
                for name, delta in self.factors
            ],
        }


CLOSING_WINDOW_HOURS: tuple[int, ...] = (22, 23, 0, 1, 2)
LARGE_CASH_THRESHOLD = Decimal("100.00")


def score(inputs: RiskInputs) -> RiskScore:
    factors: list[tuple[str, float]] = []

    low_conf_lines = sum(1 for line in inputs.cart.lines if line.confidence < 0.8)
    if low_conf_lines:
        delta = min(0.05 * low_conf_lines, 0.30)
        factors.append((f"{low_conf_lines}_low_confidence_lines", delta))

    model_lines = sum(
        1 for line in inputs.cart.lines if line.source == "model_proposed"
    )
    if model_lines:
        factors.append(("model_proposed_lines", min(0.04 * model_lines, 0.20)))

    if inputs.voids_in_txn >= 2:
        factors.append(("multiple_voids", 0.15))
    elif inputs.voids_in_txn == 1:
        factors.append(("single_void", 0.05))

    if inputs.tender is not None and to_money(inputs.tender) >= LARGE_CASH_THRESHOLD:
        factors.append(("large_cash_tender", 0.10))

    if inputs.closing_hour_local in CLOSING_WINDOW_HOURS:
        factors.append(("closing_window", 0.10))

    total = min(1.0, sum(delta for _, delta in factors))
    return RiskScore(value=total, factors=tuple(factors))


def closing_hour(ts: datetime) -> int:
    """Helper: extract the local clock hour from a datetime."""

    return ts.hour


__all__ = [
    "CLOSING_WINDOW_HOURS",
    "LARGE_CASH_THRESHOLD",
    "RiskInputs",
    "RiskScore",
    "closing_hour",
    "score",
]
