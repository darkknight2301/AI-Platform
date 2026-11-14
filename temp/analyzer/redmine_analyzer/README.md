# rmsum 2.0: Redmine ticket summarisation and analysis

Command-line tool that reads a Redmine ticket together with its parent, sub-tasks and related tickets and
produces a **short summary** and a **detailed analysis** with a **locally hosted LLM** (Qwen 27B Instruct via
Ollama, optionally on another machine over SSH). Reports: **HTML**, **Excel**, **JSON**, plus an **Excel audit log**.

* Python **3.12+** only. Runtime dependencies: `openpyxl`, `pyyaml`; `paramiko` only for the SSH option.
* No database, no external LLM API, no web UI. Configuration is one YAML file; interaction is `argparse`.

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .            # add ".[ssh]" if Ollama runs on another machine
cp config.example.yml config.yml && chmod 600 config.yml    # then edit it
```

On the machine that runs Ollama: `ollama pull qwen3:27b` (or your exact Qwen 27B Instruct tag; put it in `llm.model`).
In Redmine enable *Administration, Settings, API, Enable REST web service* and use an API key that can see the tickets.

`translate.module` (default `api`) must be importable and expose a synchronous `translate(text) -> str`. If it cannot be
imported, translation is switched off with a warning and Japanese text is analysed untranslated (flagged in the report).

## Usage

```bash
rmsum search "login" --status all
rmsum analyze 1234                              # html, xlsx and json in ./reports
rmsum analyze 1234 1250 -f html                 # json is always written (see "Re-runs")
rmsum analyze --from-file today.txt             # 100-200 ids: one per line, '#' or '//' comments allowed
rmsum analyze 1234 --regenerate                 # analyse again even if nothing changed
rmsum analyze 1234 --max-depth 3 --max-tickets 40 --no-translate
rmsum -c other.yml -v analyze 1234
```

The terminal shows each short summary, warnings and file paths, and for several tickets a final success count.
Exit code: `0` all succeeded, `1` at least one ticket failed (the others still ran), `130` interrupted with Ctrl-C.

### Ollama on another machine (SSH)

Set `ssh.enabled: true` (or pass `--ssh`). **When a run starts** you are asked, once:

```
Ollama server IP / hostname [192.168.1.50]:        <- Enter accepts the default from config.yml
SSH username [llmuser]:
SSH password for llmuser@192.168.1.50:             <- hidden, three tries
```

* The IP, user name and password are held in memory for the run only. **There is no password key in the YAML**
  (a `password:` entry is rejected with an explanation). Only non-secret defaults (host, username, port) live there.
* The password is used solely to log in over SSH. It is never sent to Ollama, never placed in a prompt, report, audit log
  or JSON file, and log output is filtered to mask it (verified by the tests).
* HTTP to Ollama is carried inside the SSH connection: no local port is opened, nothing but Ollama is needed remotely.
* Unknown host keys are rejected unless `ssh.trust_unknown_host: true`, because an impostor server could capture the
  password. Run `ssh user@host` once to add the host to `~/.ssh/known_hosts`.
* Without a terminal (cron/CI) the values come from `RMSUM_SSH_HOST`, `RMSUM_SSH_USER`, `RMSUM_SSH_PASSWORD`; if they
  are missing the run stops with a clear message instead of hanging.
* Before the first ticket the tool checks that Ollama answers and that `llm.model` is installed there, so a typo fails
  immediately, not after 40 minutes.

## Output

| File | Content |
|---|---|
| `redmine_<id>.html` | Self-contained, no JavaScript. Status/priority badges, short summary, risk chips, 12 expandable sections (blockers, contradictions, requirement changes highlighted), related tickets, MR/commit/branch table, documents and attachment names, warnings, and the statements that validation rejected. Every ticket, journal and MR is a link. |
| `redmine_<id>.xlsx` | *Short Summary*, *Detailed Analysis*, *Related Tickets*, *MR References* (MR, commit, branch), *Open Issues*, *Other References*. Hyperlinked, filterable, formula-injection safe. |
| `redmine_<id>.json` | Complete analysis (schema v2). Also the stored state for re-runs. |
| `audit_log.xlsx` | One row per ticket per run: time, OS user, ticket, outcome (`ANALYSED`, `REUSED`, `FAILED`), tickets analysed/skipped, mode, model, LLM calls, tokens, warnings, rejected statements, timings (fetch/translate/LLM/total), where the model ran, files written, error text. Appended after every ticket, so a crash loses nothing. No credentials, no ticket text beyond the subject. |

Source tags: `#1234` is a ticket, `#1234 J56` is journal 56 of ticket 1234; both link into Redmine.

### Re-runs

There is no cache database. Each run re-fetches the ticket graph (cheap) and compares a fingerprint of every ticket's
`updated_on` plus every setting that influences the result (model, depth, limits, git URL, prompt version, ...) with the
`redmine_<id>.json` already in the output folder. Same fingerprint: the stored analysis is reused (reports are rewritten,
no LLM call, audit outcome `REUSED`). Any ticket or setting changed: analysed again. `--regenerate` always re-analyses.
Delete the JSON to force it for one ticket. Translations are not cached across runs.

## Architecture

```
domain/        models (frozen), extraction, validation, budgeting      pure, no I/O
ports.py       Transport, IssueSource, LanguageModel, TextTranslator   interfaces
adapters/      transport (urllib + retry), ssh, redmine, ollama, translation
application/   graph, render, prompts, pipeline, service               use cases
reporting/     html, xlsx, audit, writer                               outputs
config.py  errors.py  logging_setup.py  cli.py (the only place concrete classes are wired together)
```

* **Translation in batches.** All Japanese texts of an analysis go to `api.translate` in a few calls, joined by numbered markers.
  If the translator mangles the markers, that batch is redone text by text.

## Development

```bash
python -m unittest discover -s tests -v     # 97 tests, no extra packages needed
pip install -e ".[dev]" && black .          # formatting: line length 120 (configured in pyproject.toml)
```

Add another LLM: implement `LanguageModel` (`generate`, `check_ready`, `model_id`, `context_tokens`, `max_output_tokens`) and register it in `BACKENDS`.

## Limitations (please read)

* **Throughput.** Processing is sequential on purpose (one GPU is the bottleneck). A ticket needs 2 model calls when it fits the
  context window, otherwise one per related ticket plus 2. 100-200 tickets per day is feasible only if your model answers fast
  enough; use `keep_alive`, a sensible `num_ctx`, and a low `max_depth` to control cost, and check the audit log timings.
* MR/commit/branch links assume GitLab URLs (`/-/merge_requests/N`). Validation covers ticket IDs, MR IDs, commit SHAs and source tags;
  it cannot detect fluent prose that misreads a real ticket, so `confirmed` means "cites a real source", not "verified true".
* The token estimate is character based, not the model's tokenizer. Redmine does not resolve user ids in journal changes
  (assignee changes show raw ids); status, priority and custom-field names are resolved.
