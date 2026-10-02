#!/usr/bin/env python3
"""Input type 2 (regression folder) -> regression_report.html + summary_report.xlsx

Usage:  python regression_report.py /path/to/regression_folder [-o OUTPUT_DIR]
Needs:  jinja2, pandas, openpyxl

Run matching: every log is matched to its suite run by  <sut_xx_yy>_<Timestamp from log header>
== key in regression_test_summary.json["execution_order"].  A .zip (no header) falls back to
"same SUT whose execution_order lists the case".
"""
import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.marker import DataPoint
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from common import (COLOR, LABEL, RUN_KEY_RE, STATUSES, build_records, case_id_of, details_by_case, fmt_ts,
                    group_cases, load_json, log, parse_ts, pie_segments, render, to_float)

SOFT = {"Passed": "C6EFCE", "Failed": "FFC7CE", "Error": "FFD8A8", "Pending": "FFEB9C",
        "Skipped": "E7E6E6", "NAN": "D9D9D9", "No log": "F2F2F2"}
BORDER = Border(*[Side(style="thin", color="999999")] * 4)


# ================================================================== runs
def build_runs(summary, recs):
    """One run per execution_order key; assigns run_key / order to every record."""
    ips = {r["sut"]: r["ip"] for r in recs}          # setup IP per SUT (from log headers)
    runs = {}
    for key, items in (summary.get("execution_order") or {}).items():
        m = RUN_KEY_RE.match(key)
        if not m:
            log.warning("Unrecognised execution_order key: %s", key)
            continue
        runs[key] = dict(key=key, sut=m.group(1), ip=ips.get(m.group(1), m.group(1)), ts=parse_ts(m.group(2)),
                         order=[c for c in map(case_id_of, items or []) if c], records=[])
    for r in recs:
        run = runs.get("%s_%s" % (r["sut"], r["ts_raw"]))
        if run is None:      # zip file / header without an exact match
            cands = [x for x in runs.values() if x["sut"] == r["sut"] and r["case_id"] in x["order"]]
            free = [x for x in cands if not any(y["case_id"] == r["case_id"] for y in x["records"])]
            run = (free or cands or [None])[0]
        if run is None:
            log.warning("%s is not in any execution_order entry", r["file_name"])
            key = "%s_%s" % (r["sut"], r["ts_raw"] or "no-timestamp")
            run = runs.setdefault(key, dict(key=key, sut=r["sut"], ip=r["ip"], ts=parse_ts(r["ts_raw"]),
                                            order=[], records=[]))
        r["run_key"] = run["key"]
        if r["case_id"] in run["order"]:
            r["order"] = run["order"].index(r["case_id"])
        run["records"].append(r)
    out = sorted(runs.values(), key=lambda x: (x["ts"] is None, x["ts"], x["key"]))
    for run in out:
        run["records"].sort(key=lambda r: r["order"])
        run["counts"] = Counter(r["status"] for r in run["records"])
        run["label"] = "%s @ %s" % (run["ip"], fmt_ts(run["ts"]))
    return out


# ================================================================== Excel helpers
def autofit(ws, cap=60):
    widths = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None:
                widths[c.column] = max(widths.get(c.column, 0), max(len(x) for x in str(c.value).split("\n")))
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = min(max(w + 2, 9), cap)


def status_colors(ws, rng):
    for text, color in SOFT.items():
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"%s"' % text],
                                                      fill=PatternFill("solid", start_color=color, end_color=color)))


def as_table(ws, name):
    """Real Excel Table (named, filterable) -> the source for PivotTables."""
    if ws.max_row > 1:
        t = Table(displayName=name, ref="A1:%s%d" % (get_column_letter(ws.max_column), ws.max_row))
        t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(t)
    ws.freeze_panes = "A2"


def link_column(ws, header):
    col = [c.value for c in ws[1]].index(header) + 1
    for row in range(2, ws.max_row + 1):
        cell = ws.cell(row=row, column=col)
        if cell.value:
            cell.hyperlink = Path(cell.value).as_uri()
            cell.font = Font(color="0563C1", underline="single")


