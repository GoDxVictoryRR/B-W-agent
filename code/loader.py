"""
loader.py — Stage 0: Data Loader & Joiner

Loads every input CSV into typed dataclasses/dicts with correct types.
All monetary values -> Decimal, all dates -> datetime.date.
Joins are explicit; nothing is inferred from column naming.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dec(val: str) -> Optional[Decimal]:
    """Parse a string to Decimal; return None if blank."""
    val = val.strip()
    if not val:
        return None
    try:
        return Decimal(val)
    except InvalidOperation:
        raise ValueError(f"Cannot parse Decimal from {val!r}")


def _date(val: str) -> Optional[date]:
    """Parse YYYY-MM-DD to datetime.date; return None if blank."""
    val = val.strip()
    if not val:
        return None
    return date.fromisoformat(val)


def _bool_str(val: str) -> bool:
    """Parse 'true'/'false' string -> bool (schema says never a Python bool in CSV)."""
    return val.strip().lower() == "true"


def _pipe(val: str) -> list[str]:
    """Split a pipe-delimited string to list; empty string -> []."""
    val = val.strip()
    if not val:
        return []
    return [v.strip() for v in val.split("|") if v.strip()]


def _int_or_none(val: str) -> Optional[int]:
    val = val.strip()
    if not val:
        return None
    return int(val)


# ---------------------------------------------------------------------------
# Typed dataclasses — one per CSV table
# ---------------------------------------------------------------------------

@dataclass
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass
class FinancialProfile:
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: list[str]
    expense_categories_to_protect: list[str]
    expense_categories_user_is_willing_to_reduce: list[str]
    expense_categories_user_is_willing_to_stop: list[str]
    payment_methods_user_will_consider: list[str]
    max_installment_months: Optional[int]


@dataclass
class FinancialEvent:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str                  # credit | debit | non_cash
    amount: Optional[Decimal]       # None = blank; resolve from image
    currency: str
    event_date: date
    settlement_date: Optional[date]
    status: str                     # settled | pending | scheduled | failed | cancelled | unrealized
    linked_event_id: Optional[str]
    flexibility: str                # fixed | reducible | stoppable | reducible_or_stoppable
    minimum_allowed_amount: Optional[Decimal]


@dataclass
class ExchangeRate:
    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str             # full_payment | installments
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: Optional[int]
    financing_fee: Decimal
    total_payable_amount: Decimal


@dataclass
class Message:
    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    sent_at: str                    # keep as str; ordering done lexicographically (ISO8601)
    source_type: str
    message_text: str


@dataclass
class ImageRecord:
    image_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]


# ---------------------------------------------------------------------------
# Parsed & joined dataset
# ---------------------------------------------------------------------------

@dataclass
class Dataset:
    requests: list[Request]
    profiles: dict[str, FinancialProfile]          # user_id -> profile
    events: list[FinancialEvent]
    events_by_user: dict[str, list[FinancialEvent]]
    events_by_id: dict[str, FinancialEvent]
    exchange_rates: list[ExchangeRate]
    payment_options_by_request: dict[str, list[PaymentOption]]
    messages_by_request: dict[str, list[Message]]
    messages_by_event: dict[str, list[Message]]
    images_by_event: dict[str, ImageRecord]
    images_by_request: dict[str, list[ImageRecord]]


# ---------------------------------------------------------------------------
# Loaders — one function per CSV
# ---------------------------------------------------------------------------

def _load_requests(path: Path) -> list[Request]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            try:
                rows.append(Request(
                    request_id=row["request_id"].strip(),
                    user_id=row["user_id"].strip(),
                    request_date=_date(row["request_date"]),
                    request_type=row["request_type"].strip(),
                    requested_amount=_dec(row["requested_amount"]),
                    desired_completion_date=_date(row["desired_completion_date"]),
                    allows_partial_payment=_bool_str(row["allows_partial_payment"]),
                    request_text=row["request_text"].strip(),
                ))
            except Exception as e:
                raise ValueError(f"requests.csv row {i}: {e}")
    logger.info("Loaded %d requests", len(rows))
    return rows


def _load_profiles(path: Path) -> dict[str, FinancialProfile]:
    profiles = {}
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            try:
                p = FinancialProfile(
                    user_id=row["user_id"].strip(),
                    home_currency=row["home_currency"].strip(),
                    current_available_balance=_dec(row["current_available_balance"]),
                    minimum_balance_to_keep=_dec(row["minimum_balance_to_keep"]),
                    financial_priorities=_pipe(row["financial_priorities"]),
                    expense_categories_to_protect=_pipe(row["expense_categories_to_protect"]),
                    expense_categories_user_is_willing_to_reduce=_pipe(row["expense_categories_user_is_willing_to_reduce"]),
                    expense_categories_user_is_willing_to_stop=_pipe(row["expense_categories_user_is_willing_to_stop"]),
                    payment_methods_user_will_consider=_pipe(row["payment_methods_user_will_consider"]),
                    max_installment_months=_int_or_none(row["max_installment_months"]),
                )
                profiles[p.user_id] = p
            except Exception as e:
                raise ValueError(f"financial_profiles.csv row {i}: {e}")
    logger.info("Loaded %d financial profiles", len(profiles))
    return profiles


def _load_events(path: Path) -> list[FinancialEvent]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            try:
                rows.append(FinancialEvent(
                    event_id=row["event_id"].strip(),
                    user_id=row["user_id"].strip(),
                    event_type=row["event_type"].strip(),
                    description=row["description"].strip(),
                    category=row["category"].strip(),
                    direction=row["direction"].strip(),
                    amount=_dec(row["amount"]),             # None if blank
                    currency=row["currency"].strip(),
                    event_date=_date(row["event_date"]),
                    settlement_date=_date(row["settlement_date"]),
                    status=row["status"].strip(),
                    linked_event_id=row["linked_event_id"].strip() or None,
                    flexibility=row["flexibility"].strip(),
                    minimum_allowed_amount=_dec(row["minimum_allowed_amount"]),
                ))
            except Exception as e:
                raise ValueError(f"financial_events.csv row {i}: {e}")
    logger.info("Loaded %d financial events", len(rows))
    return rows


def _load_exchange_rates(path: Path) -> list[ExchangeRate]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            try:
                rows.append(ExchangeRate(
                    rate_date=_date(row["rate_date"]),
                    from_currency=row["from_currency"].strip(),
                    to_currency=row["to_currency"].strip(),
                    rate=_dec(row["rate"]),
                ))
            except Exception as e:
                raise ValueError(f"exchange_rates.csv row {i}: {e}")
    logger.info("Loaded %d exchange rates", len(rows))
    return rows


def _load_payment_options(path: Path) -> dict[str, list[PaymentOption]]:
    by_request: dict[str, list[PaymentOption]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            try:
                opt = PaymentOption(
                    payment_option_id=row["payment_option_id"].strip(),
                    request_id=row["request_id"].strip(),
                    payment_method=row["payment_method"].strip(),
                    payment_amount=_dec(row["payment_amount"]),
                    number_of_payments=int(row["number_of_payments"].strip()),
                    first_payment_date=_date(row["first_payment_date"]),
                    payment_frequency_days=_int_or_none(row["payment_frequency_days"]),
                    financing_fee=_dec(row["financing_fee"]),
                    total_payable_amount=_dec(row["total_payable_amount"]),
                )
                by_request.setdefault(opt.request_id, []).append(opt)
            except Exception as e:
                raise ValueError(f"request_payment_options.csv row {i}: {e}")
    logger.info("Loaded payment options for %d requests", len(by_request))
    return by_request


def _load_messages(path: Path) -> list[Message]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            try:
                rows.append(Message(
                    message_id=row["message_id"].strip(),
                    user_id=row["user_id"].strip(),
                    request_id=row["request_id"].strip() or None,
                    related_event_id=row["related_event_id"].strip() or None,
                    sent_at=row["sent_at"].strip(),
                    source_type=row["source_type"].strip(),
                    message_text=row["message_text"].strip(),
                ))
            except Exception as e:
                raise ValueError(f"messages.csv row {i}: {e}")
    logger.info("Loaded %d messages", len(rows))
    return rows


def _load_images(path: Path) -> list[ImageRecord]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            try:
                rows.append(ImageRecord(
                    image_id=row["image_id"].strip(),
                    user_id=row["user_id"].strip(),
                    request_id=row["request_id"].strip() or None,
                    related_event_id=row["related_event_id"].strip() or None,
                ))
            except Exception as e:
                raise ValueError(f"images.csv row {i}: {e}")
    logger.info("Loaded %d image records", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_dataset(data_dir: Path) -> Dataset:
    """
    Load and join all input CSVs.  Call this once at startup.

    Raises ValueError with a precise CSV row reference on any parse failure.
    """
    data_dir = Path(data_dir)

    requests = _load_requests(data_dir / "requests.csv")
    profiles = _load_profiles(data_dir / "financial_profiles.csv")
    events = _load_events(data_dir / "financial_events.csv")
    exchange_rates = _load_exchange_rates(data_dir / "exchange_rates.csv")
    payment_options_by_request = _load_payment_options(data_dir / "request_payment_options.csv")
    messages = _load_messages(data_dir / "messages.csv")
    images = _load_images(data_dir / "images.csv")

    # --- Build indexes ---
    events_by_user: dict[str, list[FinancialEvent]] = {}
    events_by_id: dict[str, FinancialEvent] = {}
    for e in events:
        events_by_user.setdefault(e.user_id, []).append(e)
        events_by_id[e.event_id] = e

    messages_by_request: dict[str, list[Message]] = {}
    messages_by_event: dict[str, list[Message]] = {}
    for m in messages:
        if m.request_id:
            messages_by_request.setdefault(m.request_id, []).append(m)
        if m.related_event_id:
            messages_by_event.setdefault(m.related_event_id, []).append(m)

    images_by_event: dict[str, ImageRecord] = {}
    images_by_request: dict[str, list[ImageRecord]] = {}
    for img in images:
        if img.related_event_id:
            images_by_event[img.related_event_id] = img
        if img.request_id:
            images_by_request.setdefault(img.request_id, []).append(img)

    logger.info("Dataset joined: %d requests, %d users, %d events",
                len(requests), len(profiles), len(events))

    return Dataset(
        requests=requests,
        profiles=profiles,
        events=events,
        events_by_user=events_by_user,
        events_by_id=events_by_id,
        exchange_rates=exchange_rates,
        payment_options_by_request=payment_options_by_request,
        messages_by_request=messages_by_request,
        messages_by_event=messages_by_event,
        images_by_event=images_by_event,
        images_by_request=images_by_request,
    )
