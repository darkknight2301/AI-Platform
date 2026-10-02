#!/usr/bin/env python3
"""Input type 1 (single suite folder) -> report.html

Usage:  python suite_report.py /path/to/03-06-2026_19-59-42 [-o OUTPUT_DIR]
Needs:  jinja2
"""
import argparse
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from common import (build_records, case_id_of, details_by_case, group_cases, load_json, log,
                    parse_ts, pie_segments, render, summary_statuses)


def main():
    """Parse arguments, read the suite JSON + logs, order the cases by execution_order and write report.html."""
    ap = argparse.ArgumentParser(description="Single-suite log folder -> report.html")
    ap.add_argument("folder")
    ap.add_argument("-o", "--output-dir", help="default: the input folder")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    folder = Path(args.folder)

    summary = load_json(folder / "test_summary.json")
    details = details_by_case(load_json(folder / "test_details.json"))
    recs, zips = build_records(folder, details, summary_statuses(summary))
    if not recs:
        log.error("No commontp_testreport_*.log files found in %s", folder)
        return 2

    # Order of execution = the single execution_order entry (sut_xx_yy_DD-mm-YYYY_HH-MM-SS)
    order = summary.get("execution_order") or {}
    run_key = next(iter(order), "")
    rank = {case_id_of(c): i for i, c in enumerate(order.get(run_key) or [])}
    recs.sort(key=lambda r: (rank.get(r["case_id"], 10 ** 9), parse_ts(r["ts_raw"]) or datetime.min))

    counts = Counter(r["status"] for r in recs)
    render("suite.html", Path(args.output_dir or folder) / "report.html",
           title="Test Execution Report", subtitle="%s | execution: %s" % (folder.resolve(), run_key or "n/a"),
           counts=counts, total=len(recs), pie=pie_segments(counts, len(recs)),
           cases=group_cases(recs), zips=zips, total_duration=sum(r["duration"] or 0 for r in recs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
