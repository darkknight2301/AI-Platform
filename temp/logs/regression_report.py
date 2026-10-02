#!/usr/bin/env python3
"""
@Author         : Vedang D
@Description    : Input type 2 (regression folder, many suite runs on many setups)
                  -> regression_report.html + summary_report.xlsx
@Input          : folder -> folder with commontp_testreport_*.log (and .zip), regression_test_summary.json and
                            regression_test_details.json
                : -o / --output-dir -> where to write the reports (default: the input folder)
@Returns        : exit code 0 on success, 2 when no valid log file is found
@Note           : usage   python regression_report.py /path/to/regression_folder
                  needs   jinja2, pandas, openpyxl
                  Run matching: a log belongs to the execution_order key  <sut_xx_yy>_<Timestamp of its header>.
                  A .zip has no header, so it falls back to "same SUT whose execution_order lists the case".
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, TypedDict

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.marker import DataPoint
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from common import (
    NOT_IN_ORDER,
    RUN_KEY_RE,
    STATUS_COLOR,
    STATUS_LABEL,
    STATUSES,
    Record,
    build_records,
    case_id_of,
    details_by_case,
    format_timestamp,
    group_cases,
    load_json,
    log,
    parse_markers,
    parse_timestamp,
    pie_segments,
    render,
    to_float,
)

SOFT_COLORS = {
    "Passed": "C6EFCE",
    "Failed": "FFC7CE",
    "Error": "FFD8A8",
    "Pending": "FFEB9C",
    "Skipped": "E7E6E6",
    "NAN": "D9D9D9",
    "No log": "F2F2F2",
}
VERDICT_COLORS = {"Stable pass": "C6EFCE", "Consistent fail": "FFC7CE", "Flaky / setup-dependent": "FFEB9C"}
BORDER = Border(*[Side(style="thin", color="999999")] * 4)
HEADER_FILL = PatternFill("solid", start_color="1F3864", end_color="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF")
LINK_FONT = Font(color="0563C1", underline="single")
FORMULA_PREFIXES = ("=", "+", "-", "@")  # Excel would run text starting with these as a formula
# Only failed / error runs embed their logs; for these statuses the HTML keeps the header and links to the .log.
LINK_ONLY_LOG_LIMITS = {"passed": 0, "skipped": 0, "nan": 0, "pending": 0}
SHEET_ORDER = ["Dashboard", "Test Details", "Execution Order", "Execution History", "Data", "Dashboard Data"]


class Run(TypedDict):
    """One suite execution on one setup = one execution_order key."""

    key: str  # sut_xx_yy_DD-mm-YYYY_HH-MM-SS
    sut_id: str
    setup_ip: str
    start_time: Optional[datetime]
    case_order: List[str]  # case ids in execution order
    records: List[Record]
    counts: Dict[str, int]
    label: str  # '<ip> @ <start time>', unique per run


class TablePosition(NamedTuple):
    """Where a table was written on the 'Dashboard Data' sheet (first_col is 0-based, like pandas startcol)."""

    first_col: int
    row_count: int
    col_count: int


# ================================================================== runs
def new_run(key: str, sut_id: str, setup_ip: str, start_time: Optional[datetime], case_order: List[str]) -> Run:
    """
    @Author         : Vedang D
    @Description    : Create an empty run.
    @Input          : key -> execution_order key
                    : sut_id -> 'sut_xx_yy'
                    : setup_ip -> IP of the setup (or the sut id when unknown)
                    : start_time -> start time taken from the key
                    : case_order -> case ids in execution order
    @Returns        : Run with no records yet
    @Note           : counts and label are filled in by build_runs() once all records are assigned
    """
    return Run(
        key=key,
        sut_id=sut_id,
        setup_ip=setup_ip,
        start_time=start_time,
        case_order=case_order,
        records=[],
        counts={},
        label="",
    )


def match_run(record: Record, runs: Dict[str, Run]) -> Optional[Run]:
    """
    @Author         : Vedang D
    @Description    : Find the run (execution_order key) a record belongs to.
    @Input          : record -> one log / zip record
                    : runs -> {execution_order key: Run}
    @Returns        : the matching Run, or None if no run lists this SUT and case
    @Note           : 1) exact key '<sut>_<header Timestamp>'; 2) fallback for zips: a run of the same SUT that lists
                      the case, preferring one that has no record of this case yet
    """
    exact = runs.get("%s_%s" % (record["sut_id"], record["timestamp_raw"]))
    if exact:
        return exact
    candidates = [
        run for run in runs.values() if run["sut_id"] == record["sut_id"] and record["case_id"] in run["case_order"]
    ]
    unused = [run for run in candidates if all(r["case_id"] != record["case_id"] for r in run["records"])]
    return (unused or candidates or [None])[0]


def build_runs(summary: Dict[str, Any], records: List[Record]) -> List[Run]:
    """
    @Author         : Vedang D
    @Description    : Build the runs from execution_order and assign every record to its run.
    @Input          : summary -> parsed regression_test_summary.json
                    : records -> all records of the folder
    @Returns        : runs sorted by start time; each run's records are in execution order
    @Note           : sets record['run_key'] and record['order_index']; a record that matches no key gets its own run
    """
    ip_by_sut = {record["sut_id"]: record["setup_ip"] for record in records}
    runs: Dict[str, Run] = {}
    for key, items in (summary.get("execution_order") or {}).items():
        key_match = RUN_KEY_RE.match(key)
        if not key_match:
            log.warning("Unrecognised execution_order key: %s", key)
            continue
        sut_id = key_match.group(1)
        case_order = [case_id for case_id in map(case_id_of, items or []) if case_id]
        setup_ip = ip_by_sut.get(sut_id, sut_id)
        runs[key] = new_run(key, sut_id, setup_ip, parse_timestamp(key_match.group(2)), case_order)

    for record in records:
        run = match_run(record, runs)
        if run is None:
            log.warning("%s is not in any execution_order entry", record["log_file_name"])
            key = "%s_%s" % (record["sut_id"], record["timestamp_raw"] or "no-timestamp")
            start = parse_timestamp(record["timestamp_raw"])
            run = runs.setdefault(key, new_run(key, record["sut_id"], record["setup_ip"], start, []))
        record["run_key"] = run["key"]
        if record["case_id"] in run["case_order"]:
            record["order_index"] = run["case_order"].index(record["case_id"])
        run["records"].append(record)

    ordered = sorted(runs.values(), key=lambda run: (run["start_time"] is None, run["start_time"], run["key"]))
    for run in ordered:
        run["records"].sort(key=lambda record: record["order_index"])
        for record in run["records"]:
            run["counts"][record["status"]] = run["counts"].get(record["status"], 0) + 1
        run["label"] = "%s @ %s" % (run["setup_ip"], format_timestamp(run["start_time"]))
    return ordered


# ================================================================== Excel helpers
def neutralize_formula(value: Any) -> Any:
    """
    @Author         : Vedang D
    @Description    : Stop text coming from logs / JSON from being executed as an Excel formula.
    @Input          : value -> any cell value
    @Returns        : the value; a string starting with = + - @ gets a leading apostrophe
    @Note           : protects against formula injection (a header value such as '=HYPERLINK(...)')
    """
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def neutralize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """
    @Author         : Vedang D
    @Description    : Apply neutralize_formula() to every text column of a DataFrame.
    @Input          : frame -> DataFrame that will be written to Excel
    @Returns        : the same DataFrame (modified in place)
    @Note           : numeric and date columns are not touched
    """
    for column in frame.columns:
        if pd.api.types.is_string_dtype(frame[column]):
            frame[column] = frame[column].map(neutralize_formula)
    return frame


def solid_fill(color: str) -> PatternFill:
    """
    @Author         : Vedang D
    @Description    : Create a solid cell fill.
    @Input          : color -> hex colour without '#', e.g. 'C6EFCE'
    @Returns        : PatternFill
    @Note           : -
    """
    return PatternFill("solid", start_color=color, end_color=color)


def autofit_columns(sheet: Worksheet, max_width: int = 60) -> None:
    """
    @Author         : Vedang D
    @Description    : Set every column width to its longest cell text.
    @Input          : sheet -> worksheet
                    : max_width -> upper limit of a column width
    @Returns        : None
    @Note           : for multi-line cells the longest line counts
    """
    widths: Dict[int, int] = {}
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value is not None:
                longest = max(len(line) for line in str(cell.value).split("\n"))
                widths[cell.column] = max(widths.get(cell.column, 0), longest)
    for column, width in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = min(max(width + 2, 9), max_width)


def add_color_rules(sheet: Worksheet, cell_range: str, colors: Dict[str, str]) -> None:
    """
    @Author         : Vedang D
    @Description    : Add conditional formatting: a cell equal to a text gets that text's soft colour.
    @Input          : sheet -> worksheet
                    : cell_range -> e.g. 'F2:F40'
                    : colors -> {cell text: hex colour}
    @Returns        : None
    @Note           : -
    """
    for text, color in colors.items():
        rule = CellIsRule(operator="equal", formula=['"%s"' % text], fill=solid_fill(color))
        sheet.conditional_formatting.add(cell_range, rule)


def make_excel_table(sheet: Worksheet, table_name: str) -> None:
    """
    @Author         : Vedang D
    @Description    : Turn the used range of a sheet into a named Excel Table and freeze the header row.
    @Input          : sheet -> worksheet whose first row holds the headers
                    : table_name -> Excel table name (no spaces)
    @Returns        : None
    @Note           : a real Table can be picked directly as the source of an Excel PivotTable
    """
    if sheet.max_row > 1:  # a table needs at least one data row
        reference = "A1:%s%d" % (get_column_letter(sheet.max_column), sheet.max_row)
        table = Table(displayName=table_name, ref=reference)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        sheet.add_table(table)
    sheet.freeze_panes = "A2"


def set_file_link(cell: Any, path: str) -> None:
    """
    @Author         : Vedang D
    @Description    : Make a cell a clickable link to a local file.
    @Input          : cell -> openpyxl cell
                    : path -> absolute file path
    @Returns        : None
    @Note           : -
    """
    cell.hyperlink = Path(path).as_uri()
    cell.font = LINK_FONT


def write_header_row(sheet: Worksheet, row: int, headers: List[str], start_col: int = 1, col_span: int = 1) -> None:
    """
    @Author         : Vedang D
    @Description    : Write a dark-blue bordered header row.
    @Input          : sheet -> worksheet
                    : row -> row number
                    : headers -> header texts
                    : start_col -> first column number
                    : col_span -> columns per header; values > 1 merge that many cells per header
    @Returns        : None
    @Note           : -
    """
    for index, header in enumerate(headers):
        column = start_col + index * col_span
        cell = sheet.cell(row=row, column=column, value=header)
        cell.font, cell.border, cell.fill = HEADER_FONT, BORDER, HEADER_FILL
        if col_span > 1:
            sheet.merge_cells(start_row=row, start_column=column, end_row=row, end_column=column + col_span - 1)


# ================================================================== Excel sheets
def build_executions_frame(runs: List[Run]) -> pd.DataFrame:
    """
    @Author         : Vedang D
    @Description    : Build the flat 'fact table' with one row per execution (the best source for PivotTables).
    @Input          : runs -> runs with their records
    @Returns        : DataFrame; text columns are already protected against formula injection
    @Note           : 'Execution Order' is 1-based and empty for cases missing from execution_order
    """
    rows = []
    for run in runs:
        for record in run["records"]:
            header = record["header"]
            in_order = record["order_index"] < NOT_IN_ORDER
            rows.append(
                {
                    "Run": run["label"],
                    "Run ID": run["key"],
                    "Run Start": run["start_time"],
                    "Execution Order": record["order_index"] + 1 if in_order else None,
                    "Case ID": record["case_id"],
                    "Test Name": record["test_name"],
                    "Status": STATUS_LABEL[record["status"]],
                    "Is Pass": int(record["status"] == "passed"),
                    "Is Fail": int(record["status"] in ("failed", "error")),
                    "SUT": record["sut_id"],
                    "Setup IP": record["setup_ip"],
                    "Duration (s)": record["duration_sec"],
                    "Markers": ", ".join(record["markers"]),
                    "Product": header.get("Product", ""),
                    "OS": header.get("OS", ""),
                    "Firmware Version": header.get("Firmware Version", ""),
                    "Git Branch": header.get("Git Branch Info", ""),
                    "Drive Capacity": header.get("Drive Capacity", ""),
                    "Test File Path": record["test_file_path"],
                    "Function Name": record["function_name"],
                    "Log File": record["log_path"],
                }
            )
    return neutralize_frame(pd.DataFrame(rows))


def case_verdict(total: int, passed: int, failed: int) -> str:
    """
    @Author         : Vedang D
    @Description    : Summarise all executions of one case in one word group.
    @Input          : total -> number of executions
                    : passed -> number of passed executions
                    : failed -> number of failed + error executions
    @Returns        : 'Not executed', 'Stable pass', 'Consistent fail', 'Flaky / setup-dependent' or 'Other'
    @Note           : 'Other' means no pass or fail mix, e.g. only pending / skipped / NAN
    """
    if total == 0:
        return "Not executed"
    if passed == total:
        return "Stable pass"
    if failed == total:
        return "Consistent fail"
    return "Flaky / setup-dependent" if passed and failed else "Other"


def sheet_test_details(
    writer: pd.ExcelWriter, frame: pd.DataFrame, details: Dict[str, Dict[str, Any]], names: Dict[str, str]
) -> None:
    """
    @Author         : Vedang D
    @Description    : Write sheet 'Test Details': regression_test_details.json plus setups and counts per case.
    @Input          : writer -> open pandas ExcelWriter
                    : frame -> executions frame
                    : details -> regression_test_details.json keyed by case id
                    : names -> {case id: test name}
    @Returns        : None
    @Note           : cases that only appear in the details JSON are listed too (verdict 'Not executed')
    """
    rows = []
    for case_id in sorted(set(details) | set(frame["Case ID"])):
        case_details = details.get(case_id, {})
        runs_of_case = frame[frame["Case ID"] == case_id]
        passed, failed = int(runs_of_case["Is Pass"].sum()), int(runs_of_case["Is Fail"].sum())
        rows.append(
            {
                "Case ID": case_id,
                "Test Name": names.get(case_id, ""),
                "Duration (s)": to_float(case_details.get("duration")),
                "Markers": ", ".join(parse_markers(case_details.get("markers"))),
                "Test File Path": case_details.get("file_path", ""),
                "Function Name": case_details.get("function_name", ""),
                "Executions": len(runs_of_case),
                "Passed": passed,
                "Failed / Error": failed,
                "Setup Count": runs_of_case["SUT"].nunique(),
                "Setups (IP)": ", ".join(sorted(runs_of_case["Setup IP"].unique())),
                "Verdict": case_verdict(len(runs_of_case), passed, failed),
            }
        )
    neutralize_frame(pd.DataFrame(rows)).to_excel(writer, sheet_name="Test Details", index=False)
    sheet = writer.sheets["Test Details"]
    make_excel_table(sheet, "tblTestDetails")
    verdict_column = get_column_letter(sheet.max_column)  # 'Verdict' is the last column
    add_color_rules(sheet, "%s2:%s%d" % (verdict_column, verdict_column, sheet.max_row), VERDICT_COLORS)
    autofit_columns(sheet)


def sheet_execution_order(workbook: Workbook, runs: List[Run], names: Dict[str, str]) -> None:
    """
    @Author         : Vedang D
    @Description    : Write sheet 'Execution Order': one bordered table per run, cases in execution order with log link.
    @Input          : workbook -> openpyxl workbook
                    : runs -> runs with their records
                    : names -> {case id: test name}, used for cases that have no log file
    @Returns        : None
    @Note           : a case listed in execution_order but without a log shows status 'No log'
    """
    sheet = workbook.create_sheet("Execution Order")
    row = 1
    for number, run in enumerate(runs, 1):
        start = format_timestamp(run["start_time"])
        title = "Run %d  |  %s  |  %s  |  %s" % (number, run["setup_ip"], start, run["key"])
        sheet.cell(row=row, column=1, value=neutralize_formula(title)).font = Font(bold=True, size=12, color="1F3864")
        row += 1
        write_header_row(sheet, row, ["#", "Case ID", "Test Name", "Status", "Duration (s)", "Log File"])

        items: List[Any] = []  # a Record, or a plain case id when the log is missing
        for case_id in run["case_order"]:
            items += [r for r in run["records"] if r["case_id"] == case_id] or [case_id]
        items += [r for r in run["records"] if r["case_id"] not in run["case_order"]]
        for position, item in enumerate(items, 1):
            row += 1
            if isinstance(item, str):
                values = [position, item, names.get(item, ""), "No log", None, ""]
            else:
                values = [position, item["case_id"], item["test_name"], STATUS_LABEL[item["status"]]]
                values += [item["duration_sec"], item["log_path"]]
            for column, value in enumerate(values, 1):
                cell = sheet.cell(row=row, column=column, value=neutralize_formula(value))
                cell.border = BORDER
                if column == 6 and value:
                    set_file_link(cell, value)
        row += 3  # blank rows between the run tables
    add_color_rules(sheet, "D1:D%d" % row, SOFT_COLORS)
    for column, width in zip("ABCDEF", (6, 14, 42, 12, 14, 80)):
        sheet.column_dimensions[column].width = width


def history_text(attempts: List[Tuple[str, str]]) -> str:
    """
    @Author         : Vedang D
    @Description    : Describe the executions of one case in time order, merging neighbours with the same status.
    @Input          : attempts -> [(status, setup ip), ...] sorted by time
    @Returns        : e.g. 'Failed x2 (ip1, ip2) -> Skipped x1 (ip3) -> Passed x1 (ip4)' (arrow is a real arrow sign)
    @Note           : alternating statuses stay separate: fail, pass, fail gives three groups
    """
    groups: List[Tuple[str, List[str]]] = []
    for status, setup_ip in attempts:
        if groups and groups[-1][0] == status:
            groups[-1][1].append(setup_ip)
        else:
            groups.append((status, [setup_ip]))
    parts = ["%s x%d (%s)" % (STATUS_LABEL[status], len(ips), ", ".join(ips)) for status, ips in groups]
    return " \u2192 ".join(parts)


def sheet_history(workbook: Workbook, runs: List[Run]) -> None:
    """
    @Author         : Vedang D
    @Description    : Write sheet 'Execution History': every execution of every case sorted by time.
    @Input          : workbook -> openpyxl workbook
                    : runs -> runs with their records
    @Returns        : None
    @Note           : Case ID, name and conclusion are merged over the rows of a case; status, setup IP and log file
                      stay one per row. The timestamp is the log header time (run start time for a zip).
    """
    sheet = workbook.create_sheet("Execution History")
    headers = ["Case ID", "Test Name", "Conclusion (time order)", "#", "Timestamp"]
    headers += ["Status", "Setup IP", "Log File Name"]
    write_header_row(sheet, 1, headers)

    attempts_by_case: Dict[str, List[Tuple[Any, ...]]] = {}
    for run_number, run in enumerate(runs):
        for record in run["records"]:
            when = parse_timestamp(record["timestamp_raw"]) or run["start_time"]
            attempts_by_case.setdefault(record["case_id"], []).append((when, run_number, record["order_index"], record))

    row = 2
    for case_id in sorted(attempts_by_case):
        # oldest first; undated attempts last; ties broken by run number, then execution order
        attempts = sorted(attempts_by_case[case_id], key=lambda a: (a[0] is None, a[0], a[1], a[2]))
        conclusion = history_text([(a[3]["status"], a[3]["setup_ip"]) for a in attempts])
        first_row = row
        for number, (when, _, _, record) in enumerate(attempts, 1):
            values = [case_id, record["test_name"], conclusion, number, format_timestamp(when)]
            values += [STATUS_LABEL[record["status"]], record["setup_ip"], record["log_file_name"]]
            for column, value in enumerate(values, 1):
                shown = value if (number == 1 or column > 3) else None  # merged columns: value only in the first row
                cell = sheet.cell(row=row, column=column, value=neutralize_formula(shown))
                cell.border = BORDER
                cell.alignment = Alignment(vertical="center", wrap_text=(column == 3))
                if column == 8:
                    set_file_link(cell, record["log_path"])
            row += 1
        if row - first_row > 1:  # merge after the borders are set, so the merged block keeps its border
            for column in (1, 2, 3):
                sheet.merge_cells(start_row=first_row, start_column=column, end_row=row - 1, end_column=column)
    add_color_rules(sheet, "F2:F%d" % max(row, 2), SOFT_COLORS)
    sheet.freeze_panes = "A2"
    for column, width in zip("ABCDEFGH", (14, 26, 70, 5, 20, 11, 18, 70)):
        sheet.column_dimensions[column].width = width


def sheet_data(writer: pd.ExcelWriter, frame: pd.DataFrame) -> None:
    """
    @Author         : Vedang D
    @Description    : Write sheet 'Data': the flat table 'tblExecutions' for PivotTables.
    @Input          : writer -> open pandas ExcelWriter
                    : frame -> executions frame
    @Returns        : None
    @Note           : Excel: Insert > PivotTable > Table/Range = tblExecutions
    """
    frame.to_excel(writer, sheet_name="Data", index=False)
    sheet = writer.sheets["Data"]
    make_excel_table(sheet, "tblExecutions")
    add_color_rules(sheet, "G2:G%d" % sheet.max_row, SOFT_COLORS)  # column G = Status
    for cell in sheet["C"][1:]:  # column C = Run Start
        cell.number_format = "dd-mm-yyyy hh:mm:ss"
    log_column = list(frame.columns).index("Log File") + 1
    for row in range(2, sheet.max_row + 1):
        set_file_link(sheet.cell(row=row, column=log_column), sheet.cell(row=row, column=log_column).value)
    autofit_columns(sheet)


def build_dashboard_tables(frame: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    @Author         : Vedang D
    @Description    : Aggregate the executions into the small tables that feed the dashboard charts.
    @Input          : frame -> executions frame
    @Returns        : {'status', 'setup', 'run', 'top', 'marker'} -> DataFrame (first column = chart category)
    @Note           : 'top' is sorted ascending on purpose, a horizontal bar chart draws the first row at the bottom
    """
    labels = [STATUS_LABEL[status] for status in STATUSES]
    run_order = list(dict.fromkeys(frame["Run"]))  # runs in time order
    by_setup = pd.crosstab(frame["Setup IP"], frame["Status"]).reindex(columns=labels, fill_value=0)
    by_run = pd.crosstab(frame["Run"], frame["Status"]).reindex(index=run_order, columns=labels, fill_value=0)
    for table in (by_setup, by_run):
        table.columns.name = None

    exploded = frame.assign(Marker=frame["Markers"].str.split(",")).explode("Marker")  # one row per marker
    exploded["Marker"] = exploded["Marker"].fillna("").str.strip()
    by_marker = exploded[exploded["Marker"] != ""].groupby("Marker").agg(N=("Case ID", "size"), P=("Is Pass", "sum"))
    by_marker = by_marker.reset_index()
    by_marker["Pass %"] = (by_marker["P"] * 100.0 / by_marker["N"]).round(1)

    failing = frame[frame["Is Fail"] == 1].groupby("Case ID").size().sort_values(ascending=False).head(10)
    return {
        "status": pd.DataFrame({"Status": labels, "Count": [int((frame["Status"] == s).sum()) for s in labels]}),
        "setup": by_setup.reset_index(),
        "run": by_run.reset_index(),
        "top": failing.iloc[::-1].reset_index(name="Failed / Error runs"),
        "marker": by_marker[["Marker", "Pass %"]],
    }


