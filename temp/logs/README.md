# Test Report Generator — User Guide

Turn a folder of CommonTP test logs into a single, self-contained, searchable
HTML report. Regression folders also produce an Excel summary workbook.

| You have...                                   | Run                       | You get                                 |
|-----------------------------------------------|---------------------------|-----------------------------------------|
| One suite execution on one setup              | `suite_report.py`         | `report.html`                           |
| A regression (many runs on many setups)       | `regression_report.py`    | `regression_report.html` + `summary_report.xlsx` |

---

## 1. Setup (one time)

Requires Python 3.8 or newer.

```bash
pip install jinja2                    # suite report
pip install jinja2 pandas openpyxl    # regression report (adds Excel)
```

Keep this layout — the scripts look for a `templates` folder next to them:

```
suite_report.py
regression_report.py
common.py
templates/
    suite.html  regression.html  macros.html  style.css  app.js
```

## 2. What your input folder must contain

**Suite folder** (e.g. `03-06-2026_19-59-42`)
- `commontp_testreport_*.log` (and/or `.zip`) files
- `test_summary.json`
- `test_details.json`

**Regression folder**
- `commontp_testreport_*.log` (and/or `.zip`) files
- `regression_test_summary.json`
- `regression_test_details.json`

Log files must be named exactly like this:

```
commontp_testreport_<status>_<sut_xx_yy>_<test name>_<Cxxxxxx>.log
e.g. commontp_testreport_failed_sut_87_70_identify_ctrl_C123456.log
```

- `status` is one of: passed, failed, error, pending, skipped, nan
- `Cxxxxxx` is the case id: the letter C plus 4 to 8 digits
- Files with a different name are skipped (a warning is printed)

## 3. Generating a report

```bash
# Single suite
python suite_report.py /path/to/03-06-2026_19-59-42

# Regression
python regression_report.py /path/to/regression_folder

# Write the output somewhere else
python suite_report.py /path/to/folder -o /path/to/output
```

By default the output is written into the input folder. Exit code `0` means
success; `2` means no valid log file was found.

## 4. Reading the HTML report

Open the file in any browser. It works offline and follows your light/dark mode.

**Dashboard (stays at the top while you scroll)**
- Cards: total executions, count per status, pass rate
- Donut chart of the status split (hover for numbers)
- Filter buttons by status, a search box, and Expand all / Collapse all

**Search** matches case id, test name, setup IP and markers.

**Case cards** are colour-coded by the worst status of the case
(failed > error > pending > NAN > skipped > passed). Each card shows the
status, case id, name, markers and run duration, then dropdown sections:

| Section          | Content                                              |
|------------------|------------------------------------------------------|
| Header Metadata  | Header fields of the log, log path, test file, function |
| Failure Reason   | The failure block (opens automatically on fail/error) |
| Compilation Log  | Compiler output, if the log has any                  |
| Execution Log    | Test output; RUN / OK / FAILED lines are coloured    |

**Regression report extras**
- *Runs* table: one row per suite execution on one setup, with pass %
- *Case x Setup matrix*: click a case id to jump to its card
- Passed runs hide their logs behind "Show raw logs"; failed/error runs open

## 5. Excel workbook (regression only)

`summary_report.xlsx` sheets: Dashboard, Test Details, Execution Order,
Execution History, Data, Dashboard Data. Each case gets a verdict:

| Verdict                 | Meaning                              |
|-------------------------|--------------------------------------|
| Stable pass             | Passed in every execution            |
| Consistent fail         | Failed/errored in every execution    |
| Flaky / setup-dependent | Both passed and failed               |
| Other / Not executed    | Only pending, skipped, NAN, or none  |

## 6. Good to know

- **Long logs are trimmed.** Passed suite logs keep 1000 lines and others 5000
  (first and last half); the full text stays in the original `.log`.
- **Regression keeps HTML light.** Only failed/error runs embed logs; others
  link to the original file (`file://`), so the report works best on the
  machine or share that holds the logs.
- **ZIP files are not opened.** A note is shown instead; details come from the
  JSON files. Zips with non-standard names are listed at the bottom.
- **NAN status** is resolved from `test_summary.json` in a suite report. In a
  regression it stays NAN.
- **Duration** comes only from the details JSON.
- **Setup IP** is read from the log header (`SUT: host[sut_87_70][14.31.122.34]`).
  If missing, the `sut_xx_yy` id is shown.

## 7. Troubleshooting

| Problem                           | Fix                                              |
|-----------------------------------|--------------------------------------------------|
| `No commontp_testreport_*.log...` | Check the folder path and file names (section 2) |
| `TemplateNotFound`                | Keep `templates/` next to the scripts            |
| `ModuleNotFoundError`             | Run the `pip install` line from section 1        |
| Duration shows `-`                | Case missing from the details JSON               |
| Case missing from run order       | It is not in `execution_order`; sorted to the end |
| Log link does not open            | Original log moved or on an unreachable drive    |
