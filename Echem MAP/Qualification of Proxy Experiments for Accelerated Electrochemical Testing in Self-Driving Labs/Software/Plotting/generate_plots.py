# -*- coding: utf-8 -*-
"""
Generate graphs from an Origin project and:
  1) Keep them in the project (save the .opju),
  2) Export each as TIFF to a chosen folder.

Workbooks:
  - OCP*           : scatter (X=A, Y=B)
  - LPR_csv        : line   (X=A, Y=B)
  - CPP_csv        : line   (X=A, Y=B), log Y
  - Impedance_csv  : (1) 2-Y scatter: X=A, Y1=B (left, log), Y2=E (right)
                     (2) scatter + line: X=C, Y=D (single layer)

Graph Long Name = "<Workbook Long Name> - <Sheet Name>"
"""

import os
import re
import sys
from pathlib import Path
import originpro as op  # pip install originpro (Origin 2021+ required)

# ----------------------------- Inputs -----------------------------
OPEN_PROJECT = True
proj_in = input("Path to OPJ/OPJU to open (leave blank to use current project): ").strip()

out_dir = input("Folder to save TIFFs (created if missing) [default: <Origin User Folder>/GraphExports]: ").strip()
if not out_dir:
    out_dir = str(Path(op.path()) / "GraphExports")  # Origin user folder

# --- keep your inputs as-is ---
save_choice = input(
    "Save project: press Enter to OVERWRITE current project, or type a full .opju path to Save As: "
).strip()


# ---- change run definition to accept it ----
def run(save_choice: str):
    # ... your plotting loop above ...
    # -------- Save the Origin project with graphs included --------
    save_target = save_choice.strip()
    if save_target:
        if not save_target.lower().endswith(".opju"):
            save_target = save_target + ".opju"
        ok = op.save(save_target)     # save to a specific file
        print(f"[SAVE-AS] {'OK' if ok else 'FAILED'} -> {save_target}")
    else:
        ok = op.save()                # overwrite current project
        print(f"[SAVE]    {'OK' if ok else 'FAILED'} (current project)")

if __name__ == "__main__":
    try:
        run(save_choice)              # <-- pass it here
    finally:
        if op and op.oext:
            op.exit()

Path(out_dir).mkdir(parents=True, exist_ok=True)
SHOW_ORIGIN = True  # visible when running external Python

# -------------------- External Python nicety ----------------------
def _install_excepthook_for_external():
    if op and op.oext:
        def origin_shutdown_exception_hook(exctype, value, tb):
            try: op.exit()
            finally: sys.__excepthook__(exctype, value, tb)
        sys.excepthook = origin_shutdown_exception_hook
        if SHOW_ORIGIN:
            op.set_show(True)

_install_excepthook_for_external()

# ------------------------ Open project  ---------------------------
def resolve_project_path(p: str) -> Path | None:
    if not p: return None
    cand = Path(p)
    if cand.is_dir():
        picks = sorted(cand.glob("*.opju")) or sorted(cand.glob("*.opj"))
        if not picks: return None
        picks.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return picks[0]
    if cand.suffix.lower() in (".opju", ".opj"):
        return cand if cand.exists() else None
    for ext in (".opju", ".opj"):
        trial = cand.with_suffix(ext)
        if trial.exists(): return trial
    return None

if OPEN_PROJECT and proj_in:
    proj = resolve_project_path(proj_in)
    if not proj:
        raise RuntimeError(f"Cannot resolve a valid Origin project from:\n  {proj_in}")
    if not op.open(str(proj), readonly=False, asksave=False):  # open project file
        raise RuntimeError(f"Origin could not open project:\n  {proj}")
    print(f"[OPENED] {proj}")
else:
    print("[INFO] Using the currently open Origin project.")

# -------------------------- Helpers -------------------------------
def sanitize_filename(s: str) -> str:
    s = re.sub(r'[\\/*?:"<>|]+', '_', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:180]

def worksheet_display_name(wks) -> str:
    try:
        ln = getattr(wks, 'lname', None)
        return ln if (ln and ln.strip()) else wks.name
    except Exception:
        return wks.get_str('name')

def make_graph_long_name(wb, wks) -> str:
    wb_ln = wb.lname or wb.name
    sh_nm = worksheet_display_name(wks)
    return f"{wb_ln} - {sh_nm}"

def save_tiff(gpage, outdir: str, graph_ln: str, width_px: int = 2400) -> str:
    # GPage.save_fig infers file type from extension; 'width' is pixels for raster.  (docs)  ⟶ TIFF supported
    # https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GPage.html
    fname = sanitize_filename(graph_ln) + ".tif"
    fpath = str(Path(outdir) / fname)
    out = gpage.save_fig(fpath, width=width_px)   # export
    return out

# ------------------- Graph building primitives --------------------
def new_graph_page(template: str = 'scatter'):
    gp = op.new_graph(template=template)  # new graph page using template  (examples)
    gl = gp[0]                           # first layer
    return gp, gl  # https://www.originlab.com/doc/python/Examples/Graphing

def add_xy(gl, wks, xcol: int, ycol: int, kind: str):
    """
    kind: 's' scatter, 'l' line
    add_plot supports (wks, coly=?, colx=?, type='s'/'l')
    """
    return gl.add_plot(wks, coly=ycol, colx=xcol, type=kind)  # examples in docs

