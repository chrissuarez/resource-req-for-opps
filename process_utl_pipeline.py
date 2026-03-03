import shutil
from pathlib import Path
import pandas as pd

UTL_IDENTIFIER_HEADERS = {"PracticeName02", "Sum of ValueUtilizationTargetHours"}
UTL_BASE_REQUIRED_HEADERS = UTL_IDENTIFIER_HEADERS | {
    "ResourceName",
    "Sum of ValueCreditedHours",
    "Sum of ValueExcludedHours",
    "Sum of ValueCalendarHours",
}
UTL_BILLABLE_COLUMN_CANDIDATES = ["ValueBillableHours", "Sum of ValueBillableHours"]
TIME_IDENTIFIER_HEADERS = {"ResourcePracticeName02", "ProjectType"}
TIME_REQUIRED_HEADERS = TIME_IDENTIFIER_HEADERS | {"Sum of ValueTotalHours"}
PRESCRIBED_HOURS_PER_PERSON = 11.0
FORECAST_FILE = "looker_studio_pipeline_forecast_v3.csv"
FORECAST_REQUIRED_COLUMNS = {
    "Pricing Region: Region Name",
    "Capability",
    "Stage",
    "Reporting Month (Date)",
    "Monthly Allocated Hours",
}
UK_REGION_NAME = "United Kingdom"
INPUT_DIR = Path("data/input")
OUTPUT_DIR = Path("data/output")
CANONICAL_UTL = INPUT_DIR / "utl_by_capability.csv"
CANONICAL_TIME = INPUT_DIR / "time_type.csv"
OUTPUT_FILE = OUTPUT_DIR / "utl_pipeline_output.csv"
PRACTICE_TO_PARENT = {
    "Media Strategy": "AI, Planning & Insights (H)",
    "Market Intelligence": "AI, Planning & Insights (H)",
    "Creative Strategy": "AI, Planning & Insights (H)",
    "Brand Strategy": "Brand Strategy (H)",
    "Client Management": "Client Management (H)",
    "Commerce": "Commerce (H)",
    "Language Services": "Creative & Experience (H)",
    "Content": "Creative & Experience (H)",
    "Production": "Creative & Experience (H)",
    "Creative": "Creative & Experience (H)",
    "Creative Collective": "Creative & Experience (H)",
    "AI Studios": "Creative & Experience (H)",
    "Creative Ideation": "Creative & Experience (H)",
    "Social Creative": "Creative & Experience (H)",
    "Design & Production": "Creative & Experience (H)",
    "Integrated Production": "Creative & Experience (H)",
    "GenAI Transformation": "Creative & Experience (H)",
    "SEO": "Earned Media (H)",
    "Public Relations": "Earned Media (H)",
    "ASO": "Earned Media (H)",
    "Engineering": "Engineering (H)",
    "Cloud Engineering": "Engineering (H)",
    "Growth": "Growth (H)",
    "Connect - Operations": "Jellyfish Connect (H)",
    "Connect - Engineering": "Jellyfish Connect (H)",
    "Connect - Client Management": "Jellyfish Connect (H)",
    "Connect - Marketing": "Jellyfish Connect (H)",
    "CX": "Martech (H)",
    "Cloud": "Martech (H)",
    "CX - Web Development": "Martech (H)",
    "Analytics": "Martech (H)",
    "CX - Experience Optimization": "Martech (H)",
    "CX - CRM": "Martech (H)",
    "Martech Operations": "Martech (H)",
    "CX - Experience Design": "Martech (H)",
    "Paid Media Operations": "Paid Media (H)",
    "Retail Media": "Paid Media (H)",
    "Paid Social": "Paid Media (H)",
    "Paid Search": "Paid Media (H)",
    "Programmatic": "Paid Media (H)",
    "Paid Media": "Paid Media (H)",
    "Investment Analytics": "Paid Media (H)",
    "Direct Investment": "Paid Media (H)",
    "Paid Media Activation": "Paid Media (H)",
    "Media Standards and Process": "Paid Media (H)",
    "AdTech Solutions": "Partnerships (H)",
    "Partnerships - Growth": "Partnerships (H)",
    "Account Management": "Partnerships (H)",
    "Partnerships": "Partnerships (H)",
    "Project Management": "Project Management (H)",
    "Training": "Training (H)",
}


