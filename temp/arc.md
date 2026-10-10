# Architecture: Local AI Agent Platform for SSD Firmware Test (Phase 0 draft)

Status: DRAFT for review. Numbers marked **(estimate)** must be validated by experiment before they are committed to management.

## 1. Goals and hard constraints

| # | Constraint | Design consequence |
|---|-----------|--------------------|
| C1 | All data is confidential; a breach is a serious offence | Fully on-prem, no outbound internet from runtime, no telemetry, no external API |
| C2 | ~500 users, growing | Stateless gateway, queued inference, horizontally scalable model servers |
| C3 | Use resources only if mandatory | Fewest moving parts: one database, one model server per tier, no extra clusters until measured need |
| C4 | Spec answers must not hallucinate | Every claim cited to a section; verifier step; explicit "not concluded by spec" outcome |
| C5 | Terminal UI on Linux, backend first | Backend exposes an HTTP + streaming API; UI is a thin client |
| C6 | Four agents over time | One shared platform; agents are configurations of a common runtime |

## 2. Lessons from the ILA POC (baseline to beat)

| ILA POC behaviour | Root cause | Platform answer |
|-------------------|-----------|-----------------|
| Vague output when prompt wording varies | Single-shot retrieval on raw text chunks | Structure-aware index, query rewriting, multi-hop retrieval |
| One step, minimal context | No agent loop or memory | Planner/executor loop with working memory |
| 10-step test needed 20-25 prompts | No plan, user feeds steps one by one | Whole-sequence planning, step decomposition by the agent |
| Code ~30% off, not compilable | No compile/run feedback | Execute, read logs, repair loop (Automation Agent, later) |
| 7B models, simple RAG | Model and retrieval both weak | Larger model tier (see section 8) plus verifier |

## 3. Platform overview

```
 Terminal UI (Linux)        <- Phase 1b, thin client
        |  HTTPS + SSE streaming
 +------v------------------------------------------------+
 | API Gateway (FastAPI)                                   |
 |  - LDAP auth, per-user spec entitlements (ACL)          |
 |  - request queue, rate limits, audit log                |
 +------+------------------------------------------------+
        |
 +------v------------------+    +--------------------------+
 | Agent Runtime           |    | Tool Registry            |
 |  - agent loop (plan/act)|--->|  spec_search, spec_read, |
 |  - session memory       |    |  ref_follow, glossary,   |
 |  - verifier             |    |  testrail, redmine,      |
 +------+------------------+    |  pynvme_runner (later)   |
        |                       +--------------------------+
 +------v------------------+    +--------------------------+
 | LLM Serving             |    | Knowledge Store          |
 |  - generator model      |    |  PostgreSQL:             |
 |  - embedding + reranker |    |   pgvector + full-text   |
 +-------------------------+    |   + reference graph tbls |
                                +--------------------------+
 Offline: Ingestion pipeline (docx/pptx/xlsx/pdf -> structured sections)
```

Rationale for PostgreSQL as the single store: it provides vector search (pgvector), keyword search (full-text), relational metadata (product, version, ACL) and a reference graph in one service that the company can already back up and secure. Add a dedicated vector DB only if measurements show a need.

## 4. Security design

1. **Network**: runtime hosts have egress denied by firewall. Model weights and packages enter via a reviewed internal mirror and are pinned with checksums.
2. **Telemetry**: every library is configured with telemetry and analytics disabled and verified by a packet-capture test during acceptance.
3. **Identity**: LDAP login; the gateway maps LDAP groups to spec entitlements.
4. **Authorization at retrieval time**: the ACL filter is applied inside the database query, so a model can never be handed text the user may not see. This matters most for the "some users have all specs" case.
5. **Audit**: who asked what, which sections were retrieved, which answer returned. Logs stay on-prem and are access-controlled.
6. **Isolation**: services in containers or systemd units with least privilege; tool execution (pynvme, code run) in a separate sandbox, never in the gateway process.
7. **Data in prompts**: no user content is sent anywhere outside the host cluster.

## 5. Ingestion pipeline (Technical Agent foundation)

Input: .docx, .pptx, .xlsx, .pdf, about 3-4 GB, multiple products, customers, form factors, versions.

Steps:

1. **Catalog**: assign each file `spec_family` (NVMe, MCTP, PCIe, PLDM...), `version`, `product/customer/form_factor`, `confidentiality`, `acl_group`.
2. **Parse to a structure tree**, not flat chunks: chapters, sections, numbered requirements, tables (kept as tables), figures (caption plus nearby text), footnotes.
3. **Section identity**: stable id such as `NVMe-2.1/§5.2.1`, so citations are exact.
4. **Reference graph**: detect "see section X", "as defined in Figure Y", "refer to MCTP spec §Z" and store as edges. Cross-document references link to the target spec and version where it is in the corpus.
5. **Glossary and term map**: extract definitions (e.g. "Controller", "Namespace") per spec so that identical words with different technical meanings are disambiguated by spec context.
6. **Indexing**: each section gets an embedding, a keyword index entry and parent/child links. Tables are indexed as rows plus a header summary.
7. **Quality report**: parse failures, scanned pages needing OCR, empty tables, unresolved references. A human reviews this before a spec goes live.

Open item: scanned PDFs may need local OCR, which adds a component. Confirm whether any exist (see questions).

## 6. Technical Agent: candidate approaches to experiment with

All three share the ingestion pipeline and the same benchmark, so the comparison is fair.

