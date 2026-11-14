"""Command line interface: ``rmsum search`` and ``rmsum analyze``."""

import argparse
import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from .analyzer import analyze
from .cache import Cache
from .config import Config, ConfigError, LoggingCfg, load_config
from .export_html import render_html
from .export_xlsx import write_xlsx
from .httpjson import Fetch, request_json
from .llm import LLMError, make_backend
from .models import Analysis
from .redmine import RedmineClient, RedmineError
from .translate import load_translator

log = logging.getLogger("rmsum")


def build_parser() -> argparse.ArgumentParser:
    """Define the command line."""
    p = argparse.ArgumentParser(prog="rmsum", description="Summarise and analyse Redmine tickets with a local LLM.")
    p.add_argument("-c", "--config", default=os.environ.get("RMSUM_CONFIG", "config.yml"),
                   help="YAML config file (default: $RMSUM_CONFIG or ./config.yml)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="find tickets by id or subject text")
    s.add_argument("query", help="ticket number or subject substring")
    s.add_argument("--project", help="project identifier")
    s.add_argument("--status", choices=["open", "closed", "all"], default="open")
    s.add_argument("--limit", type=int, default=20)

    a = sub.add_parser("analyze", help="analyse one or more tickets and write reports")
    a.add_argument("tickets", nargs="+", type=int, metavar="TICKET_ID")
    a.add_argument("-f", "--format", nargs="+", choices=["html", "xlsx", "json"], default=["html", "xlsx"])
    a.add_argument("-o", "--out", type=Path, help="output directory (default: output.dir from config)")
    a.add_argument("--regenerate", action="store_true", help="ignore the cache and analyse again")
    a.add_argument("--max-depth", type=int, help="override analysis.max_depth")
    a.add_argument("--max-tickets", type=int, help="override analysis.max_tickets")
    a.add_argument("--no-translate", action="store_true", help="do not translate Japanese text")
    return p


def setup_logging(cfg: LoggingCfg, verbose: bool) -> None:
    """Log to stderr and, if configured, to a rotating file."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if cfg.file:
        handlers.append(logging.handlers.RotatingFileHandler(
            Path(cfg.file).expanduser(), maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else cfg.level.upper(), handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


def _search(args: argparse.Namespace, cfg: Config, fetch: Fetch) -> int:
    """Print matching tickets, one per line."""
    for t in RedmineClient(cfg.redmine, fetch).search(args.query, args.project, args.status, args.limit):
        print(f"#{t.id:<7} {t.status:<14} {t.priority:<10} {t.assignee or '-':<20} {t.subject}")
    return 0


def _export(a: Analysis, out: Path, formats: list[str]) -> list[Path]:
    """Write the requested report files and return their paths."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in formats:
        path = out / f"redmine_{a.root_id}.{fmt}"
        if fmt == "html":
            path.write_text(render_html(a), "utf-8")
        elif fmt == "xlsx":
            write_xlsx(a, path)
        else:
            path.write_text(json.dumps(a.to_dict(), ensure_ascii=False, indent=2), "utf-8")
        written.append(path)
    return written


def _analyze(args: argparse.Namespace, cfg: Config, fetch: Fetch) -> int:
    """Analyse each requested ticket; a failure on one ticket does not stop the others."""
    for name in ("max_depth", "max_tickets"):
        if (value := getattr(args, name)) is not None:
            setattr(cfg.analysis, name, value)
    client, backend, cache = RedmineClient(cfg.redmine, fetch), make_backend(cfg.llm, fetch), Cache(cfg.cache.path)
    translator = None if args.no_translate else load_translator(cfg.translate, cache)
    out = args.out or Path(cfg.output.dir).expanduser()
    status = 0
    for tid in args.tickets:
        try:
            a = analyze(tid, cfg=cfg, client=client, backend=backend, cache=cache,
                        translator=translator, regenerate=args.regenerate)
        except (RedmineError, LLMError) as e:
            log.error("#%d failed: %s", tid, e)
            status = 1
            continue
        root = a.tickets[0]
        print(f"\n#{tid} {root.title} [{root.status}]\n{a.short_summary}")
        for w in a.warnings:
            print(f"  warning: {w}")
        for path in _export(a, out, args.format):
            print(f"  -> {path}")
    return status


def main(argv: list[str] | None = None, fetch: Fetch = request_json) -> int:
    """Entry point. ``fetch`` is injectable for tests. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        setup_logging(cfg.logging, args.verbose)
        return {"search": _search, "analyze": _analyze}[args.command](args, cfg, fetch)
    except (ConfigError, RedmineError, LLMError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
