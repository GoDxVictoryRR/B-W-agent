"""
run.py — Single pipeline entrypoint (harness.md)

Usage:
    python run.py --data dataset/ --out output.csv

Stages wired in order (architecture-design.md):
    Stage 0: load_and_join     [DONE]
    Stage 1: forecast_and_rank [TODO]
    Stage 2: plan types        [TODO]
    Stage 3: evidence/messages [TODO]
    Stage 4: explanations      [TODO]
    Stage 5: usage report      [TODO]
"""

from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging — always before any other import that uses logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run")

# ---------------------------------------------------------------------------
# Project imports (all in code/)
# ---------------------------------------------------------------------------
from loader import load_dataset
from writer import OutputRow, safe_default_row, write_output_csv


# ---------------------------------------------------------------------------
# Pipeline stubs — will be replaced stage by stage
# ---------------------------------------------------------------------------

def process_request(request, dataset, fx_converter) -> OutputRow:
    """
    Stub: returns safe-default for every request.
    Replace in Stage 1 with the real forecast + plan logic.
    """
    return safe_default_row(
        request_id=request.request_id,
        requested_amount=request.requested_amount,
        reason="Pipeline not yet implemented (Stage 0 skeleton)",
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(data_dir: Path, out_path: Path) -> None:
    logger.info("=== Buy or Wait pipeline starting ===")
    logger.info("data_dir=%s  out_path=%s", data_dir, out_path)

    # Stage 0 — Load & Join
    dataset = load_dataset(data_dir)
    logger.info("Stage 0 complete: dataset loaded")

    # Stage 0 — FX converter
    from fx import FXConverter
    fx = FXConverter(dataset.exchange_rates)
    logger.info("FX converter ready with %d pairs", len(fx.available_pairs()))

    # Stages 1-4 — process each request (stub for now)
    output_rows: list[OutputRow] = []
    errors = 0
    for req in dataset.requests:
        try:
            row = process_request(req, dataset, fx)
        except Exception as exc:
            logger.exception("Unhandled error for %s: %s", req.request_id, exc)
            row = safe_default_row(
                request_id=req.request_id,
                requested_amount=req.requested_amount,
                reason=str(exc),
            )
            errors += 1
        output_rows.append(row)

    logger.info(
        "Processed %d requests (%d errors, %d safe-defaults)",
        len(output_rows), errors, errors,
    )

    # Stage 0 — Write output
    write_output_csv(output_rows, out_path)
    logger.info("=== Pipeline complete ===")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Buy or Wait pipeline")
    parser.add_argument("--data", default="dataset/", help="Path to dataset/ directory")
    parser.add_argument("--out", default="output.csv", help="Path for output.csv")
    args = parser.parse_args()

    run_pipeline(Path(args.data), Path(args.out))


if __name__ == "__main__":
    main()
