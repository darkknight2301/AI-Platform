"""Command line interface and composition root: the only place where concrete classes are wired together."""

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path

from .adapters.ollama import create_model
from .adapters.redmine import RedmineClient
from .adapters.ssh import Connector, CredentialPrompter, connect_paramiko, open_ssh_transport
from .adapters.transport import RetryingTransport, UrllibTransport
from .adapters.translation import load_translator
from .application.service import AnalysisOutcome, AnalysisService, AnalysisSettings
from .config import Config, load_config
from .errors import ConfigError, RmsumError
from .logging_setup import SecretRedactor, configure_logging
from .ports import Transport
from .reporting.audit import AuditEntry, AuditLog
from .reporting.writer import FORMATS, load_previous, report_path, write_reports

log = logging.getLogger("rmsum.cli")


def build_parser() -> argparse.ArgumentParser:
    """Define the command line."""
    parser = argparse.ArgumentParser(
        prog="rmsum", description="Summarise and analyse Redmine tickets with a local LLM."
    )
    parser.add_argument(
        "-c",
        "--config",
        default=os.environ.get("RMSUM_CONFIG", "config.yml"),
        help="YAML config file (default: $RMSUM_CONFIG or ./config.yml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    commands = parser.add_subparsers(dest="command", required=True)

    search = commands.add_parser("search", help="find tickets by id or subject text")
    search.add_argument("query", help="ticket number or subject substring")
    search.add_argument("--project", help="project identifier")
    search.add_argument("--status", choices=["open", "closed", "all"], default="open")
    search.add_argument("--limit", type=int, default=20)

    analyze = commands.add_parser("analyze", help="analyse tickets and write reports")
    analyze.add_argument("tickets", nargs="*", type=int, metavar="TICKET_ID")
    analyze.add_argument("--from-file", type=Path, help="text file with one ticket id per line")
    analyze.add_argument("-f", "--format", nargs="+", choices=list(FORMATS), default=["html", "xlsx", "json"])
    analyze.add_argument("-o", "--out", type=Path, help="output directory (default: output.dir from config)")
    analyze.add_argument("--regenerate", action="store_true", help="analyse again even if nothing changed")
    analyze.add_argument("--max-depth", type=int, help="override analysis.max_depth")
    analyze.add_argument("--max-tickets", type=int, help="override analysis.max_tickets")
    analyze.add_argument("--no-translate", action="store_true", help="do not translate Japanese text")
    analyze.add_argument(
        "--ssh", action=argparse.BooleanOptionalAction, default=None, help="run Ollama over SSH (overrides ssh.enabled)"
    )
    return parser


def read_ticket_ids(path: Path) -> list[int]:
    """Ticket ids from a text file: one per line, optional leading ``#``, ``#``/``//`` comment lines allowed."""
    ids: list[int] = []
    try:
        lines = path.read_text("utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    for number, line in enumerate(lines, 1):
        tokens = line.split()
        if not tokens or tokens[0].startswith("//"):
            continue
        token = tokens[0].lstrip("#")
        if token.isdigit():
            ids.append(int(token))
        elif not tokens[0].startswith("#"):
            raise ConfigError(f"{path}:{number}: '{tokens[0]}' is not a ticket id")
    return ids


def collect_ticket_ids(args: argparse.Namespace) -> list[int]:
    """Positional ids plus ids from ``--from-file``; duplicates removed, order kept."""
    ids = list(args.tickets) + (read_ticket_ids(args.from_file) if args.from_file else [])
    unique = list(dict.fromkeys(ids))
    if not unique:
        raise ConfigError("no ticket ids given (use TICKET_ID arguments or --from-file)")
    return unique


@dataclass
class Runtime:
    """Transports and helpers shared by the commands; closed by the ExitStack in :func:`main`."""

    redmine_transport: Transport
    llm_transport: Transport
    llm_endpoint: str
    llm_location: str  # where the model runs, for the audit log (never credentials)


def _redmine_transport(cfg: Config, override: Transport | None, stack: ExitStack) -> Transport:
    transport = override or RetryingTransport(UrllibTransport(cfg.redmine.verify_ssl), cfg.redmine.retries)
    stack.callback(transport.close)
    return transport


def _llm_runtime(
    cfg: Config,
    use_ssh: bool,
    override: Transport | None,
    prompter: CredentialPrompter,
    connector: Connector,
    redactor: SecretRedactor,
    stack: ExitStack,
) -> tuple[Transport, str, str]:
    """Create the transport to the model: injected (tests), SSH (credentials asked now), or direct HTTP."""
    if override is not None:
        return override, cfg.llm.endpoint, cfg.llm.endpoint
    if use_ssh:
        ssh = open_ssh_transport(cfg.ssh, prompter, redactor.register, connector)
        transport: Transport = RetryingTransport(ssh, cfg.llm.retries)
        endpoint = f"http://{cfg.ssh.remote_host}:{cfg.ssh.remote_port}"
        location = f"ssh:{ssh.host}"
    else:
        transport = RetryingTransport(UrllibTransport(), cfg.llm.retries)
        endpoint = location = cfg.llm.endpoint
    stack.callback(transport.close)
    return transport, endpoint, location


def _search(args: argparse.Namespace, cfg: Config, redmine_transport: Transport) -> int:
    for t in RedmineClient(cfg.redmine, redmine_transport).search(args.query, args.project, args.status, args.limit):
        print(f"#{t.id:<7} {t.status:<14} {t.priority:<10} {t.assignee or '-':<20} {t.subject}")
    return 0


def _audit_entry(ticket_id: int, outcome: str, location: str, **fields) -> AuditEntry:
    return AuditEntry(ticket_id=ticket_id, outcome=outcome, ollama_host=location, **fields)


def _success_entry(result: AnalysisOutcome, location: str, files: Sequence[Path]) -> AuditEntry:
    a, stats = result.analysis, result.stats
    return _audit_entry(
        a.root_id,
        "REUSED" if result.reused else "ANALYSED",
        location,
        subject=a.root.title,
        tickets_analysed=len(a.tickets),
        not_analysed=len(a.skipped),
        mode=a.meta.mode,
        model=a.meta.model,
        llm_calls=stats.llm_calls,
        prompt_tokens=stats.prompt_tokens,
        output_tokens=stats.output_tokens,
        warnings=len(a.warnings),
        rejected=len(a.dropped),
        fetch_seconds=stats.fetch_seconds,
        translate_seconds=stats.translate_seconds,
        llm_seconds=stats.llm_seconds,
        total_seconds=stats.total_seconds,
        files=", ".join(str(f) for f in files),
    )


def _analyze(args: argparse.Namespace, cfg: Config, runtime: Runtime) -> int:
    """Analyse each requested ticket. A failure on one ticket is recorded and the others still run."""
    ids = collect_ticket_ids(args)
    overrides = {k: v for k, v in (("max_depth", args.max_depth), ("max_tickets", args.max_tickets)) if v is not None}
    cfg = replace(cfg, analysis=replace(cfg.analysis, **overrides))
    out = Path(args.out or cfg.output.dir).expanduser()
    audit = AuditLog(out / cfg.output.audit_file if cfg.output.audit_file else None)

    translator = None if args.no_translate else load_translator(cfg.translate)
    model = create_model(cfg.llm, runtime.llm_transport, runtime.llm_endpoint)
    model.check_ready()  # fail before the first ticket, not in the middle of a 150-ticket batch
    service = AnalysisService(
        RedmineClient(cfg.redmine, runtime.redmine_transport),
        model,
        translator,
        AnalysisSettings.from_config(cfg, translation_enabled=translator is not None),
    )

    failures = 0
    for position, ticket_id in enumerate(ids, 1):
        log.info("[%d/%d] ticket #%d", position, len(ids), ticket_id)
        previous = None if args.regenerate else load_previous(report_path(out, ticket_id, "json"))
        try:
            outcome = service.analyze(ticket_id, previous)
            files = write_reports(outcome.analysis, out, args.format)
            audit.record(_success_entry(outcome, runtime.llm_location, files))
        except Exception as exc:  # a bug or outage on one ticket must not abort a long batch
            if not isinstance(exc, RmsumError):
                log.exception("unexpected error while analysing #%d", ticket_id)
            log.error("#%d failed: %s", ticket_id, exc)
            audit.record(_audit_entry(ticket_id, "FAILED", runtime.llm_location, error=f"{type(exc).__name__}: {exc}"))
            failures += 1
            continue
        a = outcome.analysis
        how = "reused" if outcome.reused else "analysed"
        print(f"\n#{ticket_id} {a.root.title} [{a.root.status}]  ({how}, {outcome.stats.total_seconds:.0f}s)")
        print(a.short_summary)
        for warning in a.warnings:
            print(f"  warning: {warning}")
        for path in files:
            print(f"  -> {path}")
    if len(ids) > 1:
        print(f"\n{len(ids) - failures} of {len(ids)} ticket(s) succeeded, {failures} failed.")
    return 1 if failures else 0


def main(
    argv: Sequence[str] | None = None,
    *,
    redmine_transport: Transport | None = None,
    llm_transport: Transport | None = None,
    prompter: CredentialPrompter | None = None,
    ssh_connector: Connector = connect_paramiko,
) -> int:
    """Entry point; returns the process exit code (0 ok, 1 failures, 130 interrupted).

    The keyword arguments are injection points for tests; production code leaves them at their defaults.
    """
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        redactor = configure_logging(cfg.logging, args.verbose)
        redactor.register(cfg.redmine.api_key)
        with ExitStack() as stack:
            transport = _redmine_transport(cfg, redmine_transport, stack)
            if args.command == "search":
                return _search(args, cfg, transport)
            use_ssh = cfg.ssh.enabled if args.ssh is None else args.ssh
            llm, endpoint, location = _llm_runtime(
                cfg, use_ssh, llm_transport, prompter or CredentialPrompter(), ssh_connector, redactor, stack
            )
            return _analyze(args, cfg, Runtime(transport, llm, endpoint, location))
    except RmsumError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
