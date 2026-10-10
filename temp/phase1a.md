# Phase 1a Plan: Technical Agent Backend (CLI, experiments A/B/C)

Status: DRAFT, awaiting your go-ahead. Nothing here is built yet.

## 1. Goal

Prove, on 15-20 real specs and your benchmark, which retrieval/answering design gives correct, cited, non-hallucinated answers, using only the 24 GB dev GPU. Output: a working `specagent` CLI plus a benchmark report that management can read.

## 2. Repository layout (proposal)

```
specagent/
  pyproject.toml
  src/specagent/
    catalog/      # spec catalog: family, version, product, acl_group, svn_revision
    ingest/       # parsers: pdf.py, docx.py, pptx.py, xlsx.py -> common schema
    structure/    # section tree, table merge, field extraction, requirement tagging
    refs/         # cross-reference + glossary extraction
    index/        # Postgres schema, embeddings, keyword index, graph tables
    llm/          # model client (local server), prompts, offline guard
    agent/        # approach_a.py, approach_b.py, approach_c.py, verifier.py
    eval/         # benchmark loader, metrics, report generator
    cli.py        # argparse entry point
  tests/
  docker/         # compose file: postgres, model server, app
```

## 3. CLI surface (argparse)

| Command | Purpose |
|---------|---------|
| `specagent catalog add <file> --family NVMe --version 1.4c --product X` | Register a spec with metadata |
| `specagent ingest <folder>` | Parse, structure, index; prints a quality report |
| `specagent ask "<question>" --specs nvme-1.4c,pcie-4.0 --approach a\|b\|c` | Answer with citations |
| `specagent show <section-id>` | Print a cited section exactly as indexed |
| `specagent eval --benchmark bench.yaml --approach a,b,c` | Run benchmark and write a report |

## 4. Common schema (what every parser must produce)

- `Document`: spec_family, version, product/customer/form_factor, svn_revision, acl_group
- `Section`: id (`NVMe-1.4c/§2.5.3`), title, level, parent, text, page range
- `Field`: register, field name, bit range, type, reset, description (from register tables)
- `Requirement`: sentence, level (shall / should / may / mandatory / optional), section id
- `Ref`: source section, target (section, figure, or other document), raw text
- `Term`: glossary term, definition, spec scope
- `Figure`: caption, nearby text, image flag (for OCR/vision later)

## 5. Work packages and acceptance checks

| # | Work package | Done when |
|---|--------------|-----------|
| 1 | Environment: Postgres with pgvector, local model server, offline guard | App starts with no network; a test confirms outbound connections fail |
| 2 | PDF parser and structure builder, tested on the NVMe 1.4c sample | Heading tree matches the spec's own table of contents; register tables merged; headers/footers removed |
| 3 | Field, requirement, reference and glossary extraction | Spot-check of 20 registers and 20 requirements against the PDF by an engineer |
| 4 | .docx, .pptx, .xlsx parsers to the same schema | Same quality report format for all four types |
| 5 | Index and Approach A | `ask --approach a` answers with section citations |
| 6 | Approach B (tool-using loop) | Answers questions needing 2+ hops or 2+ specs |
| 7 | Approach C (A, escalate to B, verifier) | Verifier removes unsupported claims on a deliberately tricky question set |
| 8 | Evaluation harness and report | Metrics table for A/B/C on your benchmark |
| 9 | Docker packaging for the single server | One command brings the stack up |

## 6. Experiments

| Variable | Options tried |
|----------|---------------|
| Generator model | 2 open-weight families, one 14B-class and one ~30B-class quantized, subject to licence approval |
| Embedding and reranker | One open-weight pair, compared against keyword-only retrieval |
| Chunking | Whole-section versus field-level versus hybrid |
| Approach | A, B, C |

Metrics reported: answer correctness, citation precision, hallucination rate, correct "not specified in the spec" rate, latency, tokens per answer.

## 7. Benchmark format (what I need from you)

Please prepare 30-50 questions in this shape (a spreadsheet is fine, I will convert it):

| Field | Example (illustrative) |
|-------|-----------------------|
| question | "What is the reset value of CAP.DSTRD?" |
| specs in scope | NVMe 1.4c |
| expected answer | Engineer-written short answer |
| source section(s) | Section ids that justify it |
| type | single-spec, multi-spec, cross-reference, silent-in-spec |

Include at least 5 questions where the spec does **not** give an answer, so we can test the "do not invent" behaviour.

## 8. Risks specific to this phase

| Risk | Mitigation |
|------|-----------|
| Complex .pptx/.xlsx structure | Treat slides/sheets as flat sections first; improve after the quality report |
| Scanned pages | Detect pages with no text layer and report them; OCR added only if the report shows real volume |
| Licence delay for models | Start the 2-week approval for two candidate families now |
| Benchmark too easy | Ask engineers for questions they find hard in daily work |

## 9. Inputs needed to start

1. The sample PDF uploaded here, plus 2-3 other real specs (include one .docx and one .pptx or .xlsx).
2. Python version and Linux distribution of the dedicated server, and whether pip can use an internal mirror.
3. Approval to proceed with Phase 1a work packages 1-3 first (parser on the sample), which carry no model or licence dependency.