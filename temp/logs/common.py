"""Shared helpers for suite_report.py and regression_report.py (Python 3.8)."""
import json
import logging
import re
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape

log = logging.getLogger("log_report")
HERE = Path(__file__).parent
MAX_LOG_LINES = 5000       # longer sections keep first/last half in HTML

STATUSES = ["passed", "failed", "error", "pending", "skipped", "nan"]
WORST = ["failed", "error", "pending", "nan", "skipped", "passed"]
LABEL = {s: s.capitalize() for s in STATUSES}
LABEL["nan"] = "NAN"
COLOR = {"passed": "2E9E5B", "failed": "D64545", "error": "E08A1E",
         "pending": "D4B106", "skipped": "8C959F", "nan": "B8C0CC"}

NAME_RE = re.compile(r"^commontp_testreport_(?P<status>passed|failed|error|pending|skipped|nan)_"
                     r"(?P<sut>sut_\d{1,3}_\d{1,3})_(?P<name>.+)_(?P<case>C\d{4,8})\.(?P<ext>log|zip)$", re.I)
SECTION_RE = re.compile(r"^\*{3,}\s*(Failure|Compilation Log|Execution Log)\s+for\b.*$", re.M | re.I)
RUN_KEY_RE = re.compile(r"^(sut_\d+_\d+)_(\d{2}-\d{2}-\d{4}_\d{2}-\d{2}-\d{2})$")
SUT_IP_RE = re.compile(r"\[(\d{1,3}(?:\.\d{1,3}){3})\]")
TS_FMT = "%d-%m-%Y_%H-%M-%S"


