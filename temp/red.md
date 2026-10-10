# AI Agents for SSD Firmware Test: Proposal for Approval

Draft v0.1. Figures marked *(estimate)* will be validated before final commitment.

## 1. One-slide summary

Build a secure, fully on-premises AI assistant platform that helps our test and firmware teams (about 500 people) to answer specification questions, find and design test cases, automate tests and analyse failures. No data leaves the company network.

## 2. The problem

- Specifications (NVMe, MCTP, PCIe, PLDM and customer variants, 3-4 GB, many versions) are hard to search and cross-reference by hand.
- Test automation and regression failure analysis consume large amounts of engineer time.
- Public AI services cannot be used because the data is confidential.

## 3. What we will build

| Agent | What it does | Value |
|-------|--------------|-------|
| Technical Agent (first) | Answers questions from the specifications with exact section citations; says so when the spec does not conclude | Faster, consistent spec understanding, fewer misreads |
| Finder Analyser | Searches existing test cases (TestRail) and tickets (Redmine); designs new cases from a checklist | Less duplicate work, better coverage |
| Automation Agent | Turns a test sequence into runnable Pytest + pynvme code, runs it and fixes errors | Faster test development |
| Failure Analysis Agent | Classifies regression failures as script or firmware issue, fixes scripts, narrows down firmware issues | Faster release sign-off |

Users work from a Linux command-line tool first; a richer interactive terminal interface, similar in style to Claude Code, follows later.

## 4. Where we start: the earlier POC (ILA Agent)

The ILA POC proved the idea is feasible but showed clear limits:

| Observed in POC | Result |
|-----------------|--------|
| Simple RAG with 7B models | Vague answers when wording changed |
| Single step with minimal context | A 10-step test needed 20-25 prompts |
| No compile/run feedback | Generated C++ not compilable; ~30% of characters needed editing |

The new design addresses each point: structure-aware spec indexing, a multi-step agent loop, a verifier against hallucination, and run-and-repair for code.

## 5. Approach (non-technical view)

1. Convert every specification into a structured, searchable library that keeps chapters, tables and cross-references.
2. Let the AI look things up step by step, like an engineer following "see section X", across several specifications.
3. Check every claim against the quoted text before showing it. If the specification does not decide the matter, say so and give only the existing guidance.
4. Test three alternative designs against a benchmark of real questions prepared by our engineers, and pick the best on evidence.

## 6. Security and compliance

- Runs entirely on company servers; internet access from the system is blocked.
- Login through existing LDAP; access to each specification is enforced per user at the database level.
- Full audit log of questions and sources, kept on-premises.
- Open-weight AI models only, each reviewed by Legal and Security before use; telemetry disabled and verified.
- Test execution tools run in an isolated sandbox.

## 7. Technical summary (for the technical slide)

- Gateway with authentication and request queue, agent runtime, tool registry, local model server, single PostgreSQL store (vector plus keyword plus metadata plus reference graph).
- Ingestion pipeline for .docx, .pptx, .xlsx, .pdf into section trees with stable citation ids.
- Three Technical Agent approaches compared: A structure-aware hybrid RAG, B agentic retrieval, C hybrid with verifier.
- Details: see `ARCHITECTURE.md`.

## 8. Resources *(estimate)*

| Stage | Hardware | People |
|-------|----------|--------|
| Experiments (now) | Existing 24 GB GPU, 64 GB RAM server | Existing team |
| Pilot (one team) | 1 server, ~48 GB GPU class | To be confirmed |
| Production (~500 users) | 2+ servers, sized after benchmark | To be confirmed |

Hardware is requested only after the experiment phase shows which model size is needed. Software is open source; there are no per-user license fees.

## 9. Roadmap and decision gates

| Phase | Deliverable | Gate to continue |
|-------|-------------|------------------|
| 0 | Design and approval | This document approved |
| 1a | Technical Agent backend, three approaches benchmarked | Accuracy and no-hallucination targets met |
| 1b | Command-line tool (argparse), Docker deployment, LDAP, pilot with one team | Security review passed |
| 2 | Finder Analyser (TestRail, Redmine) | Pilot feedback |
| 3 | Automation Agent (Pytest + pynvme) | Code runs on benchmark tests |
| 4 | Failure Analysis Agent | Classification accuracy |
| 5 | C++ framework, scale-out | Capacity review |

Timelines are intentionally not fixed yet; they will be proposed after Phase 1a experiments.

## 10. Success measures

- Spec answers: correctness, citation accuracy, hallucination rate, correct "not specified" responses on the engineer-prepared benchmark.
- Automation: share of generated tests that compile and run without edits.
- Failure analysis: accuracy of script-vs-firmware classification.
- Adoption: active users and time saved per task (measured in the pilot).

## 11. Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| Parsing quality of complex tables and slides | Quality report and human review before go-live |
| Model accuracy on dense specification language | Benchmark-driven selection, verifier step |
| Model license rejection | Two model families evaluated in parallel |
| Hardware cost | Staged purchases behind gates |

## 12. Decisions requested from management

1. Approve Phase 0 design and Phase 1a experiments on existing hardware.
2. Nominate Legal and Security contacts for model license and architecture review.
3. Agree on spec-benchmark ownership (engineer time to prepare 30-50 questions).
4. Provisional approval to plan pilot hardware after Phase 1a results.

## Appendix: files

- `ARCHITECTURE.md`: full technical design, approaches, sizing, risks.