"""
writer.py — Output CSV writer (Stage 0)

Writes output.csv with the exact column order mandated by schema.md.
Also provides the safe-default row for error cases (harness.md failure policy).
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Exact column order from schema.md — never reorder
OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

# Valid enum values — validated before write (guardrails.md)
VALID_AFFORDABILITY = {
    "affordable_now",
    "affordable_with_plan",
    "affordable_later",
    "not_affordable",
}

VALID_PAYMENT_METHOD = {
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended",
}


@dataclass
class OutputRow:
    """
    One row of output.csv.  All validation lives here.

    Invariants enforced at construction time (guardrails.md hard bounds):
      - 0 <= amount_safe_to_pay <= requested_amount
      - affordability_status in VALID_AFFORDABILITY
      - recommended_payment_method in VALID_PAYMENT_METHOD
      - payment_plan is 'none' or 'DATE:AMOUNT|...' chronological string
      - earliest_date_for_full_payment is '' or 'YYYY-MM-DD'
      - spending_changes_needed is 'none' or pipe-joined stop/reduce_to entries
    """

    request_id: str
    amount_safe_to_pay: Decimal
    requested_amount: Decimal           # used only for validation, not written
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str                   # 'none' or 'YYYY-MM-DD:amount|...'
    earliest_date_for_full_payment: str # 'YYYY-MM-DD' or ''
    spending_changes_needed: str        # 'none' or pipe-joined entries
    decision_explanation: str

    def __post_init__(self) -> None:
        # Hard bounds (guardrails.md)
        if not (Decimal("0") <= self.amount_safe_to_pay <= self.requested_amount):
            raise ValueError(
                f"{self.request_id}: amount_safe_to_pay={self.amount_safe_to_pay} "
                f"not in [0, {self.requested_amount}]"
            )
        if self.affordability_status not in VALID_AFFORDABILITY:
            raise ValueError(
                f"{self.request_id}: invalid affordability_status "
                f"{self.affordability_status!r}"
            )
        if self.recommended_payment_method not in VALID_PAYMENT_METHOD:
            raise ValueError(
                f"{self.request_id}: invalid recommended_payment_method "
                f"{self.recommended_payment_method!r}"
            )

    def as_csv_row(self) -> dict[str, str]:
        """Render to a dict suitable for csv.DictWriter."""
        # Format amount: strip trailing zeros but keep at least 2 decimal places
        amt = self.amount_safe_to_pay
        amt_str = format(amt.normalize(), "f")
        # ensure at least 2 dp
        if "." not in amt_str:
            amt_str += ".00"
        elif len(amt_str.split(".")[1]) < 2:
            amt_str += "0" * (2 - len(amt_str.split(".")[1]))

        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": amt_str,
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": self.earliest_date_for_full_payment,
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }


def safe_default_row(request_id: str, requested_amount: Decimal, reason: str) -> OutputRow:
    """
    Return the conservative safe-default row for error cases (harness.md policy).
    A partial crash that produces this row is better than losing the whole run.
    """
    return OutputRow(
        request_id=request_id,
        amount_safe_to_pay=Decimal("0"),
        requested_amount=requested_amount,
        affordability_status="not_affordable",
        recommended_payment_method="not_recommended",
        payment_plan="none",
        earliest_date_for_full_payment="",
        spending_changes_needed="none",
        decision_explanation=f"Unable to process request due to insufficient data: {reason}",
    )


def write_output_csv(rows: list[OutputRow], out_path: Path) -> None:
    """
    Write output.csv to out_path with the exact required column order.
    Pre-sorts by request_id to ensure deterministic file order.
    """
    rows_sorted = sorted(rows, key=lambda r: r.request_id)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows_sorted:
            writer.writerow(row.as_csv_row())
    logger.info("Wrote %d rows to %s", len(rows), out_path)