def write_kpi_tiles(sheet: Worksheet, frame: pd.DataFrame) -> None:
    """
    @Author         : Vedang D
    @Description    : Draw the six KPI tiles (label row + big value) at the top of the dashboard.
    @Input          : sheet -> dashboard worksheet
                    : frame -> executions frame
    @Returns        : None
    @Note           : 'Flaky cases' = cases with at least one pass AND at least one fail / error
    """
    per_case = frame.groupby("Case ID")[["Is Pass", "Is Fail"]].sum()
    flaky = int(((per_case["Is Pass"] > 0) & (per_case["Is Fail"] > 0)).sum())
    pass_rate = frame["Is Pass"].sum() * 100.0 / len(frame)
    tiles = [
        ("Executions", len(frame), "DDEBF7"),
        ("Unique cases", int(frame["Case ID"].nunique()), "DDEBF7"),
        ("Setups (SUT)", int(frame["SUT"].nunique()), "DDEBF7"),
        ("Pass rate", "%.1f%%" % pass_rate, "C6EFCE"),
        ("Failed / Error", int(frame["Is Fail"].sum()), "FFC7CE"),
        ("Flaky cases", flaky, "FFEB9C"),
    ]
    for index, (label, value, color) in enumerate(tiles):
        first_col = 2 + 3 * index  # every tile is 3 columns wide
        sheet.merge_cells(start_row=4, start_column=first_col, end_row=4, end_column=first_col + 2)
        sheet.merge_cells(start_row=5, start_column=first_col, end_row=6, end_column=first_col + 2)
        sheet.cell(row=4, column=first_col, value=label).font = Font(size=10, color="44546A")
        sheet.cell(row=5, column=first_col, value=value).font = Font(size=22, bold=True, color="1F3864")
        for row in range(4, 7):
            for column in range(first_col, first_col + 3):
                sheet.cell(row=row, column=column).fill = solid_fill(color)
                sheet.cell(row=row, column=column).alignment = Alignment(horizontal="center", vertical="center")


