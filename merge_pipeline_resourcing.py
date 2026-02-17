#!/usr/bin/env python3
"""Merge, filter, and explode resourcing assignments into long monthly rows."""

from datetime import date
from pathlib import Path
import re
import sys

import pandas as pd


PIPELINE_FILE = "pipeline.csv"
RESOURCING_FILE = "resourcing.csv"
FORECAST_OUTPUT_FILE = "looker_studio_pipeline_forecast_v3.csv"

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
                "Reporting Month": month_start.strftime("%Y-%m-01"),
                "Monthly Allocated Revenue": allocated_revenue,
                "Monthly Allocated Hours": allocated_hours,
            }
        )

    return rows


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    pipeline_path = base_dir / PIPELINE_FILE
    resourcing_path = base_dir / RESOURCING_FILE
    forecast_output_path = base_dir / FORECAST_OUTPUT_FILE

    if not pipeline_path.exists():
        print(f"Error: file not found: {pipeline_path}", file=sys.stderr)
        return 1
    if not resourcing_path.exists():
        print(f"Error: file not found: {resourcing_path}", file=sys.stderr)
        return 1

    try:
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
        print(monthly_df.head(20).to_string(index=False))
        monthly_df["Reporting Month"] = monthly_df["Reporting Month"].dt.strftime(
            "%Y-%m-%d"
        )
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
        "Resource Role": "Test Role",
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
    if any(row["Monthly Allocated Revenue"] != 1000.0 for row in split_result):
        raise ValueError("Expected each monthly allocated revenue to equal 1000.0")
    if any(row["Market"] != "UK - Market" for row in split_result):
        raise ValueError("Expected Market to be preserved as 'UK - Market' in all rows")
    print("Split test passed: 3 monthly rows with 1000.0 revenue each.")

    raise SystemExit(main())