# ================================================================== Excel sheets
def flat_frame(runs):
    """One row per execution - flat 'fact table' (best source for PivotTables)."""
    rows = []
    for run in runs:
        for r in run["records"]:
            h = r["header"]
            rows.append({
                "Run": run["label"], "Run ID": run["key"], "Run Start": run["ts"],
                "Execution Order": r["order"] + 1 if r["order"] < 10 ** 9 else None,
                "Case ID": r["case_id"], "Test Name": r["name"], "Status": LABEL[r["status"]],
                "Is Pass": int(r["status"] == "passed"), "Is Fail": int(r["status"] in ("failed", "error")),
                "SUT": r["sut"], "Setup IP": r["ip"], "Duration (s)": r["duration"],
                "Markers": ", ".join(r["markers"]), "Product": h.get("Product", ""), "OS": h.get("OS", ""),
                "Firmware Version": h.get("Firmware Version", ""), "Git Branch": h.get("Git Branch Info", ""),
                "Drive Capacity": h.get("Drive Capacity", ""), "Test File Path": r["test_file"],
                "Function Name": r["function"], "Log File": r["file"]})
    return pd.DataFrame(rows)


def sheet_test_details(xw, df, details, names):
    """Sheet: regression_test_details.json (markers, duration, ...) + execution counts per case."""
    rows = []
    for cid in sorted(set(details) | set(df["Case ID"])):
        d, sub = details.get(cid, {}), df[df["Case ID"] == cid]
        p, f, n = int(sub["Is Pass"].sum()), int(sub["Is Fail"].sum()), len(sub)
        verdict = ("Not executed" if n == 0 else "Stable pass" if p == n else "Consistent fail" if f == n
                   else "Flaky / setup-dependent" if p and f else "Other")
        rows.append({"Case ID": cid, "Test Name": names.get(cid, ""), "Duration (s)": to_float(d.get("duration")),
                     "Markers": d.get("markers", ""), "Test File Path": d.get("file_path", ""),
                     "Function Name": d.get("function_name", ""), "Executions": n, "Passed": p,
                     "Failed / Error": f, "Setup Count": sub["SUT"].nunique(),
                     "Setups (IP)": ", ".join(sorted(sub["Setup IP"].unique())), "Verdict": verdict})
    pd.DataFrame(rows).to_excel(xw, sheet_name="Test Details", index=False)
    ws = xw.sheets["Test Details"]
    as_table(ws, "tblTestDetails")
    vcol = get_column_letter(ws.max_column)          # Verdict is the last column
    for text, color in (("Stable pass", "C6EFCE"), ("Consistent fail", "FFC7CE"), ("Flaky / setup-dependent", "FFEB9C")):
        ws.conditional_formatting.add("%s2:%s%d" % (vcol, vcol, ws.max_row), CellIsRule(
            operator="equal", formula=['"%s"' % text], fill=PatternFill("solid", start_color=color, end_color=color)))
    autofit(ws)


def sheet_execution_order(wb, runs, names):
    """Sheet: one bordered table per run, cases in execution order + path of their log."""
    ws = wb.create_sheet("Execution Order")
    row = 1
    for n, run in enumerate(runs, 1):
        ws.cell(row=row, column=1, value="Run %d  |  %s  |  %s  |  %s" % (n, run["ip"], fmt_ts(run["ts"]), run["key"])
                ).font = Font(bold=True, size=12, color="1F3864")
        row += 1
        for j, h in enumerate(["#", "Case ID", "Test Name", "Status", "Duration (s)", "Log File"], 1):
            c = ws.cell(row=row, column=j, value=h)
            c.font, c.border = Font(bold=True, color="FFFFFF"), BORDER
            c.fill = PatternFill("solid", start_color="1F3864", end_color="1F3864")
        items = []
        for cid in run["order"]:                      # executed order, even if the log is missing
            items += [r for r in run["records"] if r["case_id"] == cid] or [cid]
        items += [r for r in run["records"] if r["case_id"] not in run["order"]]
        for i, it in enumerate(items, 1):
            row += 1
            if isinstance(it, str):                   # case in execution_order without a log file
                vals = [i, it, names.get(it, ""), "No log", None, ""]
            else:
                vals = [i, it["case_id"], it["name"], LABEL[it["status"]], it["duration"], it["file"]]
            for j, v in enumerate(vals, 1):
                c = ws.cell(row=row, column=j, value=v)
                c.border = BORDER
                if j == 6 and v:
                    c.hyperlink, c.font = Path(v).as_uri(), Font(color="0563C1", underline="single")
        row += 3
    status_colors(ws, "D1:D%d" % row)
    for col, w in zip("ABCDEF", (6, 14, 42, 12, 14, 80)):
        ws.column_dimensions[col].width = w


