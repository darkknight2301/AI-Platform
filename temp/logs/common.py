"""
@Author         : Vedang D
@Description    : Shared helpers for suite_report.py and regression_report.py: file-name and log parsing,
                  record building and Jinja HTML rendering. Compatible with Python 3.8.
@Input          : -
@Returns        : -
@Note           : A "record" is one dict per .log / .zip file (see the Record TypedDict below).
"""
import json
import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Match, Optional, Tuple, TypedDict

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape

log = logging.getLogger("log_report")
TEMPLATE_DIR = Path(__file__).parent / "templates"
MAX_LOG_LINES = 5000  # default cap per log block: longer blocks keep only the first / last half in the HTML
NOT_IN_ORDER = 10 ** 9  # sort position of a case that is not listed in execution_order

STATUSES = ["passed", "failed", "error", "pending", "skipped", "nan"]
WORST_FIRST = ["failed", "error", "pending", "nan", "skipped", "passed"]
STATUS_LABEL = {status: status.capitalize() for status in STATUSES}
STATUS_LABEL["nan"] = "NAN"
STATUS_COLOR = {
    "passed": "2E9E5B",
    "failed": "D64545",
    "error": "E08A1E",
    "pending": "D4B106",
    "skipped": "8C959F",
    "nan": "B8C0CC",
}

LOG_NAME_RE = re.compile(
    r"^commontp_testreport_(?P<status>passed|failed|error|pending|skipped|nan)_"
    r"(?P<sut>sut_\d{1,3}_\d{1,3})_(?P<name>.+)_(?P<case>C\d{4,8})\.(?P<ext>log|zip)$",
    re.I,
)
SECTION_RE = re.compile(r"^\*{3,}\s*(Failure|Compilation Log|Execution Log)\s+for\b.*$", re.M | re.I)
RUN_KEY_RE = re.compile(r"^(sut_\d+_\d+)_(\d{2}-\d{2}-\d{4}_\d{2}-\d{2}-\d{2})$")
SUT_IP_RE = re.compile(r"\[(\d{1,3}(?:\.\d{1,3}){3})\]")
CASE_ID_RE = re.compile(r"(?<![A-Za-z0-9])C\d{4,8}(?!\d)")  # whole token only, never part of a longer number
TIMESTAMP_FORMAT = "%d-%m-%Y_%H-%M-%S"


class Record(TypedDict):
    """One execution of one case on one setup (= one .log or .zip file). Templates read these keys."""

    log_path: str
    log_uri: str  # file:// link to the original log (used when the log is not embedded)
    log_file_name: str
    is_zip: bool
    case_id: str
    test_name: str
    status: str
    sut_id: str  # sut_xx_yy
    setup_ip: str  # full IP from the log header, else sut_xx_yy
    header: Dict[str, str]
    failure: Optional[str]
    compilation: Optional[str]
    execution: Optional[Markup]
    log_embedded: bool  # False -> only the header is kept, the HTML links to the original .log
    timestamp_raw: str  # "Timestamp:" value of the header
    duration_sec: Optional[float]
    markers: List[str]
    test_file_path: str
    function_name: str
    run_key: str  # execution_order key this record belongs to (regression only)
    order_index: int  # position of the case inside that run's execution_order


# ------------------------------------------------------------------ small utilities
def load_json(path: Path) -> Dict[str, Any]:
    """
    @Author         : Vedang D
    @Description    : Read a JSON file that must contain an object; never raises.
    @Input          : path -> JSON file path
    @Returns        : the parsed dict, or {} if the file is missing, unreadable or not a JSON object
    @Note           : a warning is logged when the file cannot be read
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as error:
        log.warning("Cannot read %s: %s", Path(path).name, error)
        return {}


def case_id_of(text: Any) -> Optional[str]:
    """
    @Author         : Vedang D
    @Description    : Extract the case id from text such as 'any_prefix::C123456'.
    @Input          : text -> string (or anything printable) that contains a case id
    @Returns        : the last whole-token case id (C + 4 to 8 digits), or None
    @Note           : 'C123456789' (9 digits) is NOT a case id, it is not cut down to 8 digits
    """
    matches = CASE_ID_RE.findall(str(text))
    return matches[-1] if matches else None


def parse_timestamp(text: Optional[str]) -> Optional[datetime]:
    """
    @Author         : Vedang D
    @Description    : Parse a 'DD-mm-YYYY_HH-MM-SS' timestamp.
    @Input          : text -> timestamp text from a log header or an execution_order key
    @Returns        : datetime, or None when the text is empty or in another format
    @Note           : -
    """
    try:
        return datetime.strptime(text.strip(), TIMESTAMP_FORMAT)  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        return None


def to_float(value: Any) -> Optional[float]:
    """
    @Author         : Vedang D
    @Description    : Convert a JSON value (for example a duration in seconds) to float.
    @Input          : value -> number, numeric string or None
    @Returns        : float, or None if the value is missing or not numeric
    @Note           : -
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_markers(raw_markers: Any) -> List[str]:
    """
    @Author         : Vedang D
    @Description    : Turn the 'markers' value of a details JSON into a clean list.
    @Input          : raw_markers -> 'sanity,identify,gen4' (comma separated), a list, or None
    @Returns        : ['sanity', 'identify', 'gen4']; empty entries are dropped
    @Note           : -
    """
    if isinstance(raw_markers, (list, tuple)):
        raw_markers = ",".join(str(marker) for marker in raw_markers)
    return [marker.strip() for marker in str(raw_markers or "").split(",") if marker.strip()]


