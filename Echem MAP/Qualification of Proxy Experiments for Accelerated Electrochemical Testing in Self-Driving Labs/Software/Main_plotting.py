# -*- coding: utf-8 -*-
"""
Run three Origin automation scripts in sequence:
  1) transfer_to_origin.py      -> builds project from CSVs
  2) rearrange_OCP.py           -> inserts 'time' column for OCP books
  3) generate_plots.py          -> builds graphs, exports TIFF, saves project

This script feeds answers to each script's input() prompts.
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime

# ---- CONFIG: paths to your three scripts (edit these) ----
PY = sys.executable  # use current Python interpreter
SCRIPT_TRANSFER  = r"C:\Users\Plotting\transfer_csv_origin.py"
SCRIPT_REARRANGE = r"C:\Users\Plotting\rearrange_OCP.py"
SCRIPT_PLOTS     = r"C:\Users\\Plotting\generate_plots.py"

# ---- CONFIG: pipeline I/O (edit these) ----
EXPERIMENT_DIR = r"C:\Users\Results\EXPERIMENT_26-10-2025_1641"   # same folder you use in step 1, folder with CPP/Impedance/LPR folders
STAGE1_OPJU    = r"C:\Users\Results\EXPERIMENT_26-10-2025_1641\data.opju" #origin file name with extenstion in EXPERIMENT folder
STAGE2_OPJU    = r"C:\Users\Results\EXPERIMENT_26-10-2025_1641\data_ocp.opju" #origin file name + "_ocp" with extenstion in EXPERIMENT folder
FINAL_OPJU     = r"C:\Users\Results\EXPERIMENT_26-10-2025_1641\data_tiff.opju" #origin file name + "_tiff" with extenstion in EXPERIMENT folder
TIFF_FOLDER    = r"C:\Users\Results\EXPERIMENT_26-10-2025_1641\Graphs"      # where to export images

# ---- utility to run a step and feed input lines ----
def run_step(title: str, script_path: str, stdin_lines=None):
    print(f"\n=== {title} ===")
    if stdin_lines is None:
        input_payload = None
    else:
        # join answers with newlines; input() consumes each one in order
        input_payload = "\n".join(stdin_lines) + "\n"

    cp = subprocess.run(
        [PY, script_path],
        input=input_payload,
        text=True,
        capture_output=True,
        check=False
    )

    # stream script output for visibility
    if cp.stdout:
        print(cp.stdout, end="")
    if cp.stderr:
        # treat non-empty stderr as warning unless returncode != 0
        print(cp.stderr, end="")

    if cp.returncode != 0:
        raise RuntimeError(f"{title} failed with exit code {cp.returncode}")

def main():
    start = datetime.now()
    print(f"[PIPELINE START] {start:%Y-%m-%d %H:%M:%S}")

    # --- Step 1: transfer CSVs to Origin project
    # Prompts: MAIN_DIR, SAVE_AS(.opju)
    run_step(
        "Step 1 - Transfer CSVs",
        SCRIPT_TRANSFER,
        stdin_lines=[
            EXPERIMENT_DIR,
            STAGE1_OPJU
        ]
    )

    # --- Step 2: rearrange OCP (insert time column)
    # Prompts: project to open, Save As (blank to overwrite)
    run_step(
        "Step 2 - Rearrange OCP",
        SCRIPT_REARRANGE,
        stdin_lines=[
            STAGE1_OPJU,
            STAGE2_OPJU  # or "" to overwrite (blank line)
        ]
    )

    # --- Step 3: generate plots + export TIFF + save project
    # Prompts: project to open, TIFF folder, Save As (blank to overwrite)
    run_step(
        "Step 3 - Generate Plots",
        SCRIPT_PLOTS,
        stdin_lines=[
            STAGE2_OPJU,
            TIFF_FOLDER,
            FINAL_OPJU   # or "" to overwrite (blank line)
        ]
    )

    end = datetime.now()
    print(f"\n[PIPELINE DONE] {end:%Y-%m-%d %H:%M:%S}  (elapsed: {end - start})")

if __name__ == "__main__":
    main()