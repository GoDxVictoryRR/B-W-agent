"""
fx.py — FX Converter (deterministic, Stage 0)

Converts amounts between currencies using exchange_rates.csv.
Rules (schema.md):
  - Rates are monthly snapshots; use exact date first, else closest prior date.
  - No direct ZAR<->IDR, ZAR<->INR, INR<->IDR pairs: chain via USD.
  - ZAR rates disappear after early 2026 — use most recent available.
  - All arithmetic in Decimal (never float).
  - Raise loudly if no rate path exists.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from loader import ExchangeRate

logger = logging.getLogger(__name__)


class FXConverter:
    """
    Immutable FX rate table built from a list of ExchangeRate rows.

    Usage:
        converter = FXConverter(dataset.exchange_rates)
        amount_home = converter.convert(Decimal("1000"), "IDR", "ZAR", as_of=date(2025, 3, 3))
    """

    def __init__(self, rates: list[ExchangeRate]) -> None:
        # Index: (from_currency, to_currency) -> sorted list of (rate_date, rate)
        self._table: dict[tuple[str, str], list[tuple[date, Decimal]]] = {}
        for r in rates:
            key = (r.from_currency, r.to_currency)
            self._table.setdefault(key, []).append((r.rate_date, r.rate))
        # Sort ascending by date for bisect-style lookup
        for key in self._table:
            self._table[key].sort(key=lambda x: x[0])

    def _direct_rate(
        self, from_ccy: str, to_ccy: str, as_of: date
    ) -> Optional[Decimal]:
        """
        Return the most recent rate for (from_ccy, to_ccy) on or before as_of.
        Returns None if no such rate exists at all.
        """
        if from_ccy == to_ccy:
            return Decimal("1")

        # Try (from_ccy -> to_ccy) directly
        key = (from_ccy, to_ccy)
        if key in self._table:
            entries = self._table[key]
            # Walk backward from most-recent to find the latest date <= as_of
            for d, r in reversed(entries):
                if d <= as_of:
                    return r
            # Direct key exists but all dates are AFTER as_of — fall through to inverse

        # Try inverse (to_ccy -> from_ccy) and reciprocate
        inv_key = (to_ccy, from_ccy)
        if inv_key in self._table:
            entries = self._table[inv_key]
            for d, r in reversed(entries):
                if d <= as_of:
                    return Decimal("1") / r
            return None

        return None

    def convert(
        self, amount: Decimal, from_ccy: str, to_ccy: str, as_of: date
    ) -> Decimal:
        """
        Convert `amount` from `from_ccy` to `to_ccy` using rates valid on or
        before `as_of`.

        Tries direct lookup first; if no direct pair exists, chains via USD,
        then via EUR as a further pivot if needed.
        Raises ValueError if no conversion path is available.
        """
        if from_ccy == to_ccy:
            return amount

        # 1. Direct rate
        rate = self._direct_rate(from_ccy, to_ccy, as_of)
        if rate is not None:
            result = amount * rate
            logger.debug(
                "FX %s %s -> %s @ %s = %s (direct)",
                amount, from_ccy, to_ccy, as_of, result,
            )
            return result

        # 2. Chain via USD: from_ccy -> USD -> to_ccy
        rate_to_usd = self._direct_rate(from_ccy, "USD", as_of)
        rate_usd_to_target = self._direct_rate("USD", to_ccy, as_of)

        if rate_to_usd is not None and rate_usd_to_target is not None:
            result = amount * rate_to_usd * rate_usd_to_target
            logger.debug(
                "FX %s %s -> %s @ %s = %s (via USD)",
                amount, from_ccy, to_ccy, as_of, result,
            )
            return result

        # 3. Chain via EUR: from_ccy -> EUR -> to_ccy
        #    Handles ZAR->IDR: ZAR->EUR (inv EUR->ZAR), EUR->USD, USD->IDR
        rate_to_eur = self._direct_rate(from_ccy, "EUR", as_of)
        rate_eur_to_target = self._direct_rate("EUR", to_ccy, as_of)

        if rate_to_eur is not None and rate_eur_to_target is not None:
            result = amount * rate_to_eur * rate_eur_to_target
            logger.debug(
                "FX %s %s -> %s @ %s = %s (via EUR)",
                amount, from_ccy, to_ccy, as_of, result,
            )
            return result

        # 4. Three-hop: from_ccy -> EUR -> USD -> to_ccy (e.g. ZAR -> EUR -> USD -> IDR)
        if rate_to_eur is not None:
            rate_eur_usd = self._direct_rate("EUR", "USD", as_of)
            if rate_eur_usd is not None and rate_usd_to_target is not None:
                result = amount * rate_to_eur * rate_eur_usd * rate_usd_to_target
                logger.debug(
                    "FX %s %s -> %s @ %s = %s (via EUR->USD)",
                    amount, from_ccy, to_ccy, as_of, result,
                )
                return result

        raise ValueError(
            f"No FX rate path for {from_ccy} -> {to_ccy} on or before {as_of}. "
            f"Checked: direct, via USD, via EUR, via EUR->USD."
        )

    def available_pairs(self) -> list[tuple[str, str]]:
        """Return all (from, to) currency pairs in the table."""
        return sorted(self._table.keys())