def set_axis_log(gl, which: str, yes: bool):
    ax = gl.axis(which)                # Axis object (x or y)
    ax.scale = 'log10' if yes else 'linear'  # Axis.scale setter supports strings
    # https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1Axis.html

def set_graph_long_name(gp, ln: str):
    gp.lname = ln  # BasePage/BaseObject exposes .lname

# -------------------- Per-workbook plotters ----------------------
def plot_ocp_sheet(wb, wks, outdir):
    """OCP*: scatter X=A(0), Y=B(1)"""
    gp, gl = new_graph_page('scatter')
    add_xy(gl, wks, 0, 1, 's')
    gl.rescale()
    ln = make_graph_long_name(wb, wks)
    set_graph_long_name(gp, ln)
    tif = save_tiff(gp, outdir, ln)
    print(f"[OCP]  {tif}")

def plot_lpr_sheet(wb, wks, outdir):
    """LPR_csv: line X=A, Y=B"""
    gp, gl = new_graph_page('line')
    add_xy(gl, wks, 0, 1, 'l')
    gl.rescale()
    ln = make_graph_long_name(wb, wks)
    set_graph_long_name(gp, ln)
    tif = save_tiff(gp, outdir, ln)
    print(f"[LPR]  {tif}")

def plot_cpp_sheet(wb, wks, outdir):
    """CPP_csv: line X=A, Y=B, log Y"""
    gp, gl = new_graph_page('line')
    add_xy(gl, wks, 0, 1, 'l')
    set_axis_log(gl, 'y', True)   # log10 Y
    gl.rescale()
    ln = make_graph_long_name(wb, wks)
    set_graph_long_name(gp, ln)
    tif = save_tiff(gp, outdir, ln)
    print(f"[CPP]  {tif}")

def plot_impedance_sheet_twoY(wb, wks, outdir):
    """
    Impedance_csv: 2-Y scatter
      layer 1 (left Y): X=A(0), Y1=B(1), log X & log Y1
      layer 2 (right Y): X=A(0), Y2=E(4)
    """
    gp, gl1 = new_graph_page('scatter')
    add_xy(gl1, wks, 0, 1, 's')
    set_axis_log(gl1, 'x', True)
    set_axis_log(gl1, 'y', True)

    # Add Right-Y layer = index 2  (GPage.add_layer) then plot Y2
    gl2 = gp.add_layer(2)  # right Y layer
    gl2.activate()
    add_xy(gl2, wks, 0, 4, 's')

    gl1.rescale(); gl2.rescale()
    ln = make_graph_long_name(wb, wks) + " (2Y)"
    set_graph_long_name(gp, ln)
    tif = save_tiff(gp, out_dir, ln)
    print(f"[IMP-2Y] {tif}")

def plot_impedance_sheet_scatter_line(wb, wks, outdir):
    """Impedance_csv: scatter + line overlay, X=C(2), Y=D(3)"""
    gp, gl = new_graph_page('scatter')
    add_xy(gl, wks, 2, 3, 's')
    add_xy(gl, wks, 2, 3, 'l')
    gl.rescale()
    ln = make_graph_long_name(wb, wks) + " (C-D scatter+line)"
    set_graph_long_name(gp, ln)
    tif = save_tiff(gp, outdir, ln)
    print(f"[IMP-CD] {tif}")

# ------------------------ Sheet iterator -------------------------
def iter_sheets_in_book(wb):
    short = wb.name  # workbook short name for range strings
    i = 1
    while True:
        wks = op.find_sheet('w', f'[{short}]{i}')
        if not wks: break
        yield wks
        i += 1

# ------------------------ Main routine ---------------------------
def run(save_choice: str, out_dir: str):
    made = 0
    for wb in op.pages('w'):   # iterate all workbooks in project
        wbln = (wb.lname or "").lower()

        is_ocp = ("ocp" in wbln)
        is_lpr = (wbln == "lpr_csv")
        is_cpp = (wbln == "cpp_csv")
        is_imp = (wbln == "impedance_csv")

        for wks in iter_sheets_in_book(wb):
            try:
                if is_ocp:
                    plot_ocp_sheet(wb, wks, out_dir); made += 1
                elif is_lpr:
                    plot_lpr_sheet(wb, wks, out_dir); made += 1
                elif is_cpp:
                    plot_cpp_sheet(wb, wks, out_dir); made += 1
                elif is_imp:
                    plot_impedance_sheet_twoY(wb, wks, out_dir)
                    plot_impedance_sheet_scatter_line(wb, wks, out_dir)
                    made += 2
            except Exception as e:
                print(f"[WARN] Skipped {wb.lname} / {worksheet_display_name(wks)}: {e}")

    # -------- Save the Origin project with graphs included --------
    save_target = (save_choice or "").strip()  # local copy; don't modify the outer var
    if save_target:
        if not save_target.lower().endswith(".opju"):
            save_target = save_target + ".opju"
        ok = op.save(save_target)    # save to a specific file
        print(f"[SAVE-AS] {'OK' if ok else 'FAILED'} -> {save_target}")
    else:
        ok = op.save()               # overwrite current project
        print(f"[SAVE]    {'OK' if ok else 'FAILED'} (current project)")

    print(f"\n[DONE] Exported {made} TIFF(s) to: {out_dir}")


if __name__ == "__main__":
    try:
        # IMPORTANT: pass both values in
        run(save_choice, out_dir)
    finally:
        if op and op.oext:
            op.exit()