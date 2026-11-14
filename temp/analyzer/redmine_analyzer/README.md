# rmsum: Redmine ticket summarisation and analysis

Command-line tool that reads a Redmine ticket together with its parent, sub-tasks and related
tickets, and produces a **short summary** and a **detailed analysis** using a **locally hosted LLM**
(Qwen 27B Instruct through Ollama). Reports are written as **HTML**, **Excel** and **JSON**.

* Python **3.12+** only. Runtime dependencies: **`openpyxl`** (xlsx export) and **`pyyaml`** (YAML config). Everything else is the standard library (`urllib`, `sqlite3`, `argparse`, `logging`, `unittest`).
* No external LLM APIs. No web UI: configuration is a `.yml` file, interaction is `argparse`.

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .

ollama pull qwen3:27b            # or the exact Qwen 27B Instruct tag you use
cp config.example.yml config.yml # then edit; chmod 600 config.yml
export REDMINE_API_KEY=...       # referenced as ${REDMINE_API_KEY} in config.yml
```

Redmine: enable *Administration → Settings → API → Enable REST web service*, and use an API key of a
user who can see the tickets.

Translation: `translate.module` (default `api`) must be importable and expose `translate(text) -> str`
(synchronous). If it cannot be imported, translation is disabled with a warning and Japanese text is
analysed untranslated (flagged in the report). Use `--no-translate` to skip it.

## Usage

```bash
rmsum search "login"                          # find tickets by subject (or: rmsum search 1234)
rmsum search login --project web --status all --limit 50

rmsum analyze 1234                            # writes reports/redmine_1234.html and .xlsx
rmsum analyze 1234 1250 -f html xlsx json -o out/
rmsum analyze 1234 --regenerate               # ignore cache, analyse again
rmsum analyze 1234 --max-depth 3 --max-tickets 40
rmsum -c /path/other.yml -v analyze 1234      # other config, debug logging
```

`python -m rmsum ...` works too. The terminal shows the short summary, warnings and output paths.
Exit code is 1 if any ticket failed (others are still processed).

### Output

| Format | Content |
|---|---|
| **HTML** | Self-contained, no JavaScript. Header with status/priority badges, short summary, risk chips, 12 expandable analysis sections (blockers/contradictions highlighted), related-ticket table, MR/commit/branch table, documents/links/attachments table, warnings. Every ticket, journal, MR and URL is a link. Light/dark aware. |
| **Excel** | Sheets: *Short Summary*, *Detailed Analysis*, *Related Tickets*, *MR References* (MR, commit, branch), *Open Issues*, *Other References* (documents, URLs, attachment names, ticket mentions). Hyperlinked, filterable, formula-injection safe. |
| **JSON** | The complete `Analysis` object (what the cache stores). |

Source tags: `#1234` = ticket (subject, description, fields), `#1234 J56` = journal 56 of ticket 1234; both link to Redmine.

## How it works

```
CLI ─► graph.py (BFS over parent/children/relations, visited-set, depth + size caps)
    ─► translate.py (Japanese paragraphs only; cached)      ─► extract.py (regex facts + source tags)
    ─► context.py (render, token budget, chronological chunks)
    ─► analyzer.py: [pass 1 per ticket, only if too big] ─► pass 2 consolidated analysis ─► pass 3 short summary
    ─► validation ─► cache.py ─► export_html.py / export_xlsx.py / JSON
```

**Facts by code, reasoning by the LLM.** Ticket relations come from the Redmine API; ticket IDs, MR IDs
(`!123`, `MR 123`, `/merge_requests/123`, `/pull/123`), commits, branches, documents, URLs and attachment
filenames come from regexes and carry the journal they were found in. The model receives them as a FACTS
block and is told it may mention no other identifier.

**Validation of model output.** Each statement has a basis: `confirmed` (with source tags), `assumption`,
or `unverified` (the model claimed "confirmed" but its tags do not exist). Unknown source tags are removed;
statements naming a ticket, MR or commit that is not in the extracted data are dropped, and the number
dropped is shown as a warning. Summary sentences are checked the same way.

**Large tickets.** Pass 1 is skipped when everything fits in `num_ctx`. Otherwise each ticket is analysed
separately; its conversation is split chronologically into chunks that fit the budget, so no comment is dropped.
If the per-ticket results still do not fit pass 2, detail is removed from *related* tickets first, never from the root,
and a warning says what was omitted. A single text longer than `max_text_chars` is clipped in the middle with an explicit marker.

**Determinism.** Temperature 0, top_p 1, fixed seed, explicit `num_ctx`, JSON-schema constrained output, one
repair retry on invalid JSON, prompts versioned in `prompts.py`.

**Caching and regeneration.** Each run re-fetches the ticket graph (cheap) and compares a fingerprint of every
ticket's `updated_on` + prompt version + model. Unchanged → cached analysis, no LLM calls. Any ticket in the graph
changed → analysed again automatically. `--regenerate` forces it. Translations are cached per paragraph.
Delete the SQLite file (`cache.path`) to reset everything.

**Not silently ignored.** Tickets beyond `max_depth`/`max_tickets`, or that cannot be fetched (no permission, deleted),
are listed under "Not analysed". Missing information is stated ("none found in ticket data"), not filled in.

## Adding another local LLM

Implement `generate(system, prompt, schema=None) -> str` plus `model_id`, `num_ctx`, `max_output` (see
`LLMBackend` in `llm.py`), add the class to `BACKENDS`, and set `llm.backend`. Ollama is ~20 lines.

## Tests

```bash
python -m unittest discover -s tests -v      # no extra packages needed; pytest also works
```

51 tests: unit tests (extraction, graph traversal and loops, translation, context chunking, config, validation,
cache invalidation, HTML/XLSX content and escaping) and end-to-end tests that drive the real CLI against a fake
Redmine (`tests/fixtures/sample_issues.json`: parent, child, blocker, circular relation, Japanese text, MRs, commit,
branches, attachment) and a fake Ollama endpoint.

## Limitations (please read)

* **Verified with fakes only.** The test suite never talks to a real Redmine or Ollama. First run against your instance
  with a ticket you know well and compare the output with it. Check the Ollama request/response shape if your version differs.
* MR/commit/branch links assume **GitLab** URL layout (`/-/merge_requests/N`). Other hosts need small changes in `extract.py`.
* Validation covers ticket IDs, MR IDs, commit SHAs and source tags. It cannot verify branch names or prose that merely
  *sounds* plausible, so treat `confirmed` as "the model cites a real source", and open the linked journal for anything important.
* Token counts are a conservative character-based estimate, not the model's tokenizer.
* Translation works per paragraph; a very long single Japanese paragraph is sent to `api.translate` in one piece.
* Journals are read from the issue endpoint; private notes you cannot see are not available. Attachment contents are never read.
* Redmine's issue API does not resolve user ids in journal changes (assignee changes show raw ids); status, priority and custom-field names are resolved.