def history_text(items):
    """[(status, ip), ...] in time order -> 'Failed x2 (ip1, ip2) -> Skipped x1 (ip3) -> Passed x1 (ip4)'."""
    groups = []
    for st, ip in items:
        if groups and groups[-1][0] == st:
            groups[-1][1].append(ip)
        else:
            groups.append([st, [ip]])
    return " \u2192 ".join("%s x%d (%s)" % (LABEL[st], len(ips), ", ".join(ips)) for st, ips in groups)


def sheet_history(wb, runs):
    """Sheet: every execution of a case (one log = one execution on one setup) sorted by time.
    Case ID / name / conclusion are merged per case; status, setup IP and log file stay one per row."""
    ws = wb.create_sheet("Execution History")
    heads = ["Case ID", "Test Name", "Conclusion (time order)", "#", "Timestamp", "Status", "Setup IP", "Log File Name"]
    for j, h in enumerate(heads, 1):
        c = ws.cell(row=1, column=j, value=h)
        c.font, c.border = Font(bold=True, color="FFFFFF"), BORDER
        c.fill = PatternFill("solid", start_color="1F3864", end_color="1F3864")
    cases = {}
    for i, run in enumerate(runs):
        for r in run["records"]:
            cases.setdefault(r["case_id"], []).append((parse_ts(r["ts_raw"]) or run["ts"], i, r["order"], r))
    row = 2
    for cid in sorted(cases):
        items = sorted(cases[cid], key=lambda x: (x[0] is None, x[0], x[1], x[2]))
        first = row
        for n, (ts, _, _, r) in enumerate(items, 1):
            vals = [cid, r["name"], history_text([(x[3]["status"], x[3]["ip"]) for x in items]),
                    n, fmt_ts(ts), LABEL[r["status"]], r["ip"], r["file_name"]]
            for j, v in enumerate(vals, 1):
                c = ws.cell(row=row, column=j, value=v if (n == 1 or j > 3) else None)
                c.border = BORDER
                c.alignment = Alignment(vertical="center", wrap_text=(j == 3))
                if j == 8:
                    c.hyperlink, c.font = Path(r["file"]).as_uri(), Font(color="0563C1", underline="single")
            row += 1
        if row - first > 1:
            for col in (1, 2, 3):
                ws.merge_cells(start_row=first, start_column=col, end_row=row - 1, end_column=col)
    status_colors(ws, "F2:F%d" % max(row, 2))
    ws.freeze_panes = "A2"
    for col, w in zip("ABCDEFGH", (14, 26, 70, 5, 20, 11, 18, 70)):
        ws.column_dimensions[col].width = w


def sheet_data(xw, df):
    """Sheet: flat table 'tblExecutions' -> Insert > PivotTable > pick this table."""
    df.to_excel(xw, sheet_name="Data", index=False)
    ws = xw.sheets["Data"]
    as_table(ws, "tblExecutions")
    status_colors(ws, "G2:G%d" % ws.max_row)
    for cell in ws["C"][1:]:
        cell.number_format = "dd-mm-yyyy hh:mm:ss"
    link_column(ws, "Log File")
    autofit(ws)