def add_chart(
    sheet: Worksheet,
    data_sheet: Worksheet,
    position: TablePosition,
    title: str,
    anchor: str,
    kind: str,
    colors: List[str],
    stacked: bool = False,
) -> None:
    """
    @Author         : Vedang D
    @Description    : Add one chart that reads a table of 'Dashboard Data' onto the dashboard.
    @Input          : sheet -> dashboard worksheet (where the chart is placed)
                    : data_sheet -> 'Dashboard Data' worksheet (where the numbers are)
                    : position -> location of the source table
                    : title -> chart title
                    : anchor -> top-left cell of the chart, e.g. 'B8'
                    : kind -> 'pie', 'col' (columns) or 'bar' (horizontal bars)
                    : colors -> hex colours, one per pie slice / per series
                    : stacked -> stack the series (col / bar only)
    @Returns        : None
    @Note           : first table column = categories, the other columns = series; an empty table adds no chart
    """
    if position.row_count == 0:
        return
    first_col, last_row = position.first_col + 1, position.row_count + 1  # openpyxl columns are 1-based
    chart = PieChart() if kind == "pie" else BarChart()
    chart.title = title
    if kind != "pie":
        chart.type = kind
        if stacked:
            chart.grouping, chart.overlap = "stacked", 100
    last_col = first_col + position.col_count - 1
    series_data = Reference(data_sheet, min_col=first_col + 1, max_col=last_col, min_row=1, max_row=last_row)
    chart.add_data(series_data, titles_from_data=True)
    chart.set_categories(Reference(data_sheet, min_col=first_col, min_row=2, max_row=last_row))
    if kind == "pie":
        for index, color in enumerate(colors):
            point = DataPoint(idx=index)
            point.graphicalProperties.solidFill = color
            chart.series[0].dPt.append(point)
    else:
        for series, color in zip(chart.series, colors):
            series.graphicalProperties.solidFill = color
        if position.col_count == 2:  # a single series needs no legend
            chart.legend = None
    chart.width, chart.height = 18.5, 7.5
    sheet.add_chart(chart, anchor)


