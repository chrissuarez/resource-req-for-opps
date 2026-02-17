#!/usr/bin/env python3
"""Master entry point: ingest exports, process data, and upload to Google Sheets."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
import sys

import merge_pipeline_resourcing as pipeline_processing
import upload_to_google_sheets as sheets_upload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the full pipeline: stage recent Salesforce exports, process forecast, "
            "and upload to Google Sheets."
        )
    )
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="Run ingest_files() only, then exit.",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Run ingest_files() + process_data(), but skip Google Sheets upload.",
    )
    return parser.parse_args()


def ingest_files(base_dir: Path) -> tuple[Path, Path]:
    print("Stage 1/3: ingest_files()")
    pipeline_path, resourcing_path = pipeline_processing.ingest_files(base_dir=base_dir)
    print(f"Ingest complete: {pipeline_path} and {resourcing_path}")
    return pipeline_path, resourcing_path


def process_data(base_dir: Path) -> Path:
    print("Stage 2/3: process_data()")
    exit_code = pipeline_processing.main(stage_files=False, stage_only=False)
    if exit_code != 0:
        raise ValueError("process_data() failed")
    output_csv = base_dir / pipeline_processing.FORECAST_OUTPUT_FILE
    if not output_csv.exists():
        raise ValueError(f"Expected output file not found: {output_csv}")
    print(f"Process complete: {output_csv}")
    return output_csv


def upload_to_sheets(output_csv: Path) -> tuple[str, int]:
    print("Stage 3/3: upload_to_sheets()")
    args = SimpleNamespace(csv_path=str(output_csv), sheet_url=None, tab_name=None)
    csv_path, sheet_url, tab_name, service_account_path = sheets_upload.load_config(args)
    sheet_name, row_count = sheets_upload.upload_csv_to_sheet(
        csv_path=csv_path,
        sheet_url=sheet_url,
        tab_name=tab_name,
        service_account_path=service_account_path,
    )
    print(
        f"Successfully updated Google Sheet: {sheet_name} - {row_count} rows uploaded."
    )
    return sheet_name, row_count


def main() -> int:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    try:
        ingest_files(base_dir)
        if args.stage_only:
            return 0

        output_csv = process_data(base_dir)
        if args.skip_upload:
            print("Upload skipped (--skip-upload).")
            return 0

        upload_to_sheets(output_csv)
        print(
            "Pipeline completed. Verify Looker Studio reflects new rows after refresh."
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
