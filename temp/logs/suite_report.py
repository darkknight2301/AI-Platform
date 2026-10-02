#!/usr/bin/env python3
"""
@Author         : Vedang D
@Description    : Input type 1 (one suite execution folder) -> report.html
@Input          : folder -> folder with commontp_testreport_*.log, test_summary.json and test_details.json
                : -o / --output-dir -> where to write report.html (default: the input folder)
@Returns        : exit code 0 on success, 2 when no valid log file is found
@Note           : usage   python suite_report.py /path/to/03-06-2026_19-59-42
                  needs   jinja2
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from common import (
    NOT_IN_ORDER,
    Record,
    build_records,
    case_id_of,
    details_by_case,
    group_cases,
    load_json,
    log,
    parse_timestamp,
    pie_segments,
    render,
    summary_statuses,
)

# Passed cases are healthy, so their log blocks are cut to this many lines (first and last half are kept).
# Every other status keeps the default cap (MAX_LOG_LINES).
PASSED_MAX_LOG_LINES = 1000


def execution_ranks(summary: Dict) -> Tuple[str, Dict[str, int]]:
    """
    @Author         : Vedang D
    @Description    : Read the single execution_order entry of test_summary.json.
    @Input          : summary -> parsed test_summary.json
    @Returns        : (entry key 'sut_xx_yy_DD-mm-YYYY_HH-MM-SS' or '', {case id: position in the order})
    @Note           : a suite JSON has one entry; if it has several, only the first is used
    """
    execution_order = summary.get("execution_order") or {}
    run_key = next(iter(execution_order), "")
    ranks = {}
    for position, item in enumerate(execution_order.get(run_key) or []):
        ranks.setdefault(case_id_of(item), position)
    return run_key, ranks


def sort_by_execution(records: List[Record], ranks: Dict[str, int]) -> None:
    """
    @Author         : Vedang D
    @Description    : Sort the records in place: execution_order first, then the log timestamp.
    @Input          : records -> records to sort
                    : ranks -> {case id: position} from execution_ranks()
    @Returns        : None
    @Note           : cases missing from execution_order go to the end
    """
    records.sort(
        key=lambda record: (
            ranks.get(record["case_id"], NOT_IN_ORDER),
            parse_timestamp(record["timestamp_raw"]) or datetime.min,
        )
    )


def main() -> int:
    """
    @Author         : Vedang D
    @Description    : Read the suite JSON files and logs and write report.html.
    @Input          : command line arguments (see the module docstring)
    @Returns        : 0 on success, 2 when the folder has no valid log file
    @Note           : status NAN is resolved from test_summary.json when the case is listed there;
                      passed cases embed at most PASSED_MAX_LOG_LINES lines per log block
    """
    parser = argparse.ArgumentParser(description="Single-suite log folder -> report.html")
    parser.add_argument("folder")
    parser.add_argument("-o", "--output-dir", help="default: the input folder")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    folder = Path(args.folder)

    summary = load_json(folder / "test_summary.json")
    details = details_by_case(load_json(folder / "test_details.json"))
    log_limits = {"passed": PASSED_MAX_LOG_LINES}
    records, zip_names = build_records(folder, details, summary_statuses(summary), log_limits)
    if not records:
        log.error("No commontp_testreport_*.log files found in %s", folder)
        return 2

    run_key, ranks = execution_ranks(summary)
    sort_by_execution(records, ranks)
    counts: Dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1

    render(
        "suite.html",
        Path(args.output_dir or folder) / "report.html",
        title="Test Execution Report",
        subtitle="%s | execution: %s" % (folder.resolve(), run_key or "n/a"),
        counts=counts,
        total=len(records),
        pie=pie_segments(counts, len(records)),
        cases=group_cases(records),
        zips=zip_names,
        total_duration=sum(record["duration_sec"] or 0 for record in records),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())