# -*- coding: utf-8 -*-
"""
Build an Origin project from a folder tree:
Experiment/
  ├─ CPP/
  │    ├─ CPP_csv/            -> workbook "CPP_csv"
  │    └─ OCP_CPP_csv/        -> workbook "OCP_CPP_csv"
  ├─ Impedance/
  │    ├─ Impedance_csv/      -> workbook ...
  │    └─ OCP_impedance_csv/
  └─ LPR/
       ├─ LPR_csv/
       ├─ LPR_stats/
       └─ OCP_LPR_csv/

Each CSV in a "final" folder becomes a new worksheet in that workbook.
Column headers like "Potential (V)" become Long Name = "Potential", Units = "V".
"""

import os
import re
import sys
import csv
import pandas as pd

import originpro as op  # pip install originpro (requires Origin 2021+ on Windows)

# ---------- User settings ----------

MAIN_DIR = input("Enter the path to your main Experiment folder: ").strip()
while not os.path.isdir(MAIN_DIR):
    print("Invalid folder path. Please try again.")
    MAIN_DIR = input("Enter the path to your main Experiment folder: ").strip()

SAVE_AS = input("Enter the full path (including .opju) where you want to save the Origin project: ").strip()
if not SAVE_AS.lower().endswith(".opju"):
    SAVE_AS += ".opju"

SHOW_ORIGIN = True                        # set False to run Origin hidden when using external Python
CSV_GLOB_EXTS = (".csv",)  # extensions to consider as "CSV-like"
EXCLUDE_FINAL_FOLDERS = {"lpr_stats", "lpr-stats"}



# ---------- External Python wrappers (safe Origin startup/shutdown) ----------
# (Not used by Origin's embedded Python; guarded internally)
def _install_excepthook_for_external():
    """Ensure Origin shuts down on uncaught exceptions (external Python only)."""
    if op and op.oext:
        def origin_shutdown_exception_hook(exctype, value, tb):
            try:
                op.exit()
            finally:
                sys.__excepthook__(exctype, value, tb)
        sys.excepthook = origin_shutdown_exception_hook
        if SHOW_ORIGIN:
            op.set_show(True)

_install_excepthook_for_external()  # per Origin’s External Python guidance
# Ref: https://www.originlab.com/doc/ExternalPython/External-Python-Code-Samples
# [6](https://www.originlab.com/doc/ExternalPython/External-Python-Code-Samples)


# ---------- Helpers ----------
FORBIDDEN = set(list('{}`|"<>()![]'))  # disallowed in sheet names in Origin
# Ref: Worksheet, Column and Cell Range Naming Conventions
# [7](https://www.originlab.com/doc/Origin-Help/WksCol-CellRange-Names)

def sanitize_sheet_name(name: str, fallback_prefix="Sheet"):
    """Make a safe worksheet name following Origin's rules."""
    base = os.path.splitext(name)[0]  # drop extension
    # Remove forbidden characters
    base = "".join(ch for ch in base if ch not in FORBIDDEN)
    base = base.strip()
    # Cannot begin with a special character; if so, prefix
    if not base or not base[0].isalnum():
        base = f"{fallback_prefix}_{base}"
    # Max 64 chars
    return base[:64]

HEADER_RE = re.compile(r"^(.*?)\s*\((.*?)\)\s*$")  # "Name (unit)" -> groups

def split_longname_unit(col_header: str):
    """Parse 'LongName (unit)' -> ('LongName','unit'); if no match, unit=''."""
    m = HEADER_RE.match(str(col_header))
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return col_header.strip(), ""


def is_final_folder(path: str) -> bool:
    """A 'final' folder is one that contains CSV files (and no deeper subdirs used here)."""
    if not os.path.isdir(path):
        return False
    for f in os.listdir(path):
        if os.path.isfile(os.path.join(path, f)) and f.lower().endswith(CSV_GLOB_EXTS):
            return True
    return False

NEVER_SEP = '\x07'  # unlikely to appear in your files

def read_csv_single_column(path: str) -> pd.DataFrame:
    """Read a true one-column CSV even if header/values contain commas."""
    return pd.read_csv(
        path,
        header=0,
        sep=NEVER_SEP,     # force: treat whole line as one field
        engine='python'
    )

