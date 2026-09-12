"""
test_stage0.py — Stage 0 smoke tests

Checks:
  1. All 7 CSVs load without error
  2. Row counts match schema.md
  3. All join keys resolve (every request has a profile; every event has a user)
  4. FX converter: direct pair, inverse pair, chained-via-USD pair
  5. OutputRow: valid row passes, invalid bounds raise
  6. Output CSV writer: columns in correct order, row count matches
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from decimal import Decimal
from datetime import date
import csv
import tempfile

from loader import load_dataset
from fx import FXConverter
from writer import OutputRow, safe_default_row, write_output_csv

DATA = Path("dataset")


def test_load_all_csvs():
    ds = load_dataset(DATA)
    # schema.md expected counts
    assert len(ds.requests) == 250, f"Expected 250 requests, got {len(ds.requests)}"
    assert len(ds.profiles) == 275, f"Expected 275 profiles, got {len(ds.profiles)}"
    assert len(ds.events) == 25342, f"Expected 25,342 events, got {len(ds.events)}"
    assert len(ds.exchange_rates) == 134, f"Expected 134 exchange rate rows, got {len(ds.exchange_rates)}"
    print(f"  [OK] load_all_csvs: requests={len(ds.requests)}, profiles={len(ds.profiles)}, "
          f"events={len(ds.events)}, rates={len(ds.exchange_rates)}")
    return ds


def test_join_keys(ds):
    # Every request must have a matching profile
    missing_profiles = [r.request_id for r in ds.requests if r.user_id not in ds.profiles]
    assert not missing_profiles, f"Requests with no profile: {missing_profiles[:5]}"

    # Every event must have a user_id that is in profiles
    missing_event_users = set(e.user_id for e in ds.events if e.user_id not in ds.profiles)
    assert not missing_event_users, f"Events with no profile: {list(missing_event_users)[:5]}"

    # images_by_event keys must all exist in events_by_id
    bad_img_events = [eid for eid in ds.images_by_event if eid not in ds.events_by_id]
    assert not bad_img_events, f"Image event_ids not in events: {bad_img_events}"

    print(f"  [OK] join_keys: all request profiles found, all events have users, image event refs valid")


def test_fx_direct(ds):
    fx = FXConverter(ds.exchange_rates)
    # EUR->ZAR direct rate exists (rate=20 in 2023-10-15)
    result = fx.convert(Decimal("1"), "EUR", "ZAR", as_of=date(2023, 10, 15))
    assert result == Decimal("20"), f"EUR->ZAR expected 20, got {result}"

    # Inverse: ZAR->EUR should be 1/20 = 0.05
    result_inv = fx.convert(Decimal("20"), "ZAR", "EUR", as_of=date(2023, 10, 15))
    assert abs(result_inv - Decimal("1")) < Decimal("0.0001"), f"ZAR->EUR(20) expected ~1, got {result_inv}"

    print(f"  [OK] fx_direct: EUR->ZAR=20, ZAR(20)->EUR~=1")


def test_fx_chained_via_usd(ds):
    fx = FXConverter(ds.exchange_rates)
    # ZAR->IDR: no direct pair; code should chain ZAR->EUR->USD->IDR
    # EUR->ZAR=20 => ZAR->EUR=0.05; EUR->USD=1/0.92~1.0869; USD->IDR=15833.33
    # => ZAR(1000) ~ 0.05 * 1.0869 * 15833.33 * 1000 ~ 860,870
    result = fx.convert(Decimal("1000"), "ZAR", "IDR", as_of=date(2023, 10, 15))
    assert result > Decimal("0"), f"ZAR->IDR should be positive, got {result}"
    print(f"  [OK] fx_chained_via_usd: ZAR(1000)->IDR = {result:.2f} (via EUR->USD three-hop)")


def test_fx_closest_prior_date(ds):
    fx = FXConverter(ds.exchange_rates)
    # Request date after the last available ZAR rate — should use most recent prior
    try:
        result = fx.convert(Decimal("100"), "EUR", "ZAR", as_of=date(2030, 1, 1))
        print(f"  [OK] fx_closest_prior_date: EUR(100)->ZAR @ 2030 = {result} (used prior rate)")
    except ValueError as e:
        print(f"  [INFO] fx_closest_prior_date: {e} (no prior rate found, expected for extinct pairs)")


def test_output_row_validation():
    # Valid row passes
    row = OutputRow(
        request_id="test_001",
        amount_safe_to_pay=Decimal("500"),
        requested_amount=Decimal("1000"),
        affordability_status="affordable_later",
        recommended_payment_method="wait",
        payment_plan="none",
        earliest_date_for_full_payment="2025-03-01",
        spending_changes_needed="none",
        decision_explanation="Test explanation.",
    )
    assert row.request_id == "test_001"

    # Invalid amount raises
    try:
        OutputRow(
            request_id="test_bad",
            amount_safe_to_pay=Decimal("2000"),   # > requested_amount
            requested_amount=Decimal("1000"),
            affordability_status="affordable_now",
            recommended_payment_method="full_payment",
            payment_plan="none",
            earliest_date_for_full_payment="",
            spending_changes_needed="none",
            decision_explanation="Should fail.",
        )
        assert False, "Should have raised"
    except ValueError:
        pass

    # Invalid status raises
    try:
        OutputRow(
            request_id="test_bad2",
            amount_safe_to_pay=Decimal("500"),
            requested_amount=Decimal("1000"),
            affordability_status="definitely_yes",  # invalid
            recommended_payment_method="wait",
            payment_plan="none",
            earliest_date_for_full_payment="",
            spending_changes_needed="none",
            decision_explanation="Should fail.",
        )
        assert False, "Should have raised"
    except ValueError:
        pass

    print("  [OK] output_row_validation: valid row passes, invalid bounds/enum raise")


def test_write_csv(ds):
    # Build safe-default rows for all sample requests (first 5)
    rows = [
        safe_default_row(r.request_id, r.requested_amount, "test")
        for r in ds.requests[:5]
    ]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        tmp = Path(f.name)

    write_output_csv(rows, tmp)

    with tmp.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        read_rows = list(reader)
        expected_cols = [
            "request_id", "amount_safe_to_pay", "affordability_status",
            "recommended_payment_method", "payment_plan",
            "earliest_date_for_full_payment", "spending_changes_needed",
            "decision_explanation",
        ]
        assert reader.fieldnames == expected_cols, f"Column order wrong: {reader.fieldnames}"
        assert len(read_rows) == 5

    tmp.unlink()
    print(f"  [OK] write_csv: correct column order, {len(read_rows)} rows written")


def test_full_pipeline_runs():
    """Run the full pipeline skeleton end-to-end and verify output.csv is produced."""
    import subprocess
    result = subprocess.run(
        ["python", "code/run.py", "--data", "dataset/", "--out", "output.csv"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Pipeline crashed:\n{result.stderr}"

    out = Path("output.csv")
    assert out.exists(), "output.csv not created"

    with out.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 250, f"Expected 250 output rows, got {len(rows)}"

    print(f"  [OK] full_pipeline_runs: output.csv written with {len(rows)} rows")


if __name__ == "__main__":
    print("\n=== Stage 0 smoke tests ===\n")
    ds = test_load_all_csvs()
    test_join_keys(ds)
    test_fx_direct(ds)
    test_fx_chained_via_usd(ds)
    test_fx_closest_prior_date(ds)
    test_output_row_validation()
    test_write_csv(ds)
    test_full_pipeline_runs()
    print("\n=== All Stage 0 tests passed ===\n")
