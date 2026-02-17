#!/usr/bin/env python3
"""Upload forecast CSV data into a Google Sheet tab using gspread."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import pandas as pd


DEFAULT_CSV_PATH = "looker_studio_pipeline_forecast_v3.csv"
DEFAULT_TAB_NAME = "Latest Data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload the local forecast CSV to a Google Sheet tab, replacing existing data."
        )
    )
    parser.add_argument(
        "--csv-path",
        default=DEFAULT_CSV_PATH,
        help=f"Path to source CSV (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--sheet-url",
        default=None,
        help="Google Sheet URL (falls back to GOOGLE_SHEET_URL from .env/environment)",
    )
    parser.add_argument(
        "--tab-name",
        default=None,
        help=(
            f"Worksheet/tab name (falls back to GOOGLE_SHEET_TAB, default: {DEFAULT_TAB_NAME})"
        ),
    )
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> tuple[Path, str, str, Path]:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ModuleNotFoundError:
        # .env loading is optional; environment variables can still be provided directly.
        pass

    csv_path = Path(args.csv_path)
    sheet_url = args.sheet_url or os.getenv("GOOGLE_SHEET_URL")
    tab_name = args.tab_name or os.getenv("GOOGLE_SHEET_TAB", DEFAULT_TAB_NAME)
    service_account_path_raw = os.getenv("SERVICE_ACCOUNT_JSON_PATH")

    if not csv_path.exists():
        raise ValueError(f"CSV file not found: {csv_path}")
    if not sheet_url:
        raise ValueError("Missing Google Sheet URL. Set GOOGLE_SHEET_URL or use --sheet-url.")
    if not service_account_path_raw:
        raise ValueError(
            "Missing SERVICE_ACCOUNT_JSON_PATH in environment/.env."
        )

    service_account_path = Path(service_account_path_raw).expanduser()
    if not service_account_path.exists():
        raise ValueError(
            f"Service account JSON file not found: {service_account_path}"
        )
    if not service_account_path.is_file():
        raise ValueError(
            f"Service account path is not a file: {service_account_path}"
        )

    return csv_path, sheet_url, tab_name, service_account_path


def dataframe_to_values(df: pd.DataFrame) -> list[list[object]]:
    headers = df.columns.tolist()
    if not headers:
        return []
    values: list[list[object]] = [headers]
    values.extend(df.fillna("").astype(object).values.tolist())
    return values


def upload_csv_to_sheet(
    csv_path: Path, sheet_url: str, tab_name: str, service_account_path: Path
) -> tuple[str, int]:
    try:
        import gspread
        from gspread.exceptions import WorksheetNotFound
    except ModuleNotFoundError as exc:
        raise ValueError(
            "Missing required dependency 'gspread'. Install with: pip install gspread"
        ) from exc

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    row_count = len(df)

    client = gspread.service_account(filename=str(service_account_path))
    sheet = client.open_by_url(sheet_url)

    try:
        worksheet = sheet.worksheet(tab_name)
    except WorksheetNotFound as exc:
        raise ValueError(f"Worksheet tab not found: {tab_name}") from exc

    worksheet.clear()

    values = dataframe_to_values(df)
    if values:
        worksheet.update("A1", values, value_input_option="RAW")

    return sheet.title, row_count


def main() -> int:
    args = parse_args()
    try:
        csv_path, sheet_url, tab_name, service_account_path = load_config(args)
        sheet_name, row_count = upload_csv_to_sheet(
            csv_path=csv_path,
            sheet_url=sheet_url,
            tab_name=tab_name,
            service_account_path=service_account_path,
        )
        print(
            f"Successfully updated Google Sheet: {sheet_name} - {row_count} rows uploaded."
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