def sheet_dashboard(xw, df, folder):
    """Sheet 'Dashboard Data' (chart sources) + sheet 'Dashboard' (KPI tiles + charts)."""
    labels = [LABEL[s] for s in STATUSES]
    run_order = list(dict.fromkeys(df["Run"]))
    by_sut = pd.crosstab(df["Setup IP"], df["Status"]).reindex(columns=labels, fill_value=0)
    by_run = pd.crosstab(df["Run"], df["Status"]).reindex(index=run_order, columns=labels, fill_value=0)
    for t in (by_sut, by_run):
        t.columns.name = None
    mk = df.assign(Marker=df["Markers"].str.split(",")).explode("Marker")
    mk["Marker"] = mk["Marker"].fillna("").str.strip()
    mk = mk[mk["Marker"] != ""].groupby("Marker").agg(N=("Case ID", "size"), P=("Is Pass", "sum")).reset_index()
    mk["Pass %"] = (mk["P"] * 100.0 / mk["N"]).round(1)
    top = (df[df["Is Fail"] == 1].groupby("Case ID").size().sort_values(ascending=False).head(10)
           .iloc[::-1].reset_index(name="Failed / Error runs"))
    tables = {"status": pd.DataFrame({"Status": labels, "Count": [int((df["Status"] == s).sum()) for s in labels]}),
              "sut": by_sut.reset_index(), "run": by_run.reset_index(), "top": top, "marker": mk[["Marker", "Pass %"]]}

    pos, col = {}, 0                                  # where each table was written
    for name, t in tables.items():
        t.to_excel(xw, sheet_name="Dashboard Data", startcol=col, index=False)
        pos[name] = (col, len(t), t.shape[1])
        col += t.shape[1] + 1
    dd = xw.sheets["Dashboard Data"]
    autofit(dd)

    ws = xw.book.create_sheet("Dashboard")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    for c in range(2, 21):
        ws.column_dimensions[get_column_letter(c)].width = 11
    ws["B1"], ws["B2"] = "Regression Dashboard", "Source: %s" % Path(folder).resolve()
    ws["B1"].font, ws["B2"].font = Font(size=18, bold=True, color="1F3864"), Font(italic=True, color="6B7785")

    g = df.groupby("Case ID")[["Is Pass", "Is Fail"]].sum()
    tiles = [("Executions", len(df), "DDEBF7"), ("Unique cases", df["Case ID"].nunique(), "DDEBF7"),
             ("Setups (SUT)", df["SUT"].nunique(), "DDEBF7"),
             ("Pass rate", "%.1f%%" % (df["Is Pass"].sum() * 100.0 / len(df)), "C6EFCE"),
             ("Failed / Error", int(df["Is Fail"].sum()), "FFC7CE"),
             ("Flaky cases", int(((g["Is Pass"] > 0) & (g["Is Fail"] > 0)).sum()), "FFEB9C")]
    for i, (label, value, color) in enumerate(tiles):
        c = 2 + 3 * i
        ws.merge_cells(start_row=4, start_column=c, end_row=4, end_column=c + 2)
        ws.merge_cells(start_row=5, start_column=c, end_row=6, end_column=c + 2)
        ws.cell(row=4, column=c, value=label).font = Font(size=10, color="44546A")
        ws.cell(row=5, column=c, value=value).font = Font(size=22, bold=True, color="1F3864")
        for r in range(4, 7):
            for cc in range(c, c + 3):
                ws.cell(row=r, column=cc).fill = PatternFill("solid", start_color=color, end_color=color)
                ws.cell(row=r, column=cc).alignment = Alignment(horizontal="center", vertical="center")

    def chart(name, title, anchor, kind="col", stacked=False, colors=None):
        c0, n, nc = pos[name]
        if n == 0:
            return
        ch = PieChart() if kind == "pie" else BarChart()
        ch.title = title
        if kind != "pie":
            ch.type = kind
            if stacked:
                ch.grouping, ch.overlap = "stacked", 100
        ch.add_data(Reference(dd, min_col=c0 + 2, max_col=c0 + nc, min_row=1, max_row=n + 1), titles_from_data=True)
        ch.set_categories(Reference(dd, min_col=c0 + 1, min_row=2, max_row=n + 1))
        if kind == "pie":
            for i, color in enumerate(colors):
                pt = DataPoint(idx=i)
                pt.graphicalProperties.solidFill = color
                ch.series[0].dPt.append(pt)
        else:
            for ser, color in zip(ch.series, colors):
                ser.graphicalProperties.solidFill = color
            if nc == 2:
                ch.legend = None
        ch.width, ch.height = 18.5, 7.5
        ws.add_chart(ch, anchor)

    all_colors = [COLOR[s] for s in STATUSES]
    chart("status", "Status distribution", "B8", "pie", colors=all_colors)
    chart("sut", "Results per setup (IP)", "K8", "col", True, all_colors)
    chart("run", "Results per run (in time order)", "B24", "col", True, all_colors)
    chart("top", "Top failing cases", "K24", "bar", colors=[COLOR["failed"]])
    chart("marker", "Pass rate % by marker", "B40", "col", colors=["2F5BEA"])

    # "Setups used" table (bottom right of the dashboard)
    ws["K40"] = "Setups used"
    ws["K40"].font = Font(size=12, bold=True, color="1F3864")
    st = df.groupby(["Setup IP", "SUT"]).agg(N=("Case ID", "size"), P=("Is Pass", "sum")).reset_index()
    for j, h in enumerate(["Setup IP", "SUT", "Executions", "Pass %"]):
        c = ws.cell(row=41, column=11 + j * 2, value=h)
        c.font, c.border = Font(bold=True, color="FFFFFF"), BORDER
        c.fill = PatternFill("solid", start_color="1F3864", end_color="1F3864")
        ws.merge_cells(start_row=41, start_column=11 + j * 2, end_row=41, end_column=12 + j * 2)
    for i, r in st.iterrows():
        for j, v in enumerate([r["Setup IP"], r["SUT"], int(r["N"]), "%.1f%%" % (r["P"] * 100.0 / r["N"])]):
            ws.cell(row=42 + i, column=11 + j * 2, value=v)
            ws.merge_cells(start_row=42 + i, start_column=11 + j * 2, end_row=42 + i, end_column=12 + j * 2)
            for cc in (11 + j * 2, 12 + j * 2):
                ws.cell(row=42 + i, column=cc).border = BORDER