def write_setups_table(sheet: Worksheet, frame: pd.DataFrame) -> None:
    """
    @Author         : Vedang D
    @Description    : Draw the 'Setups used' table (IP, SUT, executions, pass %) at the bottom right of the dashboard.
    @Input          : sheet -> dashboard worksheet
                    : frame -> executions frame
    @Returns        : None
    @Note           : every value spans 2 merged columns because the dashboard columns are narrow
    """
    sheet["K40"] = "Setups used"
    sheet["K40"].font = Font(size=12, bold=True, color="1F3864")
    write_header_row(sheet, 41, ["Setup IP", "SUT", "Executions", "Pass %"], start_col=11, col_span=2)
    per_setup = frame.groupby(["Setup IP", "SUT"]).agg(N=("Case ID", "size"), P=("Is Pass", "sum")).reset_index()
    for index, setup in per_setup.iterrows():
        row = 42 + index
        pass_percent = "%.1f%%" % (setup["P"] * 100.0 / setup["N"])
        for number, value in enumerate([setup["Setup IP"], setup["SUT"], int(setup["N"]), pass_percent]):
            column = 11 + number * 2
            sheet.cell(row=row, column=column, value=value)
            sheet.merge_cells(start_row=row, start_column=column, end_row=row, end_column=column + 1)
            for border_column in (column, column + 1):
                sheet.cell(row=row, column=border_column).border = BORDER


