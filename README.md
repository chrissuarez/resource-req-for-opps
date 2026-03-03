# Resourcing Requirements for Pipeline

This project automates a full workflow:

1. Detect the latest Salesforce exports in `Downloads`
2. Stage them into `data/` as:
   - `data/pipeline.csv`
   - `data/resourcing.csv`
3. Process and explode monthly forecast data
4. Export `looker_studio_pipeline_forecast_v3.csv`
5. Upload the final CSV to Google Sheets for Looker Studio

## Required Salesforce Reports

Download these two reports from Salesforce:

- Pipeline report:  
  `https://jellyfish.lightning.force.com/lightning/r/Report/00ORN000009SNAz2AO/view?queryScope=userFolders`
- Resourcing report:  
  `https://jellyfish.lightning.force.com/lightning/r/Report/00ORN000009Sj8H2AS/view`

After downloading, run the pipeline within 10 minutes so auto-detection can find the files in `Downloads`.

## UTL Report Preparation

Before running UTL processing, prepare and export the UTL source reports:

1. Open the historical utilisation report.
2. Set date range to previous month.
3. Select all capabilities, and deselect irrelevant parent capabilities.
4. Set region to `United Kingdom`.
5. Export data with utilisation by resources.
6. Export rolled up time type report.
7. Put exported CSV files in `data/input`.
8. Run the script:

```bash
python process_utl_pipeline.py
```

UTL input rules:
- UTL processing reads only from `data/input` (never from `Downloads`).
- Raw export filenames are allowed; matching files are auto-normalized to:
  - `data/input/utl_by_capability.csv`
  - `data/input/time_type.csv`
- The newest matching file for each schema is selected.
- Processing fails fast if either required source is missing or has invalid schema.
- Output is written to `data/output/utl_pipeline_output.csv`.

## Setup

## 1) Python dependencies

Install required packages:

```bash
python -m pip install pandas gspread python-dotenv
```

## 2) Google service account

Create/download a service account JSON key and keep it local (do not commit it).

Ensure your target Google Sheet is shared with the service account `client_email` as **Editor**.

## 3) Environment variables

Create a `.env` file in the project root:

```env
GOOGLE_SHEET_URL=https://docs.google.com/spreadsheets/d/your_sheet_id_here/edit
GOOGLE_SHEET_TAB=Latest Data
GOOGLE_SHEET_UTL_TAB=Utl vs Pipeline
SERVICE_ACCOUNT_JSON_PATH=C:/Users/your-user/path/to/service_account.json
```

## Security

- `.env` is git-ignored
- `service_account.json` is git-ignored
- CSV data files are git-ignored

## Run

## Full workflow (recommended)

```bash
python main.py
```

This will:

1. Stage recent CSVs from `Downloads`
2. Process forecast data
3. Upload results to Google Sheets

## Useful options

Stage files only:

```bash
python main.py --stage-only
```

Run ingest + processing, skip Google upload:

```bash
python main.py --skip-upload
```

Run full workflow and also upload UTL output (`data/output/utl_pipeline_output.csv`) to the
tab configured in `GOOGLE_SHEET_UTL_TAB`:

```bash
python main.py --upload-utl
```

Process UTL from `data/input` and upload only UTL output (no forecast ingest/process/upload):

```bash
python main.py --process-utl --upload-utl --utl-only
```

Notes for `--upload-utl`:
- If `data/output/utl_pipeline_output.csv` is missing, UTL upload is skipped with a warning.
- If `GOOGLE_SHEET_UTL_TAB` is unset, UTL upload is skipped with a warning.
- If UTL upload fails after forecast upload succeeds, the run warns and still completes.

Notes for `--process-utl`:
- Runs UTL normalization + processing from `data/input`.
- Can be combined with `--upload-utl` in both normal and `--utl-only` modes.

## Google upload only

If you want to upload an already-generated CSV directly:

```bash
python upload_to_google_sheets.py
```

Optional overrides:

```bash
python upload_to_google_sheets.py --csv-path looker_studio_pipeline_forecast_v3.csv --tab-name "Latest Data"
```

## Success checks

- Script output includes:
  - detected Pipeline/Resourcing files
  - processing/export completion
  - `Successfully updated Google Sheet: [Sheet Name] - [Row Count] rows uploaded.`
- Confirm Looker Studio refreshes from the updated Google Sheet tab.

## Troubleshooting

- `Missing recent Salesforce export(s)`:
  - Re-download both reports and rerun within 10 minutes.
- `Missing Google Sheet URL`:
  - Confirm `.env` exists and contains `GOOGLE_SHEET_URL`.
- `403 The caller does not have permission`:
  - Share the Google Sheet with the service account email.
- `Worksheet tab not found`:
  - Confirm `GOOGLE_SHEET_TAB` matches exactly.
  - For UTL uploads, also confirm `GOOGLE_SHEET_UTL_TAB` matches exactly.