# ================================================================== main
def main():
    ap = argparse.ArgumentParser(description="Regression log folder -> regression_report.html + summary_report.xlsx")
    ap.add_argument("folder")
    ap.add_argument("-o", "--output-dir", help="default: the input folder")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    folder = Path(args.folder)
    out = Path(args.output_dir or folder)

    summary = load_json(folder / "regression_test_summary.json")
    details = details_by_case(load_json(folder / "regression_test_details.json"))
    recs, zips = build_records(folder, details, {})       # NAN stays NAN (summary is not per run)
    if not recs:
        log.error("No commontp_testreport_*.log files found in %s", folder)
        return 2
    runs = build_runs(summary, recs)
    recs = [r for run in runs for r in run["records"]]
    counts = Counter(r["status"] for r in recs)

    render("regression.html", out / "regression_report.html", title="Regression Report",
           subtitle=str(folder.resolve()), counts=counts, total=len(recs), pie=pie_segments(counts, len(recs)),
           runs=runs, cases=group_cases(recs), zips=zips, labels={x["key"]: fmt_ts(x["ts"]) for x in runs})

    df = flat_frame(runs)
    names = {r["case_id"]: r["name"] for r in recs}
    with pd.ExcelWriter(str(out / "summary_report.xlsx"), engine="openpyxl") as xw:
        sheet_test_details(xw, df, details, names)
        sheet_execution_order(xw.book, runs, names)
        sheet_history(xw.book, runs)
        sheet_data(xw, df)
        sheet_dashboard(xw, df, folder)
        wb = xw.book
        for i, name in enumerate(["Dashboard", "Test Details", "Execution Order", "Execution History", "Data", "Dashboard Data"]):
            wb.move_sheet(name, offset=i - wb.sheetnames.index(name))
        wb.active = 0
    log.info("Wrote %s", out / "summary_report.xlsx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
