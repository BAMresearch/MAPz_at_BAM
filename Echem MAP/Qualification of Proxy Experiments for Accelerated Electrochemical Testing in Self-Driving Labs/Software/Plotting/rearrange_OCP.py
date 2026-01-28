# -*- coding: utf-8 -*-
"""
For all workbooks whose Long Name contains 'OCP':
  - Insert a new column at A (shifts old A to B).
  - Fill A with 1..N where N = last non-empty row in column B.
"""

import math
import originpro as op  # pip install originpro  (Origin 2021+ required)

# ---------------- user inputs ----------------
# If you want to open a project first (external Python):
OPEN_PROJECT = True
OPJ_PATH_IN  = input("Enter the path to the Origin project to open (.opju/.opj): ").strip() if OPEN_PROJECT else ""
SAVE_AS      = input("Enter the output path to save the modified project (.opju), or blank to overwrite: ").strip()

SHOW_ORIGIN = True  # set False to run hidden (external Python only)
# ------------------------------------------------

# External Python safety / visibility
import sys
def _install_excepthook_for_external():
    if op and op.oext:
        def origin_shutdown_exception_hook(exctype, value, tb):
            try:
                op.exit()
            finally:
                sys.__excepthook__(exctype, value, tb)
        sys.excepthook = origin_shutdown_exception_hook
        if SHOW_ORIGIN:
            op.set_show(True)

_install_excepthook_for_external()

# ---- Open project (optional) ----
if OPEN_PROJECT and OPJ_PATH_IN:
    opened = op.open(OPJ_PATH_IN, readonly=False, asksave=False)  # open an Origin project file
    if not opened:
        raise RuntimeError(f"Could not open: {OPJ_PATH_IN}")

def last_filled_index(col_values):
    """Return number of non-empty rows (trailing blanks removed)."""
    n = len(col_values)
    def is_blank(v):
        if v is None: return True
        if isinstance(v, float) and math.isnan(v): return True
        if isinstance(v, str) and v.strip() == "": return True
        return False
    while n > 0 and is_blank(col_values[n-1]):
        n -= 1
    return n

def fill_index_column(wks):
    """
    Insert a new column at A and fill it with 1..N.
    After insertion, old A becomes B; we compute N from the non-empty length of column B.
    """
    # 1) Insert column at A via LabTalk (inserts before current column).
    #    LabTalk: set current column to 1 (A), then insert a column named "Index".
    #    This will make a new A; existing columns shift to the right.
    #    (LabTalk column operations doc)  [4](https://www.originlab.com/doc/LabTalk/guide/Basic-Worksheet-Column-Operation)[5](https://www.originlab.com/doc/Origin-Help/Arrange-Wks)
    wks.lt_exec('wks.col=1; wks.insert(Index);')

    # 2) Determine N from column B (index 1) after insertion.
    colB = wks.to_list(1)  # read column B values  (WSheet.to_list)  [3](https://docs.originlab.com/originpro/classoriginpro_1_1worksheet_1_1WSheet.html)
    N = last_filled_index(colB)
    if N <= 0:
        # nothing to do; clear A just in case and return
        wks.clear(0, 1)    # clear 1 column starting at A   (WSheet.clear)  [3](https://docs.originlab.com/originpro/classoriginpro_1_1worksheet_1_1WSheet.html)
        return 0

    # 3) Fill new A (index 0) with 1..N and set labels / designations if desired.
    seq = list(range(1, N + 1))
    wks.from_list(0, seq, lname='Time', units='s', axis='X')  # write data to A (WSheet.from_list)  [3](https://docs.originlab.com/originpro/classoriginpro_1_1worksheet_1_1WSheet.html)

    # 4) (Optional) Set column designations: A as X, B as Y for plotting/analysis defaults.
    wks.cols_axis('xy', 0, 1)  # designations for columns 0..1   (WSheet.cols_axis)  [3](https://docs.originlab.com/originpro/classoriginpro_1_1worksheet_1_1WSheet.html)
    return N

modified_sheets = 0
modified_books  = 0

# Iterate over all workbooks in the project (Project.pages('w') generator returns WBook objects). [1](https://www.originlab.com/python/doc/originpro/namespaceoriginpro_1_1project.html)
for wb in op.pages('w'):
    ln = wb.lname or ""   # Long Name of the book (BaseObject.lname)  [2](https://docs.originlab.com/originpro/classoriginpro_1_1base_1_1BaseObject.html)
    if "ocp" not in ln.lower():
        continue

    book_changed = False
    short = wb.name      # short name needed for range strings  (BaseObject.name)  [2](https://docs.originlab.com/originpro/classoriginpro_1_1base_1_1BaseObject.html)

    # Walk all sheets in this workbook: [BookShortName]1, [BookShortName]2, ...
    i = 1
    while True:
        # find_sheet can reference a sheet by numeric index in the range string  [1](https://www.originlab.com/python/doc/originpro/namespaceoriginpro_1_1project.html)
        wks = op.find_sheet('w', f'[{short}]{i}')
        if not wks:
            break

        # Apply transformation
        N = fill_index_column(wks)
        if N > 0:
            modified_sheets += 1
            book_changed = True
        i += 1

    if book_changed:
        modified_books += 1

# Save project (overwrite or save-as)
if SAVE_AS:
    ok = op.save(SAVE_AS)  # Saves to a specific file  (project.save)  [1](https://www.originlab.com/python/doc/originpro/namespaceoriginpro_1_1project.html)
else:
    ok = op.save()         # Save current project in-place  [1](https://www.originlab.com/python/doc/originpro/namespaceoriginpro_1_1project.html)

print(f"[DONE] Updated {modified_sheets} worksheets across {modified_books} OCP workbooks.")
print(f"[SAVE] {'OK' if ok else 'FAILED'}")

# Clean shutdown for external Python
if op and op.oext:
    op.exit()