### Approach A: Structure-aware hybrid RAG (baseline-plus)
Query -> hybrid (keyword + vector) retrieval within the user-selected specs -> rerank -> expand each hit with parent heading and its referenced sections one hop -> generate with citations.
- Pros: fast, simple, cheap per query.
- Cons: multi-hop reasoning is limited by the fixed expansion rule.

### Approach B: Agentic retrieval loop
The model is given tools (`spec_search`, `spec_read(section)`, `ref_follow`, `glossary`) and iterates: search, read, follow references, search other specs, until it has enough evidence or declares insufficiency. Output must cite section ids.
- Pros: handles chains of references and combinations of several specs.
- Cons: slower, more tokens, needs a model strong at tool use.

### Approach C: Hybrid with verifier (expected best candidate)
Approach A for the first pass, escalating to the Approach B loop when evidence is incomplete, followed by a **verifier** that splits the answer into claims and checks each claim against the quoted source text. Unsupported claims are removed or the answer becomes "not concluded by the specification", followed by closest available guidance as the requirement states.
- Pros: best protection against hallucination, controlled latency.
- Cons: most components to build and tune.

### Experiment design
- Benchmark: 30-50 questions from you at start, grown to 100+. Include single-spec, multi-spec, cross-reference and "spec is silent" questions.
- Metrics: answer correctness, citation precision (does the cited section really support the claim), hallucination rate, correct abstention rate, latency, tokens per answer.
- Decision rule (proposal): choose the approach with the lowest hallucination rate that meets the latency target. Targets to be agreed with you.

## 7. Agent runtime and orchestration

- A small, explicit **agent loop**: plan, call tool, observe, update memory, finish or ask the user. Written in-house or on a thin library; the choice (custom vs LangGraph-style library) is itself a Phase 1 experiment, judged on debuggability and offline operation.
- **Session memory** keeps the confirmed context (spec set, version, prior answers) so the user does not repeat inputs.
- **Tools are contracts**: JSON schema in/out, timeouts, permission scope. The same registry later serves the Automation, Failure Analysis and Finder agents (pynvme runner, TestRail, Redmine).
- **Human-in-the-loop**: the agent asks when scope is ambiguous (which spec version?) instead of guessing.

## 8. Model and hardware sizing

Dev hardware today: 1 GPU with 24 GB VRAM, 64 GB RAM.

What fits on 24 GB (estimate): a 14B-class open-weight model in 4-bit or 8-bit with room for context, or a ~30B-class model in 4-bit with limited context. An embedding model and a reranker are small and can share the GPU or run on CPU for development.

| Tier | Purpose | Indicative hardware (estimate) | Validate by |
|------|---------|-------------------------------|-------------|
| Dev | Experiments A/B/C, benchmark | Current 24 GB GPU, 64 GB RAM | Benchmark runs |
| Pilot | 20-50 users, one team | 1 server, 1x 48 GB class GPU (or 2x 24 GB) | Load test with queue |
| Production | ~500 users | 2+ servers, GPUs sized to chosen model; gateway and DB on separate hosts | Measured concurrency |

Sizing logic: assume 5-10% of 500 users active at peak, so 25-50 concurrent sessions **(assumption, to be measured)**. With a queue and continuous batching on the model server, fewer GPUs than one-per-user are needed. Final purchase request should come only after Dev-tier results show which model size meets the benchmark.

Candidate open-weight families (each needs legal/security license review): Qwen, Llama, Mistral and similar for generation; BGE-class models for embeddings and reranking. License terms differ per model and per size, so verify each before adoption.

Serving: llama.cpp-style server for dev; a batching server (vLLM-style) for pilot/production. Both run fully offline.

## 9. Terminal UI (Phase 1b)

- Client in Python (Textual/Rich) or Node (Ink), chosen in a small spike. Linux only.
- Features: login, choose product/spec/version scope, chat with streamed answers, clickable-style citations (section id plus quoted text), session history, slash commands (`/scope`, `/sources`, `/export`).
- The UI holds no business logic, so a web UI could be added later without backend change.

## 10. Roadmap and approval gates

| Phase | Output | Gate |
|-------|--------|------|
| 0 | This design, README for management, hardware ask | Management approval |
| 1a | Ingestion pipeline plus Approaches A/B/C on 15-20 specs, benchmark report | Hallucination and correctness targets met |
| 1b | Gateway, LDAP, ACL, terminal UI, pilot with one team | Security review passed |
| 2 | Finder Analyser (TestRail, Redmine) | Reuses platform tools |
| 3 | Automation Agent (Pytest + pynvme) with run-and-repair loop | Compile/run success rate on benchmark tests |
| 4 | Failure Analysis Agent | Script-vs-firmware classification accuracy |
| 5 | C++ framework support; scale-out | Capacity review |

## 11. Risks

| Risk | Mitigation |
|------|-----------|
| Spec parsing quality (tables, figures, PPT) | Quality report, human review before go-live |
| Model quality on dense spec language | Benchmark-driven model choice; verifier |
| License or security rejection of a model | Evaluate two model families in parallel |
| Hardware budget | Stage purchases behind gates |
| Spec updates | Versioned ingestion; re-index per version |

## 12. Open questions

1. Are any specs scanned images (OCR needed)?
2. Where do spec files live today (shared drive, Git, SharePoint-like)? Can the ingestion host read them?
3. Is Docker/Podman allowed on the target Linux servers, or only native services?
4. Which Linux distribution and GPU vendor on the deployment side?
5. Who approves model licenses (legal, security) and how long does that take?