# ------------------------------------------------------------------ small utilities
def load_json(path):
    """Return a dict; {} if the file is missing or invalid."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        log.warning("Cannot read %s: %s", Path(path).name, exc)
        return {}


def case_id_of(text):
    """'anything::C123456' -> 'C123456'"""
    m = re.search(r"C\d{4,8}\s*$", str(text).strip()) or re.search(r"C\d{4,8}", str(text))
    return m.group(0).strip() if m else None


def parse_ts(s):
    try:
        return datetime.strptime(s.strip(), TS_FMT)
    except (ValueError, AttributeError):
        return None


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def header_ip(header):
    """Full IP from the header line  SUT: host[sut_87_70][14.31.122.34]; None if that part is missing."""
    m = SUT_IP_RE.search(header.get("SUT", ""))
    return m.group(1) if m else None


def fmt_ts(ts):
    return ts.strftime("%d-%m-%Y %H:%M:%S") if ts else "n/a"


def fmt_dur(sec):
    if sec is None or sec != sec:          # None or NaN
        return "-"
    return "%.2f s" % sec if sec < 60 else "%dm %02ds" % (sec // 60, sec % 60)


def details_by_case(raw):
    """Normalise details JSON keys to plain case ids."""
    return {case_id_of(k): v for k, v in raw.items() if case_id_of(k) and isinstance(v, dict)}


def summary_statuses(summary):
    """case id -> status according to the summary lists (used to resolve 'NAN')."""
    out = {}
    for st in ("passed", "failed", "pending", "skipped"):
        for item in summary.get(st) or []:
            if case_id_of(item):
                out[case_id_of(item)] = st
    return out


# ------------------------------------------------------------------ log parsing
def parse_log(path):
    """Return (header dict, {'failure' | 'compilation log' | 'execution log': text})."""
    text = Path(path).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    marks = list(SECTION_RE.finditer(text))
    head = text[:marks[0].start()] if marks else text
    sections = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        sections.setdefault(m.group(1).lower(), text[m.end():end].strip("\n"))
    header = OrderedDict()
    for line in head.splitlines():
        line = line.strip()
        if line and set(line) != {"*"} and ":" in line:
            k, v = line.split(":", 1)
            header[k.strip()] = v.strip()
    return header, sections


def clip(text):
    lines = text.split("\n")
    if len(lines) <= MAX_LOG_LINES:
        return text
    half = MAX_LOG_LINES // 2
    skipped = len(lines) - 2 * half
    return "\n".join(lines[:half] + ["", "... %d lines omitted - see the original .log ..." % skipped, ""] + lines[-half:])


def highlight(text):
    out = []
    for line in clip(text).split("\n"):
        s, cls = line.lstrip(), ""
        if s.startswith(("[  FAILED", "[  FAILURE")) or s.endswith(": Failure"):
            cls = "l-fail"
        elif s.startswith(("[       OK", "[  PASSED")):
            cls = "l-ok"
        elif s.startswith("[ RUN"):
            cls = "l-run"
        elif s.startswith(("[==", "[--")):
            cls = "l-dim"
        out.append('<span class="%s">%s</span>' % (cls, escape(line)) if cls else str(escape(line)))
    return Markup("\n".join(out))


def build_records(folder, details, summary_status):
    """One dict per .log / .zip file. Zips are NOT opened: only name + JSON info are used.
    Returns (records, zip names that do not follow the log naming convention)."""
    recs, other_zips, ips = [], [], {}
    for p in sorted(Path(folder).iterdir()):
        ext = p.suffix.lower()
        if ext not in (".log", ".zip"):
            continue
        m = NAME_RE.match(p.name)
        if not m:
            if ext == ".zip":
                other_zips.append(p.name)
            else:
                log.warning("Skipping malformed log name: %s", p.name)
            continue
        cid, status = m.group("case"), m.group("status").lower()
        if status == "nan":
            status = summary_status.get(cid, "nan")
        d = details.get(cid, {})
        rec = dict(file=str(p.resolve()), file_name=p.name, is_zip=(ext == ".zip"), case_id=cid,
                   name=m.group("name"), status=status, sut=m.group("sut").lower(), ip="",
                   header={}, failure=None, compilation=None, execution=None, ts_raw="",
                   duration=to_float(d.get("duration")),
                   markers=[x.strip() for x in str(d.get("markers", "")).split(",") if x.strip()],
                   test_file=str(d.get("file_path", "") or ""), function=str(d.get("function_name", "") or ""),
                   run_key="", order=10 ** 9)
        if ext == ".log":
            header, sec = parse_log(p)
            rec.update(header=header, ts_raw=header.get("Timestamp", ""),
                       failure=clip(sec["failure"]) if "failure" in sec else None,
                       compilation=clip(sec["compilation log"]) if sec.get("compilation log") else None,
                       execution=highlight(sec["execution log"]) if sec.get("execution log") else None)
            if header_ip(header):
                ips[rec["sut"]] = header_ip(header)
        recs.append(rec)
    for r in recs:                      # setup id = IP from any log header of that SUT, else sut_xx_yy
        r["ip"] = ips.get(r["sut"], r["sut"])
    return recs, other_zips


def group_cases(recs):
    cases = OrderedDict()
    for r in recs:
        cases.setdefault(r["case_id"], []).append(r)
    return list(cases.items())


# ------------------------------------------------------------------ HTML rendering
def pie_segments(counts, total):
    """Donut chart as SVG circles (stroke-dasharray technique), no JS library needed."""
    segs, cum = [], 0.0
    for s in STATUSES:
        n = counts.get(s, 0)
        if n:
            pct = n * 100.0 / total
            segs.append(dict(color=COLOR[s], dash="%.3f" % pct, gap="%.3f" % (100 - pct),
                             offset="%.3f" % ((25 - cum) % 100), tip="%s: %d" % (LABEL[s], n)))
            cum += pct
    return segs


def render(template, out_path, **ctx):
    env = Environment(loader=FileSystemLoader(str(HERE / "templates")), autoescape=True)
    env.globals.update(STATUSES=STATUSES, WORST=WORST, LABEL=LABEL, COLOR=COLOR)
    env.filters.update(dur=fmt_dur, ts=fmt_ts)
    ctx["css"] = Markup((HERE / "templates" / "style.css").read_text(encoding="utf-8"))
    ctx["js"] = Markup((HERE / "templates" / "app.js").read_text(encoding="utf-8"))
    ctx["generated"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    Path(out_path).write_text(env.get_template(template).render(**ctx), encoding="utf-8")
    log.info("Wrote %s", out_path)