def sheet_dashboard(writer: pd.ExcelWriter, frame: pd.DataFrame, folder: Path) -> None:
    """
    @Author         : Vedang D
    @Description    : Write the sheets 'Dashboard Data' (chart sources) and 'Dashboard' (KPI tiles, charts, setups).
    @Input          : writer -> open pandas ExcelWriter
                    : frame -> executions frame (must not be empty)
                    : folder -> input folder, shown under the title
    @Returns        : None
    @Note           : the tables are written side by side on 'Dashboard Data', one empty column between them
    """
    positions: Dict[str, TablePosition] = {}
    next_col = 0
    for name, table in build_dashboard_tables(frame).items():
        table.to_excel(writer, sheet_name="Dashboard Data", startcol=next_col, index=False)
        positions[name] = TablePosition(next_col, len(table), table.shape[1])
        next_col += table.shape[1] + 1
    data_sheet = writer.sheets["Dashboard Data"]
    autofit_columns(data_sheet)

    sheet = writer.book.create_sheet("Dashboard")
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 2
    for column in range(2, 21):
        sheet.column_dimensions[get_column_letter(column)].width = 11
    sheet["B1"], sheet["B2"] = "Regression Dashboard", "Source: %s" % Path(folder).resolve()
    sheet["B1"].font, sheet["B2"].font = Font(size=18, bold=True, color="1F3864"), Font(italic=True, color="6B7785")
    write_kpi_tiles(sheet, frame)

    status_colors = [STATUS_COLOR[status] for status in STATUSES]
    add_chart(sheet, data_sheet, positions["status"], "Status distribution", "B8", "pie", status_colors)
    add_chart(sheet, data_sheet, positions["setup"], "Results per setup (IP)", "K8", "col", status_colors, True)
    add_chart(sheet, data_sheet, positions["run"], "Results per run (in time order)", "B24", "col", status_colors, True)
    add_chart(sheet, data_sheet, positions["top"], "Top failing cases", "K24", "bar", [STATUS_COLOR["failed"]])
    add_chart(sheet, data_sheet, positions["marker"], "Pass rate % by marker", "B40", "col", ["2F5BEA"])
    write_setups_table(sheet, frame)


