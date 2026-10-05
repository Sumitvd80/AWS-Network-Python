"""
AWS Network Audit - Master Merger
==================================
Merges multiple aws_network_audit_*.xlsx files into one master workbook.
Extracts account environment (dev/uat/prd) from filename and adds as a column.

Usage:
  python merge_audit_files.py                          # scans current directory
  python merge_audit_files.py --input-dir C:\audits    # scans specific folder
  python merge_audit_files.py --output master.xlsx     # custom output filename
"""

import argparse
import glob
import logging
import os
import re
import sys
from datetime import datetime, timezone

import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment extraction from filename
# e.g. "aws_network_audit_dev-account_20240101T120000Z.xlsx" → "dev"
#      "prd_aws_network_audit_20240101T120000Z.xlsx"         → "prd"
#      "uat-core-network-audit.xlsx"                         → "uat"
# ---------------------------------------------------------------------------

# Longer/compound prefixes must come BEFORE shorter ones so regex matches
# the most specific token first (e.g. "shareservices" before "sandbox").
ENV_PATTERN = re.compile(
    r"(AP-NE1-Directconnect|shareservices|sandbox|security|prd|uat|dev)",
    re.IGNORECASE,
)

# Canonical display names keyed by uppercase match
ENV_LABELS = {
    "AP-DIRECTCONNECT": "AP-NE1-DC",
    "SHARESERVICES":        "ShareSvc",
    "SANDBOX":              "Sandbox",
    "SECURITY":             "Security",
    "PRD":                  "PRD",
    "UAT":                  "UAT",
    "DEV":                  "DEV",
}

def extract_env(filename: str) -> str:
    """Pull the first matching account prefix from the filename."""
    basename = os.path.basename(filename)
    match = ENV_PATTERN.search(basename)
    if match:
        raw = match.group(1).upper()
        return ENV_LABELS.get(raw, raw)
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Excel styling helpers
# ---------------------------------------------------------------------------

ENV_COLORS = {
    "PRD":      "C0392B",   # red      — production stands out
    "UAT":      "D68910",   # amber
    "DEV":      "1A5276",   # navy
    "Sandbox":  "1E8449",   # green
    "Security": "6C3483",   # purple
    "ShareSvc": "117A65",   # teal
    "AP-NE1-DC": "784212",   # brown
    "UNKNOWN":  "717D7E",   # grey
}

def style_header_row(ws) -> None:
    """Dark slate header for the master merged sheet."""
    fill = PatternFill(start_color="1B2631", end_color="1B2631", fill_type="solid")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
    ws.freeze_panes = "A2"


def style_env_rows(ws) -> None:
    """Colour each data row based on the Environment column (column A)."""
    ROW_COLORS = {
        "PRD":      "FADBD8",   # light red
        "UAT":      "FDEBD0",   # light amber
        "DEV":      "D6EAF8",   # light blue
        "Sandbox":  "D5F5E3",   # light green
        "Security": "E8DAEF",   # light purple
        "ShareSvc": "D1F2EB",   # light teal
        "AP-NE1-DC": "FAE5D3",   # light brown
        "UNKNOWN":  "F2F3F4",   # light grey
    }
    for row in ws.iter_rows(min_row=2):       # skip header row
        env_val   = str(row[0].value or "").strip()
        hex_color = ROW_COLORS.get(env_val, "FFFFFF")
        row_fill  = PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")
        for cell in row:
            cell.fill = row_fill


def auto_fit_columns(ws) -> None:
    for col_cells in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            try:
                cell_len = len(str(cell.value)) if cell.value is not None else 0
                max_len = max(max_len, cell_len)
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 2, 62)


# ---------------------------------------------------------------------------
# Core merge logic
# ---------------------------------------------------------------------------