def read_csv_flexible(path: str) -> pd.DataFrame:
    """
    Robust general reader:
    - try auto-sniff
    - fall back to common seps
    - fall back to no-quoting
    """
    try:
        return pd.read_csv(path, header=0, sep=None, engine='python', on_bad_lines='error')
    except pd.errors.ParserError:
        pass
    for sep in [',', ';', '\t', r'\s+']:
        try:
            return pd.read_csv(path, header=0, sep=sep, engine='python', on_bad_lines='skip')
        except Exception:
            continue
    # last resort: treat quotes literally
    try:
        return pd.read_csv(path, header=0, sep=None, engine='python',
                           on_bad_lines='skip', quoting=csv.QUOTE_NONE, escapechar='\\')
    except Exception as e:
        raise pd.errors.ParserError(f"{path}: {e}")

# ---------- Main workflow ----------
def build_origin_project(main_dir: str, save_as: str):
    # Start a new project and go to the root folder (/UNTITLED).
    op.new()                              # start a fresh Origin project
    op.pe.cd('/UNTITLED')                 # Project Explorer root
    # Ref: Project Folders example shows pe.cd and pe.mkdir usage
    # [1](https://www.originlab.com/doc/python/Examples/Project-Folders)

    # Discover top-level folders under main_dir
    top_folders = [d for d in os.listdir(main_dir)
                   if os.path.isdir(os.path.join(main_dir, d))]
    top_folders.sort()

    for top in top_folders:
        top_path = os.path.join(main_dir, top)
        # Create a PE folder with the same name and enter it
        op.pe.mkdir(top)                  # make a PE folder
        op.pe.cd(f'"{top}"')              # cd into that folder (quotes handle spaces)
        # [1](https://www.originlab.com/doc/python/Examples/Project-Folders)

        # Identify "final" subfolders that contain CSVs
        subfolders = [sf for sf in os.listdir(top_path)
                      if is_final_folder(os.path.join(top_path, sf))]
        subfolders.sort()

        for sub in subfolders:
            final_path = os.path.join(top_path, sub)
            
            # Create workbook as before...
            wb = op.new_book('w', lname=sub)
            
            first_sheet_used = False
            csv_files = sorted(
                f for f in os.listdir(final_path)
                if os.path.isfile(os.path.join(final_path, f))
                and f.lower().endswith(CSV_GLOB_EXTS)
            )
            
            is_ocp_folder = sub.lower().startswith('ocp_')  # <- key line

            for i, csv_name in enumerate(csv_files):
                csv_path = os.path.join(final_path, csv_name)

                # ---- READ DATA ----
                try:
                    if is_ocp_folder:
                        df = read_csv_single_column(csv_path)   # force 1-col mode
                    else:
                        df = read_csv_flexible(csv_path)        # normal mode
                except Exception as e:
                    # one more try: if not OCP but parsing failed, try 1-col anyway
                    try:
                        df = read_csv_single_column(csv_path)
                        print(f"[INFO] Treated as single-column: {csv_path}")
                    except Exception as e2:
                        print(f"[WARN] Skipping {csv_path}: {e2}")
                        continue

                # Parse Long Name + Unit from header(s)
                long_names, units = zip(*(split_longname_unit(c) for c in df.columns))

                # ---- CREATE/NAME SHEET ----
                sheet_name = sanitize_sheet_name(csv_name, fallback_prefix="WS")
                if not first_sheet_used:
                    wks = wb[0]
                    wks.obj.LT_execute(f'wks.name$="{sheet_name}";')
                    first_sheet_used = True
                else:
                    wks = wb.add_sheet(name=sheet_name)

                # ---- WRITE DATA + LABELS ----
                wks.from_df(df)                        # write data
                wks.set_labels(list(long_names), 'L')  # Long Names
                wks.set_labels(list(units), 'U')       # Units
                # (WSheet.set_labels for 'L' and 'U')

        # Return to Project Explorer root before handling the next top-level folder
        op.pe.cd('/UNTITLED')  # back to root
        # [1](https://www.originlab.com/doc/python/Examples/Project-Folders)

    # Save the project
    op.save(save_as)  # e.g., *.opju
    # [2](https://www.originlab.com/python/doc/originpro/namespaceoriginpro_1_1project.html)
    
    os.makedirs(os.path.dirname(SAVE_AS), exist_ok=True)
    ok = op.save(SAVE_AS)
    if not ok:
        raise RuntimeError(f"Origin failed to save: {SAVE_AS}")



if __name__ == "__main__":
    try:
        build_origin_project(MAIN_DIR, SAVE_AS)
    finally:
        # Clean shutdown for external Python; no-op in embedded Python
        if op and op.oext:
            op.exit()