def header_ip(header: Dict[str, str]) -> Optional[str]:
    """
    @Author         : Vedang D
    @Description    : Read the setup IP from the header line  SUT: host[sut_87_70][14.31.122.34].
    @Input          : header -> parsed log header
    @Returns        : the IP string, or None when the line has no [ip] part
    @Note           : callers fall back to the sut_xx_yy id when this returns None
    """
    match = SUT_IP_RE.search(header.get("SUT", ""))
    return match.group(1) if match else None


def format_timestamp(timestamp: Optional[datetime]) -> str:
    """
    @Author         : Vedang D
    @Description    : Format a datetime for display.
    @Input          : timestamp -> datetime or None
    @Returns        : 'DD-mm-YYYY HH:MM:SS', or 'n/a' when there is no timestamp
    @Note           : -
    """
    return timestamp.strftime("%d-%m-%Y %H:%M:%S") if timestamp else "n/a"


def format_duration(seconds: Optional[float]) -> str:
    """
    @Author         : Vedang D
    @Description    : Format a duration in seconds for display.
    @Input          : seconds -> duration in seconds, None or NaN
    @Returns        : '12.34 s' or '2m 05s'; '-' when the duration is unknown
    @Note           : -
    """
    if seconds is None or math.isnan(seconds):
        return "-"
    if seconds < 60:
        return "%.2f s" % seconds
    return "%dm %02ds" % (seconds // 60, seconds % 60)


def details_by_case(raw_details: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    @Author         : Vedang D
    @Description    : Re-key a test_details JSON by plain case id.
    @Input          : raw_details -> JSON object {"<any>::C123456": {...}, ...}
    @Returns        : {"C123456": {...}}; entries without a case id or without an object value are dropped
    @Note           : -
    """
    result = {}
    for key, value in raw_details.items():
        case_id = case_id_of(key)
        if case_id and isinstance(value, dict):
            result[case_id] = value
    return result


def summary_statuses(summary: Dict[str, Any]) -> Dict[str, str]:
    """
    @Author         : Vedang D
    @Description    : Map case id -> status using the passed / failed / pending / skipped lists of a summary JSON.
    @Input          : summary -> parsed test_summary.json
    @Returns        : {"C123456": "passed", ...}
    @Note           : only meaningful for one suite; it is used to resolve log files named 'NAN'
    """
    result = {}
    for status in ("passed", "failed", "pending", "skipped"):
        for item in summary.get(status) or []:
            case_id = case_id_of(item)
            if case_id:
                result[case_id] = status
    return result


# ------------------------------------------------------------------ log parsing
def parse_header(header_text: str) -> Dict[str, str]:
    """
    @Author         : Vedang D
    @Description    : Parse the 'Key: value' lines of a log header.
    @Input          : header_text -> text before the first Failure / Compilation / Execution block
    @Returns        : {key: value}
    @Note           : blank lines and '*****' separator lines are skipped
    """
    header: Dict[str, str] = {}
    for line in header_text.splitlines():
        line = line.strip()
        if line and set(line) != {"*"} and ":" in line:
            key, value = line.split(":", 1)
            header[key.strip()] = value.strip()
    return header


def parse_log(path: Path, header_only: bool = False) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    @Author         : Vedang D
    @Description    : Split a CommonTP log into its header fields and its Failure / Compilation / Execution blocks.
    @Input          : path -> .log file path
                    : header_only -> True: read only up to the first block and return no sections
    @Returns        : (header, sections); sections keys are 'failure', 'compilation log' and 'execution log'
    @Note           : a block runs from its '*****<name> for <case>*****' line to the next such line;
                      header_only never reads the (large) rest of the file, which keeps big folders fast
    """
    if header_only:
        header_lines = []
        with open(str(path), encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if SECTION_RE.match(line.rstrip("\r\n")):
                    break
                header_lines.append(line)
        return parse_header("".join(header_lines)), {}

    text = Path(path).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    marks = list(SECTION_RE.finditer(text))
    sections: Dict[str, str] = {}
    for index, mark in enumerate(marks):
        block_end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        sections.setdefault(mark.group(1).lower(), text[mark.end() : block_end].strip("\n"))
    return parse_header(text[: marks[0].start()] if marks else text), sections


def clip_lines(text: str, max_lines: int = MAX_LOG_LINES) -> str:
    """
    @Author         : Vedang D
    @Description    : Shorten a very long log block so the HTML stays light.
    @Input          : text -> log block text
                    : max_lines -> most lines to keep
    @Returns        : the text unchanged, or its first and last max_lines/2 lines with an 'omitted' note
    @Note           : the full text is always still available in the original .log file
    """
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    half = max_lines // 2
    omitted = len(lines) - 2 * half
    note = ["", "... %d lines omitted - see the original .log ..." % omitted, ""]
    return "\n".join(lines[:half] + note + lines[-half:])


def highlight_execution_log(text: str, max_lines: int = MAX_LOG_LINES) -> Markup:
    """
    @Author         : Vedang D
    @Description    : HTML-escape an execution log and colour the Google Test RUN / OK / FAILED lines.
    @Input          : text -> execution log block
                    : max_lines -> most lines to keep (see clip_lines)
    @Returns        : Markup (already escaped, safe to print in the template)
    @Note           : every line is escaped BEFORE any tag is added, so log content can never inject HTML
    """
    html_lines = []
    for line in clip_lines(text, max_lines).split("\n"):
        stripped, css_class = line.lstrip(), ""
        if stripped.startswith(("[  FAILED", "[  FAILURE")) or stripped.endswith(": Failure"):
            css_class = "l-fail"
        elif stripped.startswith(("[       OK", "[  PASSED")):
            css_class = "l-ok"
        elif stripped.startswith("[ RUN"):
            css_class = "l-run"
        elif stripped.startswith(("[==", "[--")):
            css_class = "l-dim"
        escaped = escape(line)
        html_lines.append('<span class="%s">%s</span>' % (css_class, escaped) if css_class else str(escaped))
    return Markup("\n".join(html_lines))


def make_record(
    path: Path,
    name_match: Match[str],
    details: Dict[str, Dict[str, Any]],
    summary_status: Dict[str, str],
    log_limits: Dict[str, int],
) -> Record:
    """
    @Author         : Vedang D
    @Description    : Build the record of one .log / .zip file from its file name, the JSON details and the log text.
    @Input          : path -> the .log or .zip file
                    : name_match -> result of LOG_NAME_RE.match(path.name)
                    : details -> test_details JSON keyed by case id
                    : summary_status -> case id -> status, used only when the file name says NAN
                    : log_limits -> {status: most lines per log block}; 0 = do not embed the log, keep only the header
    @Returns        : Record; a .zip is never opened, so its header and log sections stay empty
    @Note           : duration comes ONLY from the details JSON (seconds); statuses missing in log_limits use
                      MAX_LOG_LINES
    """
    case_id = name_match.group("case")
    status = name_match.group("status").lower()
    if status == "nan":
        status = summary_status.get(case_id, "nan")
    case_details = details.get(case_id, {})

    record = Record(
        log_path=str(path.resolve()),
        log_uri=path.resolve().as_uri(),
        log_file_name=path.name,
        is_zip=path.suffix.lower() == ".zip",
        case_id=case_id,
        test_name=name_match.group("name"),
        status=status,
        sut_id=name_match.group("sut").lower(),
        setup_ip="",
        header={},
        failure=None,
        compilation=None,
        execution=None,
        log_embedded=False,
        timestamp_raw="",
        duration_sec=to_float(case_details.get("duration")),
        markers=parse_markers(case_details.get("markers")),
        test_file_path=str(case_details.get("file_path") or ""),
        function_name=str(case_details.get("function_name") or ""),
        run_key="",
        order_index=NOT_IN_ORDER,
    )
    if not record["is_zip"]:
        max_lines = log_limits.get(status, MAX_LOG_LINES)
        header, sections = parse_log(path, header_only=(max_lines == 0))
        record["header"] = header
        record["timestamp_raw"] = header.get("Timestamp", "")
        record["log_embedded"] = max_lines > 0
        if "failure" in sections:
            record["failure"] = clip_lines(sections["failure"], max_lines)
        if sections.get("compilation log"):
            record["compilation"] = clip_lines(sections["compilation log"], max_lines)
        if sections.get("execution log"):
            record["execution"] = highlight_execution_log(sections["execution log"], max_lines)
    return record


def build_records(
    folder: Path,
    details: Dict[str, Dict[str, Any]],
    summary_status: Dict[str, str],
    log_limits: Optional[Dict[str, int]] = None,
) -> Tuple[List[Record], List[str]]:
    """
    @Author         : Vedang D
    @Description    : Build one record for every commontp_testreport_*.log / .zip file in the folder.
    @Input          : folder -> log folder
                    : details -> test_details JSON keyed by case id
                    : summary_status -> case id -> status (used to resolve 'NAN'; {} for regression)
                    : log_limits -> {status: most lines per log block, 0 = link only}; default: MAX_LOG_LINES for all
    @Returns        : (records, names of .zip files that do not follow the log naming convention)
    @Note           : setup_ip is the IP found in ANY log header of the same SUT, else the sut_xx_yy id
    """
    records: List[Record] = []
    other_zips: List[str] = []
    ip_by_sut: Dict[str, str] = {}
    for path in sorted(Path(folder).iterdir()):
        suffix = path.suffix.lower()
        if not path.is_file() or suffix not in (".log", ".zip"):
            continue
        name_match = LOG_NAME_RE.match(path.name)
        if not name_match:
            if suffix == ".zip":
                other_zips.append(path.name)
            else:
                log.warning("Skipping malformed log file name: %s", path.name)
            continue
        record = make_record(path, name_match, details, summary_status, log_limits or {})
        setup_ip = header_ip(record["header"])
        if setup_ip:
            ip_by_sut[record["sut_id"]] = setup_ip
        records.append(record)
    for record in records:  # second pass, so a .zip (no header) also gets the IP of its SUT
        record["setup_ip"] = ip_by_sut.get(record["sut_id"], record["sut_id"])
    return records, other_zips


def group_cases(records: List[Record]) -> List[Tuple[str, List[Record]]]:
    """
    @Author         : Vedang D
    @Description    : Group records by case id for the HTML case cards.
    @Input          : records -> list of records
    @Returns        : [(case_id, [records of that case]), ...] in first-seen order
    @Note           : a case executed on several setups gives one group with several records
    """
    cases: Dict[str, List[Record]] = {}
    for record in records:
        cases.setdefault(record["case_id"], []).append(record)
    return list(cases.items())


# ------------------------------------------------------------------ HTML rendering
def pie_segments(counts: Dict[str, int], total: int) -> List[Dict[str, str]]:
    """
    @Author         : Vedang D
    @Description    : Compute the SVG donut-chart segments of the status distribution (no JS library needed).
    @Input          : counts -> {status: number of executions}
                    : total -> sum of the counts, must be > 0
    @Returns        : list of dicts with color, dash, gap, offset and tip for one <circle> each
    @Note           : each circle has circumference 100 (r = 15.9155), so percentages map directly to dash lengths;
                      offset 25 starts the first segment at 12 o'clock
    """
    segments = []
    done_percent = 0.0
    for status in STATUSES:
        count = counts.get(status, 0)
        if not count:
            continue
        percent = count * 100.0 / total
        segments.append(
            {
                "color": STATUS_COLOR[status],
                "dash": "%.3f" % percent,
                "gap": "%.3f" % (100 - percent),
                "offset": "%.3f" % ((25 - done_percent) % 100),
                "tip": "%s: %d" % (STATUS_LABEL[status], count),
            }
        )
        done_percent += percent
    return segments


def render(template_name: str, out_path: Path, **context: Any) -> None:
    """
    @Author         : Vedang D
    @Description    : Render a Jinja template (CSS and JS inlined) and write the self-contained HTML file.
    @Input          : template_name -> file inside the templates folder, e.g. 'suite.html'
                    : out_path -> HTML file to write (missing folders are created)
                    : context -> variables for the template
    @Returns        : None
    @Note           : autoescape is ON, so only Markup values (the highlighted execution log) are printed unescaped
    """
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    env.globals.update(STATUSES=STATUSES, WORST=WORST_FIRST, LABEL=STATUS_LABEL, COLOR=STATUS_COLOR)
    env.filters.update(dur=format_duration, ts=format_timestamp)
    context["css"] = Markup((TEMPLATE_DIR / "style.css").read_text(encoding="utf-8"))
    context["js"] = Markup((TEMPLATE_DIR / "app.js").read_text(encoding="utf-8"))
    context["generated"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(env.get_template(template_name).render(**context), encoding="utf-8")
    log.info("Wrote %s", out_path)