def _normalised_headers(path: Path):
    return [str(col).strip() for col in pd.read_csv(path, nrows=0).columns]


def _has_headers(headers, required_headers):
    return required_headers.issubset(set(headers))


def _contains_any_header(headers, candidate_headers):
    header_set = set(headers)
    return any(header in header_set for header in candidate_headers)


def _select_existing_column(columns, candidate_columns, label):
    for column in candidate_columns:
        if column in columns:
            return column
    raise ValueError(
        f"{label} is missing any of the expected columns: {candidate_columns}. "
        "Please export the correct source file and rerun."
    )


def stage_files():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(
        INPUT_DIR.glob("*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    selected_utl: Path | None = None
    selected_time: Path | None = None

    for filepath in csv_files:
        try:
            headers = _normalised_headers(filepath)
        except Exception as e:
            print(f"Warning skipping {filepath.name}: {repr(e)}")
            continue

        is_utl = _has_headers(headers, UTL_BASE_REQUIRED_HEADERS) and _contains_any_header(
            headers, UTL_BILLABLE_COLUMN_CANDIDATES
        )
        is_time = _has_headers(headers, TIME_REQUIRED_HEADERS)

        if selected_utl is None and is_utl:
            selected_utl = filepath
            print(f"Selected UTL source: {filepath.name}")

        if selected_time is None and is_time:
            selected_time = filepath
            print(f"Selected Time source: {filepath.name}")

        if selected_utl is not None and selected_time is not None:
            break

    if selected_utl is None:
        raise ValueError(
            f"Missing required UTL source in {INPUT_DIR}. "
            "Add a CSV containing the expected UTL columns."
        )
    if selected_time is None:
        raise ValueError(
            f"Missing required Time source in {INPUT_DIR}. "
            "Add a CSV containing the expected Time Type columns."
        )

    if selected_utl.resolve() != CANONICAL_UTL.resolve():
        shutil.copy2(selected_utl, CANONICAL_UTL)
    if selected_time.resolve() != CANONICAL_TIME.resolve():
        shutil.copy2(selected_time, CANONICAL_TIME)
    print(f"Canonical UTL file updated: {CANONICAL_UTL}")
    print(f"Canonical Time file updated: {CANONICAL_TIME}")


def _ensure_required_columns(df: pd.DataFrame, required_columns, label: str):
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            f"{label} is missing required columns: {missing_columns}. "
            "Please export the correct source file and rerun."
        )


def format_percentage(value):
    if pd.isna(value):
        return "0%"
    return f"{value * 100:.0f}%"


def _first_day_of_month(value: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(year=value.year, month=value.month, day=1)


def _next_n_full_month_starts(today: pd.Timestamp, n: int = 3) -> list[pd.Timestamp]:
    current_month_start = _first_day_of_month(today)
    return [current_month_start + pd.DateOffset(months=offset) for offset in range(1, n + 1)]
	
def process_data():
    utl_path = CANONICAL_UTL
    time_path = CANONICAL_TIME
    forecast_path = Path(FORECAST_FILE)
    output_path = OUTPUT_FILE

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    if not utl_path.exists() or not time_path.exists() or not forecast_path.exists():
        print(
            f"Error: Required files not found. Make sure {utl_path}, {time_path}, and "
            f"{forecast_path} exist."
        )
        return
        
    print("Reading data files...")
    df_utl = pd.read_csv(utl_path)
    df_time = pd.read_csv(time_path)
    df_forecast = pd.read_csv(forecast_path)
    _ensure_required_columns(df_utl, UTL_BASE_REQUIRED_HEADERS, "Utl Data file")
    _ensure_required_columns(df_time, TIME_REQUIRED_HEADERS, "Time Data file")
    _ensure_required_columns(df_forecast, FORECAST_REQUIRED_COLUMNS, "Forecast file")
    billable_column = _select_existing_column(
        df_utl.columns,
        UTL_BILLABLE_COLUMN_CANDIDATES,
        "Utl Data file billable source",
    )
    
    print("Processing data...")
    # Group utilization data by capability, rolling billable hours up first.
    df_utl["_billable_hours"] = pd.to_numeric(df_utl[billable_column], errors="coerce").fillna(0)
    df_utl["_calendar_hours"] = pd.to_numeric(df_utl["Sum of ValueCalendarHours"], errors="coerce").fillna(0)
    df_utl["_credited_hours"] = pd.to_numeric(df_utl["Sum of ValueCreditedHours"], errors="coerce").fillna(0)
    df_utl["_excluded_hours"] = pd.to_numeric(df_utl["Sum of ValueExcludedHours"], errors="coerce").fillna(0)
    utl_grouped = (
        df_utl.groupby("PracticeName02")
        .agg(
            {
                "_billable_hours": "sum",
                "_calendar_hours": "sum",
                "_credited_hours": "sum",
                "_excluded_hours": "sum",
                "ResourceName": "nunique",
            }
        )
        .reset_index()
        .rename(
            columns={
                "_billable_hours": "BillableHours",
                "_calendar_hours": "CalendarHours",
                "_credited_hours": "CreditedHours",
                "_excluded_hours": "ExcludedHours",
                "ResourceName": "PeopleCount",
            }
        )
    )
    
    # Process Time data
    valid_project_types = ["Client Admin", "Client Growth", "Net New Business"]
    df_time = df_time.copy()
    df_time["Sum of ValueTotalHours"] = pd.to_numeric(
        df_time["Sum of ValueTotalHours"], errors="coerce"
    ).fillna(0)
    project_type_normalised = df_time["ProjectType"].astype(str).str.strip()
    df_time_filtered = df_time[project_type_normalised.isin(valid_project_types)]
    
    if not df_time_filtered.empty:
        time_grouped = df_time_filtered.groupby("ResourcePracticeName02").agg({
            "Sum of ValueTotalHours": "sum"
        }).reset_index()
        time_grouped.rename(
            columns={
                "ResourcePracticeName02": "PracticeName02",
                "Sum of ValueTotalHours": "Sum of New Business Hours",
            },
            inplace=True,
        )
    else:
        # Create an empty dataframe with expected columns if no data matches
        time_grouped = pd.DataFrame(columns=["PracticeName02", "Sum of New Business Hours"])

    # Process forecast data for UK pipeline (next 3 full months)
    df_forecast = df_forecast.copy()
    df_forecast["Pricing Region: Region Name"] = (
        df_forecast["Pricing Region: Region Name"].astype(str).str.strip()
    )
    df_forecast["Capability"] = df_forecast["Capability"].astype(str).str.strip()
    df_forecast["Stage"] = df_forecast["Stage"].astype(str).str.strip()
    df_forecast["Reporting Month (Date)"] = pd.to_datetime(
        df_forecast["Reporting Month (Date)"], errors="coerce"
    )
    df_forecast["Monthly Allocated Hours"] = pd.to_numeric(
        df_forecast["Monthly Allocated Hours"], errors="coerce"
    ).fillna(0)
    month_starts = _next_n_full_month_starts(pd.Timestamp.now(), n=3)
    month_start_set = {_first_day_of_month(month_start) for month_start in month_starts}
    forecast_months = df_forecast["Reporting Month (Date)"].dt.to_period("M").dt.to_timestamp()
    forecast_filtered = df_forecast[
        (df_forecast["Pricing Region: Region Name"] == UK_REGION_NAME)
        & (df_forecast["Stage"].str.casefold() == "closed won")
        & forecast_months.isin(month_start_set)
    ]
    if not forecast_filtered.empty:
        forecast_grouped = forecast_filtered.groupby("Capability").agg(
            {"Monthly Allocated Hours": "sum"}
        ).reset_index()
        forecast_grouped["PipelineAvgHours"] = forecast_grouped["Monthly Allocated Hours"] / 3.0
        forecast_grouped = forecast_grouped[["Capability", "PipelineAvgHours"]]
    else:
        forecast_grouped = pd.DataFrame(columns=["Capability", "PipelineAvgHours"])

    # Merge Data
    merged_df = pd.merge(utl_grouped, time_grouped, on="PracticeName02", how="left")
    merged_df["Sum of New Business Hours"] = merged_df["Sum of New Business Hours"].fillna(0)
    merged_df = pd.merge(
        merged_df,
        forecast_grouped,
        left_on="PracticeName02",
        right_on="Capability",
        how="left",
    )
    merged_df["PipelineAvgHours"] = merged_df["PipelineAvgHours"].fillna(0)
    
    # Calculate percentages safely (division-by-zero -> 0)
    calendar_hours = merged_df["CalendarHours"]
    safe_calendar = calendar_hours.where(calendar_hours != 0, pd.NA)
    billability_ratio = (merged_df["BillableHours"] / safe_calendar).fillna(0)
    new_business_ratio = (merged_df["Sum of New Business Hours"] / safe_calendar).fillna(0)
    annual_leave_ratio = (merged_df["ExcludedHours"] / safe_calendar).fillna(0)
    base_prescribed_hours = merged_df["PeopleCount"] * PRESCRIBED_HOURS_PER_PERSON
    available_non_newbiz_hours = (merged_df["CreditedHours"] - merged_df["Sum of New Business Hours"]).clip(lower=0)
    prescribed_hours = available_non_newbiz_hours.where(
        available_non_newbiz_hours <= base_prescribed_hours,
        base_prescribed_hours,
    )
    misc_hours = (available_non_newbiz_hours - prescribed_hours).clip(lower=0)
    zero_credited_mask = merged_df["CreditedHours"] <= 0
    prescribed_hours = prescribed_hours.mask(zero_credited_mask, 0)
    misc_hours = misc_hours.mask(zero_credited_mask, 0)
    prescribed_ratio = (prescribed_hours / safe_calendar).fillna(0)
    misc_ratio = (misc_hours / safe_calendar).fillna(0)
    pipeline_ratio = (merged_df["PipelineAvgHours"] / safe_calendar).fillna(0)
    billability_pct_points = (billability_ratio * 100).round().astype(int)
    new_business_pct_points = (new_business_ratio * 100).round().astype(int)
    prescribed_pct_points = (prescribed_ratio * 100).round().astype(int)
    misc_pct_points = (misc_ratio * 100).round().astype(int)
    annual_leave_pct_points = (annual_leave_ratio * 100).round().astype(int)
    pipeline_pct_points = (pipeline_ratio * 100).round().astype(int)
    current_utl_pct_points = (
        billability_pct_points
        + new_business_pct_points
        + prescribed_pct_points
        + misc_pct_points
        + annual_leave_pct_points
    )
    est_ult_pct_points = current_utl_pct_points + pipeline_pct_points

    # Build output dataframe
    output_df = pd.DataFrame()
    capability_series = merged_df["PracticeName02"].astype(str).str.strip()
    output_df["Parent capability"] = capability_series.map(PRACTICE_TO_PARENT).fillna("")
    output_df["Capability"] = capability_series
    
    output_df["Billability %"] = billability_pct_points.astype(str) + "%"
    output_df["Billable hours"] = merged_df["BillableHours"]
    output_df["New Business %"] = new_business_pct_points.astype(str) + "%"
    output_df["New Biz hours"] = merged_df["Sum of New Business Hours"]
    
    output_df["Prescribed Int."] = prescribed_pct_points.astype(str) + "%"
    output_df["Prescribed hours"] = prescribed_hours
    output_df["Misc Int."] = misc_pct_points.astype(str) + "%"
    output_df["Misc hours"] = misc_hours
    output_df["Annual Leave %"] = annual_leave_pct_points.astype(str) + "%"
    output_df["Annual leave hours"] = merged_df["ExcludedHours"]
    output_df["Total Calendar hours"] = merged_df["CalendarHours"]
    output_df["Current Utl %"] = current_utl_pct_points.astype(str) + "%"
    output_df["Pipeline %"] = pipeline_pct_points.astype(str) + "%"
    output_df["Pipeline hours"] = merged_df["PipelineAvgHours"].round(0).astype(int)
    output_df["Est. Ult"] = est_ult_pct_points.astype(str) + "%"
    
    print(f"Saving output to {output_path}...")
    output_df.to_csv(output_path, index=False)
    print("Done!")


def main() -> int:
    try:
        print("--- Step 1: Normalising input files ---")
        stage_files()
        print("\n--- Step 2: Processing Data ---")
        process_data()
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
