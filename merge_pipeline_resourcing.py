#!/usr/bin/env python3
"""Merge, filter, and explode resourcing assignments into long monthly rows."""

import argparse
import csv
from datetime import date
from pathlib import Path
import re
import shutil
import sys
import time

import pandas as pd


DATA_DIR = "data"
PIPELINE_FILE = "pipeline.csv"
RESOURCING_FILE = "resourcing.csv"
FORECAST_OUTPUT_FILE = "looker_studio_pipeline_forecast_v3.csv"
RECENT_WINDOW_SECONDS = 10 * 60

PIPELINE_COLUMN_MAP = {
    "Opportunity Name": "Opportunity Name",
    "Opportunity Owner": "Opportunity Owner",
    "Account Name": "Account Name",
    "Primary Estimate: Estimate Name": "Primary Estimate: Estimate Name",
    "Stage": "Stage",
    "Probability (%)": "Probability (%)",
    "Lead Source": "Lead Source",
    "Type": "Type",
    "Market": "Market",
    "Close Date": "Close Date",
}

RESOURCING_COLUMN_MAP = {
    "Opportunity: Opportunity Name": "Opportunity Name",
    "Resource Role": "Resource Role",
    "Start Date": "Start Date",
    "End Date": "End Date",
    "Hours": "Hours",
    "Net Bill Amount (converted)": "Net Bill Amount",
}

VERIFICATION_COLUMNS = [
    "Opportunity Name",
    "Close Date",
    "Resource Role",
    "Start Date",
]

REPORT_REQUIRED_COLUMNS = [
    "Opportunity Name",
    "Resource Role",
    "Start Date",
    "End Date",
    "Hours",
    "Net Bill Amount",
]

SPLIT_REQUIRED_FIELDS = ["Start Date", "End Date", "Hours", "Net Bill Amount"]
SPLIT_OUTPUT_FIELDS = ["Month", "Allocated Hours", "Allocated Revenue"]
LONG_FORMAT_REQUIRED_FIELDS = [
    "Opportunity Name",
    "Resource Role",
    "Start Date",
    "End Date",
    "Hours",
    "Net Bill Amount",
]
METADATA_COLUMNS = [
    "Opportunity Owner",
    "Account Name",
    "Primary Estimate: Estimate Name",
    "Stage",
    "Probability (%)",
    "Lead Source",
    "Type",
    "Market",
]
LONG_FORMAT_OUTPUT_FIELDS = [
    "Opportunity Owner",
    "Account Name",
    "Primary Estimate: Estimate Name",
    "Stage",
    "Probability (%)",
    "Lead Source",
    "Type",
    "Market",
    "Opportunity Name",
    "Resource Role",
    "Capability",
    "Role (short)",
    "Reporting Month",
    "Monthly Allocated Revenue",
    "Monthly Allocated Hours",
]