# ================================================================== main
def main() -> int:
    """
    @Author         : Vedang D
    @Description    : Read the regression JSON files and logs, then write the HTML report and the Excel workbook.
    @Input          : command line arguments (see the module docstring)
    @Returns        : 0 on success, 2 when the folder has no valid log file
    @Note           : a log named NAN stays NAN, because the summary lists are not per run;
                      only failed / error runs embed their logs (see LINK_ONLY_LOG_LIMITS)
    """
    description = "Regression log folder -> regression_report.html + summary_report.xlsx"
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("folder")
    parser.add_argument("-o", "--output-dir", help="default: the input folder")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    folder = Path(args.folder)
    out_dir = Path(args.output_dir or folder)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = load_json(folder / "regression_test_summary.json")
    details = details_by_case(load_json(folder / "regression_test_details.json"))
    records, zip_names = build_records(folder, details, {}, LINK_ONLY_LOG_LIMITS)
    if not records:
        log.error("No commontp_testreport_*.log files found in %s", folder)
        return 2
    runs = build_runs(summary, records)
    records = [record for run in runs for record in run["records"]]  # now in run / execution order
    counts: Dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1

    render(
        "regression.html",
        out_dir / "regression_report.html",
        title="Regression Report",
        subtitle=str(folder.resolve()),
        counts=counts,
        total=len(records),
        pie=pie_segments(counts, len(records)),
        runs=runs,
        cases=group_cases(records),
        zips=zip_names,
        labels={run["key"]: format_timestamp(run["start_time"]) for run in runs},
    )

    frame = build_executions_frame(runs)
    names = {record["case_id"]: record["test_name"] for record in records}
    excel_path = out_dir / "summary_report.xlsx"
    with pd.ExcelWriter(str(excel_path), engine="openpyxl") as writer:
        workbook = writer.book
        sheet_test_details(writer, frame, details, names)
        sheet_execution_order(workbook, runs, names)
        sheet_history(workbook, runs)
        sheet_data(writer, frame)
        sheet_dashboard(writer, frame, folder)
        for position, name in enumerate(SHEET_ORDER):
            workbook.move_sheet(name, offset=position - workbook.sheetnames.index(name))
        workbook.active = 0
    log.info("Wrote %s", excel_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())