def load_file(filepath: str) -> dict[str, pd.DataFrame]:
    """Load all sheets from one audit Excel file into {sheet_name: DataFrame}."""
    env = extract_env(filepath)
    log.info("  Loading %-10s ← %s", f"[{env}]", os.path.basename(filepath))
    sheets = {}
    try:
        xl = pd.ExcelFile(filepath, engine="openpyxl")
        for sheet in xl.sheet_names:
            df = xl.parse(sheet)
            if df.empty:
                continue
            # Inject Account and Environment columns at the front
            df.insert(0, "Environment", env)
            df.insert(1, "SourceFile", os.path.basename(filepath))
            sheets[sheet] = df
    except Exception as exc:
        log.error("  Failed to load %s: %s", filepath, exc)
    return sheets


def merge_files(input_files: list[str], output_path: str) -> None:
    if not input_files:
        log.error("No audit files found. Check --input-dir or current directory.")
        sys.exit(1)

    log.info("Found %d file(s) to merge:", len(input_files))
    for f in input_files:
        log.info("  • %s", os.path.basename(f))

    # Collect all sheets across all files: {sheet_name: [df1, df2, ...]}
    all_sheets: dict[str, list[pd.DataFrame]] = {}

    for filepath in sorted(input_files):
        file_sheets = load_file(filepath)
        for sheet_name, df in file_sheets.items():
            all_sheets.setdefault(sheet_name, []).append(df)

    # Write master workbook
    log.info("\nWriting master workbook → %s", output_path)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, frames in all_sheets.items():
            merged_df = pd.concat(frames, ignore_index=True)

            # Ensure Environment + SourceFile stay as first two columns
            cols = merged_df.columns.tolist()
            front = [c for c in ["Environment", "SourceFile"] if c in cols]
            rest  = [c for c in cols if c not in front]
            merged_df = merged_df[front + rest]

            merged_df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

            ws = writer.sheets[sheet_name[:31]]
            style_header_row(ws)   # dark header row
            style_env_rows(ws)     # colour each row by environment
            auto_fit_columns(ws)

            log.info("  ✓ %-30s %6d rows from %d file(s)",
                     sheet_name, len(merged_df), len(frames))

    # Summary
    print("\n" + "=" * 65)
    print(f"  Master file : {output_path}")
    print(f"  Sheets      : {len(all_sheets)}")
    print(f"  Source files: {len(input_files)}")
    print("=" * 65)
    for sheet_name, frames in all_sheets.items():
        total = sum(len(f) for f in frames)
        envs  = ", ".join(
            sorted({f["Environment"].iloc[0] for f in frames if not f.empty})
        )
        print(f"  {sheet_name:<30} {total:>6} rows  [{envs}]")
    print("=" * 65 + "\n")



# ---------------------------------------------------------------------------
# CONFIGURE YOUR FOLDER PATH HERE  (only thing you need to change)
# ---------------------------------------------------------------------------

INPUT_FOLDER = r"C:\Users\sumit\Documents\python-testing\AWS-network-config"   # ← folder containing all your 7 xlsx files

# ---------------------------------------------------------------------------
# Entry point  —  output saved in the same folder as this script
# ---------------------------------------------------------------------------

def main() -> None:
    # Resolve input folder
    input_dir = os.path.abspath(INPUT_FOLDER)
    if not os.path.isdir(input_dir):
        log.error("Input folder not found: %s", input_dir)
        sys.exit(1)

    # Output saved next to this script, not inside the input folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp  = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_file = os.path.join(script_dir, f"aws_network_audit_MASTER_{timestamp}.xlsx")

    # Collect all xlsx files, skip any existing MASTER files
    input_files = sorted([
        os.path.join(input_dir, f)
        for f in os.listdir(input_dir)
        if f.lower().endswith(".xlsx")
        and "MASTER" not in f.upper()
    ])

    if not input_files:
        log.error("No .xlsx files found in: %s", input_dir)
        sys.exit(1)

    log.info("Input folder : %s", input_dir)
    log.info("Output folder: %s", script_dir)
    log.info("Files found  : %d", len(input_files))

    merge_files(input_files, output_file)


if __name__ == "__main__":
    main()