def require_columns(df: pd.DataFrame, required: list[str], label: str) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def read_csv_with_fallback(path: Path) -> pd.DataFrame:
    encodings = ["ISO-8859-1", "cp1252"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            df = pd.read_csv(path, encoding=encoding)
            print(f"Loaded {path.name} using encoding: {encoding}")
            return df
        except (UnicodeDecodeError, UnicodeError, pd.errors.ParserError) as exc:
            last_error = exc
    raise ValueError(
        f"Could not decode CSV file '{path.name}' with supported encodings: {encodings}"
    ) from last_error


def _read_csv_header_columns(path: Path) -> set[str]:
    encodings = ["ISO-8859-1", "cp1252"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            with path.open("r", encoding=encoding, newline="") as file_handle:
                reader = csv.reader(file_handle)
                header = next(reader, [])
            return {column.strip() for column in header}
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Could not read header from CSV file: {path}") from last_error


def _find_recent_csv_files(downloads_dir: Path, seconds: int) -> list[Path]:
    now = time.time()
    recent_files = []
    for file_path in downloads_dir.iterdir():
        if not file_path.is_file() or file_path.suffix.lower() != ".csv":
            continue
        file_age_seconds = now - file_path.stat().st_mtime
        if file_age_seconds <= seconds:
            recent_files.append(file_path)
    return sorted(recent_files, key=lambda path: path.stat().st_mtime, reverse=True)


def _atomic_move(source: Path, destination: Path) -> None:
    temp_destination = destination.with_name(destination.name + ".tmp")
    if temp_destination.exists():
        temp_destination.unlink()
    shutil.move(str(source), str(temp_destination))
    temp_destination.replace(destination)


def stage_recent_salesforce_exports(
    downloads_dir: Path, data_dir: Path, recent_seconds: int = RECENT_WINDOW_SECONDS
) -> tuple[Path, Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    pipeline_destination = data_dir / PIPELINE_FILE
    resourcing_destination = data_dir / RESOURCING_FILE

    recent_csvs = _find_recent_csv_files(downloads_dir, recent_seconds)

    pipeline_candidates: list[Path] = []
    resourcing_candidates: list[Path] = []

    for csv_path in recent_csvs:
        try:
            columns = _read_csv_header_columns(csv_path)
        except ValueError:
            continue

        is_pipeline = "Opportunity Owner" in columns
        is_resourcing = "Resource Role" in columns

        if is_pipeline and is_resourcing:
            raise ValueError(
                f"Ambiguous Salesforce export (matches both Pipeline and Resourcing): "
                f"{csv_path.name}"
            )
        if is_pipeline:
            pipeline_candidates.append(csv_path)
        elif is_resourcing:
            resourcing_candidates.append(csv_path)

    missing: list[str] = []
    if not pipeline_candidates:
        missing.append("Pipeline CSV (requires column 'Opportunity Owner')")
    if not resourcing_candidates:
        missing.append("Resourcing CSV (requires column 'Resource Role')")
    if missing:
        if not recent_csvs:
            raise ValueError(
                "Missing recent Salesforce export(s): "
                + ", ".join(missing)
                + f". No CSV files were modified in {downloads_dir} within the last "
                f"{recent_seconds // 60} minutes."
            )
        raise ValueError("Missing recent Salesforce export(s): " + ", ".join(missing))

    selected_pipeline = pipeline_candidates[0]
    selected_resourcing = resourcing_candidates[0]

    print(
        f"Found Pipeline file: {selected_pipeline.name} -> Moving to data/pipeline.csv"
    )
    print(
        "Found Resourcing file: "
        f"{selected_resourcing.name} -> Moving to data/resourcing.csv"
    )

    _atomic_move(selected_pipeline, pipeline_destination)
    _atomic_move(selected_resourcing, resourcing_destination)

    if not pipeline_destination.exists() or not resourcing_destination.exists():
        raise ValueError("Staging failed: destination files were not created in data/")

    print("Staging complete: data/pipeline.csv and data/resourcing.csv")
    return pipeline_destination, resourcing_destination


def ingest_files(
    base_dir: Path | None = None, recent_seconds: int = RECENT_WINDOW_SECONDS
) -> tuple[Path, Path]:
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent
    downloads_dir = resolve_downloads_dir(base_dir)
    if downloads_dir is None:
        raise ValueError("Downloads directory not found in known locations")
    data_dir = base_dir / DATA_DIR
    return stage_recent_salesforce_exports(
        downloads_dir=downloads_dir,
        data_dir=data_dir,
        recent_seconds=recent_seconds,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        action="store_true",
        help="Detect recent Salesforce exports in Downloads and stage them into data/ "
        "before processing.",
    )
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="Run staging only, then exit.",
    )
    return parser.parse_args()


def resolve_downloads_dir(base_dir: Path) -> Path | None:
    candidates = [Path.home() / "Downloads"]

    parts = base_dir.resolve().parts
    if len(parts) >= 5 and parts[1:4] == ("mnt", "c", "Users"):
        windows_user = parts[4]
        candidates.append(Path("/mnt/c/Users") / windows_user / "Downloads")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _parse_required_date(value: object, field_name: str) -> date:
    if pd.isna(value):
        raise ValueError(f"Missing required field: {field_name}")

    text_value = str(value).strip()
    parsed = pd.NaT
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text_value):
        parsed = pd.to_datetime(text_value, format="%Y-%m-%d", errors="coerce")
    elif re.fullmatch(r"\d{2}/\d{2}/\d{4}", text_value):
        parsed = pd.to_datetime(text_value, format="%d/%m/%Y", errors="coerce")
    else:
        parsed = pd.to_datetime(text_value, errors="coerce", dayfirst=True)

    if pd.isna(parsed):
        raise ValueError(f"Invalid date for {field_name}: {value}")
    return parsed.date()


def _parse_required_float(value: object, field_name: str) -> float:
    if pd.isna(value):
        raise ValueError(f"Missing required field: {field_name}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for {field_name}: {value}") from exc


def extract_capability(role_str: object) -> str:
    role_text = str(role_str).strip()
    capability = role_text.split(" - ", 1)[0]
    return capability.strip()


def extract_short_role(role_str: object) -> str:
    role_text = str(role_str).strip()
    short_role = role_text.rsplit(" - ", 1)[-1]
    return short_role.strip()


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def explode_to_monthly_rows(row: dict | pd.Series) -> list[dict]:
    for field in LONG_FORMAT_REQUIRED_FIELDS:
        if field not in row:
            raise ValueError(f"Missing required field: {field}")
    for field in METADATA_COLUMNS:
        if field not in row:
            raise ValueError(f"Missing required field: {field}")

    opportunity_name = str(row["Opportunity Name"])
    resource_role = str(row["Resource Role"])
    if "Capability" in row and not pd.isna(row["Capability"]):
        capability = str(row["Capability"]).strip()
    else:
        capability = extract_capability(resource_role)
    if "Role (short)" in row and not pd.isna(row["Role (short)"]):
        role_short = str(row["Role (short)"]).strip()
    else:
        role_short = extract_short_role(resource_role)
    metadata_values = {column: row[column] for column in METADATA_COLUMNS}
    start_date = _parse_required_date(row["Start Date"], "Start Date")
    end_date = _parse_required_date(row["End Date"], "End Date")
    total_hours = _parse_required_float(row["Hours"], "Hours")
    total_revenue = _parse_required_float(row["Net Bill Amount"], "Net Bill Amount")

    if end_date < start_date:
        raise ValueError("End Date must be on or after Start Date")

    month_starts: list[date] = []
    current_month_start = _month_start(start_date)
    last_month_start = _month_start(end_date)
    while current_month_start <= last_month_start:
        month_starts.append(current_month_start)
        current_month_start = _next_month(current_month_start)

    month_count = len(month_starts)
    if month_count == 0:
        raise ValueError("No months found in assignment date range")

    rows: list[dict] = []
    running_hours = 0.0
    running_revenue = 0.0

    for index, month_start in enumerate(month_starts):
        is_last = index == month_count - 1
        if is_last:
            allocated_hours = round(total_hours - running_hours, 2)
            allocated_revenue = round(total_revenue - running_revenue, 2)
        else:
            allocated_hours = round(total_hours / month_count, 2)
            allocated_revenue = round(total_revenue / month_count, 2)
            running_hours += allocated_hours
            running_revenue += allocated_revenue

        rows.append(
            {
                **metadata_values,
                "Opportunity Name": opportunity_name,
                "Resource Role": resource_role,
                "Capability": capability,
                "Role (short)": role_short,
                "Reporting Month": month_start.strftime("%Y-%m-01"),
                "Monthly Allocated Revenue": allocated_revenue,
                "Monthly Allocated Hours": allocated_hours,
            }
        )

    return rows


def main(stage_files: bool = False, stage_only: bool = False) -> int:
    base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / DATA_DIR
    downloads_dir = resolve_downloads_dir(base_dir)
    pipeline_path = data_dir / PIPELINE_FILE
    resourcing_path = data_dir / RESOURCING_FILE
    forecast_output_path = base_dir / FORECAST_OUTPUT_FILE

    try:
        if stage_files or stage_only:
            if downloads_dir is None:
                raise ValueError("Downloads directory not found in known locations")
            stage_recent_salesforce_exports(downloads_dir, data_dir)
            if stage_only:
                return 0

        if not pipeline_path.exists():
            raise ValueError(
                f"file not found: {pipeline_path} (run with --stage to auto-stage from Downloads)"
            )
        if not resourcing_path.exists():
            raise ValueError(
                f"file not found: {resourcing_path} (run with --stage to auto-stage from Downloads)"
            )

        pipeline_df = read_csv_with_fallback(pipeline_path)
        resourcing_df = read_csv_with_fallback(resourcing_path)

        special_mask = (
            pipeline_df.get("Opportunity Owner", pd.Series(dtype=str))
            .astype(str)
            .str.contains(r"Aurélie|Boursorama", case=False, na=False)
            | pipeline_df.get("Account Name", pd.Series(dtype=str))
            .astype(str)
            .str.contains(r"Aurélie|Boursorama", case=False, na=False)
            | pipeline_df.get("Opportunity Name", pd.Series(dtype=str))
            .astype(str)
            .str.contains(r"Aurélie|Boursorama", case=False, na=False)
        )
        special_rows = pipeline_df.loc[
            special_mask,
            [col for col in ["Opportunity Owner", "Account Name", "Opportunity Name"] if col in pipeline_df.columns],
        ]
        if not special_rows.empty:
            print("Special character verification sample from pipeline.csv:")
            print(special_rows.head(1).to_string(index=False))
        else:
            print("Special character verification sample not found (Aurélie/Boursorama).")

        require_columns(
            pipeline_df,
            list(PIPELINE_COLUMN_MAP.keys()),
            "Pipeline file",
        )
        require_columns(
            resourcing_df,
            list(RESOURCING_COLUMN_MAP.keys()),
            "Resourcing file",
        )

        pipeline_subset = (
            pipeline_df[list(PIPELINE_COLUMN_MAP.keys())]
            .rename(columns=PIPELINE_COLUMN_MAP)
            .copy()
        )
        resourcing_working = resourcing_df.rename(columns=RESOURCING_COLUMN_MAP).copy()

        pipeline_unique_count = pipeline_subset["Opportunity Name"].nunique(dropna=True)
        resourcing_unique_count = resourcing_working["Opportunity Name"].nunique(
            dropna=True
        )

        merged_df = resourcing_working.merge(
            pipeline_subset,
            on="Opportunity Name",
            how="inner",
        )
        merged_df["Capability"] = merged_df["Resource Role"].apply(extract_capability)
        merged_df["Role (short)"] = merged_df["Resource Role"].apply(extract_short_role)
        merged_unique_count = merged_df["Opportunity Name"].nunique(dropna=True)

        print(f"Pipeline unique Opportunity Names: {pipeline_unique_count}")
        print(f"Resourcing unique Opportunity Names: {resourcing_unique_count}")
        print(f"Merged unique Opportunity Names: {merged_unique_count}")

        if merged_unique_count > pipeline_unique_count:
            raise ValueError(
                "Ghost data detected: merged Opportunity Name unique count exceeds "
                "pipeline unique count"
            )

        print("Merged columns:")
        print(merged_df.columns.tolist())
        print("Merged sample (Opportunity Name, Opportunity Owner, Market):")
        print(
            merged_df[["Opportunity Name", "Opportunity Owner", "Market"]]
            .head(3)
            .to_string(index=False)
        )

        require_columns(merged_df, VERIFICATION_COLUMNS, "Merged data")
        require_columns(merged_df, REPORT_REQUIRED_COLUMNS, "Merged data")

        verification_df = merged_df[VERIFICATION_COLUMNS]
        print(verification_df.head(5).to_string(index=False))

        expanded_rows: list[dict] = []
        for _, row in merged_df.iterrows():
            expanded_rows.extend(explode_to_monthly_rows(row))

        if not expanded_rows:
            raise ValueError("No monthly allocations generated from merged data")

        monthly_df = pd.DataFrame(expanded_rows)
        require_columns(monthly_df, LONG_FORMAT_OUTPUT_FIELDS, "Monthly data")
        monthly_df["Reporting Month"] = pd.to_datetime(
            monthly_df["Reporting Month"], format="%Y-%m-%d", errors="coerce"
        )
        if monthly_df["Reporting Month"].isna().any():
            raise ValueError("Invalid Reporting Month values detected in monthly data")
        monthly_df = monthly_df.sort_values(
            ["Opportunity Name", "Resource Role", "Reporting Month"]
        )
        capability_values = sorted(
            value
            for value in merged_df["Capability"].dropna().astype(str).str.strip().unique()
            if value
        )
        print(f"Unique Capabilities found: {capability_values[:5]}")
        role_short_values = sorted(
            value
            for value in merged_df["Role (short)"].dropna().astype(str).str.strip().unique()
            if value
        )
        print(f"Unique Role (short) found: {role_short_values[:5]}")
        print(monthly_df.head(20).to_string(index=False))
        monthly_df["Reporting Month"] = monthly_df["Reporting Month"].dt.strftime(
            "%Y-%m-%d"
        )
        monthly_df = monthly_df[LONG_FORMAT_OUTPUT_FIELDS]
        monthly_df.to_csv(forecast_output_path, index=False, encoding="utf-8-sig")
        print(
            f"Saved long-format monthly forecast (utf-8-sig): {forecast_output_path}"
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    split_test_row = {
        "Opportunity Owner": "Test Owner",
        "Account Name": "Test Account",
        "Primary Estimate: Estimate Name": "Test Estimate",
        "Stage": "Open",
        "Probability (%)": 50,
        "Lead Source": "Inbound",
        "Type": "New Business",
        "Market": "UK - Market",
        "Opportunity Name": "Test Opportunity",
        "Resource Role": "Client Management - Director",
        "Start Date": "2025-01-01",
        "End Date": "2025-03-01",
        "Hours": 300,
        "Net Bill Amount": 3000,
    }
    split_result = explode_to_monthly_rows(split_test_row)
    for item in split_result:
        print(item)
    if len(split_result) != 3:
        raise ValueError(f"Expected 3 rows in split test, got {len(split_result)}")
    expected_months = ["2025-01-01", "2025-02-01", "2025-03-01"]
    actual_months = [row["Reporting Month"] for row in split_result]
    if actual_months != expected_months:
        raise ValueError(f"Unexpected reporting months: {actual_months}")
    if any(row["Capability"] != "Client Management" for row in split_result):
        raise ValueError(
            "Expected Capability to be 'Client Management' for role "
            "'Client Management - Director'"
        )
    if any(row["Monthly Allocated Revenue"] != 1000.0 for row in split_result):
        raise ValueError("Expected each monthly allocated revenue to equal 1000.0")
    if any(row["Market"] != "UK - Market" for row in split_result):
        raise ValueError("Expected Market to be preserved as 'UK - Market' in all rows")
    if extract_capability("Designer") != "Designer":
        raise ValueError("Expected Capability to preserve role when no delimiter exists")
    if extract_short_role("CX - CRM - Senior Manager") != "Senior Manager":
        raise ValueError(
            "Expected Role (short) to preserve only the final segment after hyphen splits"
        )
    print("Split test passed: 3 monthly rows with 1000.0 revenue each.")

    cli_args = parse_args()
    raise SystemExit(main(stage_files=cli_args.stage, stage_only=cli_args.stage_only))
