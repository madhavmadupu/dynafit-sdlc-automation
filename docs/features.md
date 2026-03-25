# DYNAFIT — Features Context
> Antigravity IDE | Project: DYNAFIT Requirement Fitment Engine
> Feature registry, implementation status, acceptance criteria, and roadmap.

---

## Feature Status Legend
- ✅ **DONE** — Implemented and tested
- 🔨 **PARTIAL** — Core logic exists, stubs/integrations missing
- ❌ **NOT BUILT** — Designed but not implemented
- 💡 **PLANNED** — In backlog, design pending

---

## Core Pipeline Features

### F-001: Document Ingestion
**Status:** 🔨 PARTIAL
**Phase:** 1 — Ingestion Agent

**What it does:**
Accepts raw business requirement documents in multiple formats and converts them to structured `RequirementAtom` objects.

**Supported formats:**
- Excel (`.xlsx`, `.xls`) — openpyxl with auto header detection, ALT+ENTER handling
- Word (`.docx`, `.doc`) — Docling primary, Unstructured fallback
- PDF — Docling with OCR, Unstructured fallback
- Plain text / Markdown (`.txt`, `.md`) — paragraph split on double newlines

**Acceptance criteria:**
- [ ] Each source row/paragraph produces at most 1 `PartialAtom` per discrete business need
- [ ] Multi-row compound requirements are split into atomic units by LLM
- [ ] `source_ref` accurately reflects document + row/paragraph location
- [ ] Malformed files do not crash the pipeline (per-file error isolation)

**Missing:**
- `core/prompts/ingestion_extract.j2` — Jinja2 LLM prompt template
- Integration tests with real BRD samples

---

### F-002: Requirement Normalization
**Status:** ✅ DONE
**Phase:** 1 — Ingestion Agent → Normalizer

**What it does:**
- Deduplicates near-identical requirements (RapidFuzz `token_sort_ratio > 90`)
- Maps business jargon to D365 canonical terminology via per-module YAML
- Enriches MoSCoW priority from text signal words

**Key behaviours:**
- Only deduplicates within same module (cross-module identical text is kept)
- On dedup collision, keeps higher `completeness_score`
- MoSCoW enrichment only overrides LLM-assigned `SHOULD` — explicit priorities are preserved
- Term alignment applies case-insensitive regex word-boundary replacement

**Acceptance criteria:**
- [x] "3-way match" → "three-way matching (purchase order)" in AP module
- [x] Near-duplicates within same module collapsed to 1 atom
- [x] "must" / "mandatory" / "critical" in raw text → priority `MUST`

---

### F-003: Requirement Validation & Quality Gating
**Status:** ✅ DONE
**Phase:** 1 — Ingestion Agent → Validator

**What it does:**
Quality gate that hard-rejects or soft-flags atoms before they enter the pipeline.

| Condition | Action |
|---|---|
| text < 10 chars | Hard reject → RejectedAtom |
| completeness_score < 20 | Hard reject → RejectedAtom |
| completeness_score 20–39 | Soft flag → needs_review=True |
| module = UNKNOWN | Soft flag → needs_review=True |
| Schema validation fails | Hard reject → RejectedAtom |

---

### F-004: Hybrid Knowledge Retrieval (RAG)
**Status:** 🔨 PARTIAL
**Phase:** 2 — Knowledge Retrieval Agent

**What it does:**
For each atom, fans out to 3 knowledge sources in parallel and assembles grounded evidence.

**Knowledge Sources:**
1. **D365 Capability KB** (Qdrant) — Vector search (bge-large cosine) + BM25 keyword search, module-filtered, top-20
2. **MS Learn Corpus** (Qdrant) — Semantic search, module-agnostic, top-10
3. **Historical Fitments** (PostgreSQL/pgvector) — Exact hash match OR embedding similarity > 0.75

**Processing pipeline:**
`QueryBuilder` → `ParallelRetriever` → `RRFFusion (k=60)` → `CrossEncoderReranker` → `ContextAssembler` → Redis cache

**Acceptance criteria:**
- [ ] Pipeline produces 1 `RetrievalContext` per atom even if MS Learn / history fail
- [ ] D365 KB failure raises and marks atom as errored (not silently empty)
- [ ] Cache hit skips all retrieval, proceeds to Phase 3
- [ ] Module filter is always applied — no cross-module capability leakage

**Missing:**
- `agents/retrieval/agent.py` — Phase 2 LangGraph orchestration node
- `infrastructure/storage/redis_client.py` — Cache implementation
- `infrastructure/vector_db/pgvector_client.py` — Historical fitment DB queries

---

### F-005: Reciprocal Rank Fusion
**Status:** ✅ DONE
**Phase:** 2 — RRF Fusion

**What it does:**
Merges vector search results and BM25 keyword results into a unified ranked list using RRF formula:
`score(d) = Σ 1/(k + rank(d))` where k=60 (ADR-001 locked).

**Acceptance criteria:**
- [x] Capabilities appearing in both lists get higher fused score
- [x] Top-20 fused capabilities returned (before reranking)
- [x] k=60 constant, not configurable via settings (by design — ADR-001)

---

### F-006: Cross-Encoder Reranking
**Status:** ✅ DONE
**Phase:** 2 — Reranker

**Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2`
**Input:** Top-20 RRF candidates
**Output:** Top-5 by pairwise relevance to requirement text

**Acceptance criteria:**
- [x] Model loaded once via `@lru_cache`, not per-request
- [x] CPU-bound inference runs in thread pool (non-blocking async)
- [x] Single candidate returned as-is (no inference needed)

---

### F-007: Semantic Matching & Confidence Scoring
**Status:** ✅ DONE
**Phase:** 3 — Semantic Matching Agent

**What it does:**
Computes a weighted composite confidence score per atom and assigns routing decision.

**Signals:**
- Cosine similarity (weight: 0.50 default, module YAML can override)
- Term overlap / entity matching (weight: 0.30)
- Historical precedent (weight: 0.20)

**Routing outputs:**
- `FAST_TRACK`: composite ≥ 0.85 + exact history → skip LLM, auto-FIT
- `SOFT_GAP`: composite < 0.40 + no history + no candidates → skip LLM, auto-GAP
- `LLM`: everything else → full chain-of-thought reasoning

**Acceptance criteria:**
- [x] Module YAML weights used when available (AP: cosine 0.50, overlap 0.30, history 0.20)
- [x] Historical weight = 1.0 for exact hash match, best_sim × 0.8 for fuzzy match, 0.0 for none
- [x] AP module uses fast_track_fit=0.82, not global 0.85

---

### F-008: Candidate Ranking & Deduplication
**Status:** ✅ DONE
**Phase:** 3 — Candidate Ranker

**What it does:**
Produces final top-5 `ScoredCandidate` list for Phase 4 context.

**Multi-factor score:**
```
0.5 × (rerank_score / 10)    # Normalized CrossEncoder score
+ 0.25 × cosine_score
+ 0.15 × overlap_score
+ 0.1 × specificity          # Shorter descriptions preferred
+ 0.1 × hist_boost           # If capability was used in prior wave
```

**Dedup rule:** candidates with > 85% word overlap to a higher-ranked candidate are dropped.

---

### F-009: LLM-Based Fitment Classification
**Status:** 🔨 PARTIAL
**Phase:** 4 — Classification Agent

**What it does:**
Core decision-making. Uses claude-3-5-sonnet with chain-of-thought to classify each LLM-routed atom.

**Prompt strategy:**
- System prompt: module identity + localization gap notes from YAML
- User prompt: requirement text + top-5 candidates with scores + up to 3 prior decisions
- Response: structured `<classification>` XML block

**Parse strategy (in order):**
1. XML parse with `xml.etree.ElementTree`
2. Regex field extraction fallback
3. Failure → GAP with `needs_review=True`, `confidence=0.0`

**Business rules enforced post-parse:**
- GAP must have `gap_description`
- PARTIAL_FIT must have `config_needed`
- FIT/PARTIAL_FIT must have `matched_capability`
- Confidence clamped to 0.0–1.0

**Acceptance criteria:**
- [ ] 95%+ of LLM responses parse successfully (monitor `response_parser_total_failure`)
- [ ] FAST_TRACK route never calls LLM (validated by `route_taken == FAST_TRACK`)
- [ ] Pre-flight cost check aborts if projected cost > `MAX_LLM_COST_USD_PER_RUN`
- [ ] Processing errors produce placeholder GAP result (atom never silently dropped)

**Missing:**
- `core/prompts/classification_system.j2`
- `core/prompts/classification_user.j2`

---

### F-010: Post-Classification Sanity Checks
**Status:** ✅ DONE
**Phase:** 4 — Sanity Checker

**Four rules:**
| Rule | Condition | Action |
|---|---|---|
| High score GAP | composite ≥ 0.80 but LLM → GAP | Flag + needs_review |
| Low score FIT | composite ≤ 0.35 but LLM → FIT | Flag + needs_review |
| Confidence divergence | \|llm_conf - composite\| > 0.40 | Flag + needs_review |
| No candidates FIT | candidates empty but FIT | Flag as likely hallucination |

Flags are **additive only** — never auto-reject, always flag for consultant.

---

### F-011: Human-in-the-Loop Review
**Status:** 🔨 PARTIAL
**Phase:** 5 — Validation Agent

**What it does:**
LangGraph `interrupt()` pauses the pipeline before report generation. A consultant reviews flagged items and can override verdicts. Override reason is stored and fed back into historical fitments for future waves.

**Review queue is built from:**
- Atoms with `needs_review=True` (from Phases 1 + 4 sanity flags)
- Atoms involved in cross-requirement conflicts (Phase 5 consistency checker)

**`ConsultantDecision` schema:**
```python
atom_id: UUID
verdict: Verdict         # Override verdict
reason: str              # Required when overriding AI verdict
reviewed_by: str         # Consultant identifier
reviewed_at: datetime
```

**Acceptance criteria:**
- [ ] `interrupt()` always fires when `human_review_required` is non-empty
- [ ] `interrupt()` fires when `conflict_report.error_count > 0` even if no flagged atoms
- [ ] Graph resumes correctly after `PATCH /runs/{id}/review` with decisions
- [ ] Override reason is written to historical fitments for future wave improvement

**Missing:**
- `agents/validation/override_handler.py`
- `PATCH /runs/{id}/review` API endpoint

---

### F-012: Cross-Requirement Conflict Detection
**Status:** ❌ NOT BUILT
**Phase:** 5 — Consistency Checker

**What it does:**
Detects logical inconsistencies across classified requirements.

**Conflict types to detect:**
- **Capability contradiction:** Same D365 capability cited as FIT for Req A but GAP for Req B (similar requirements, different verdicts)
- **Country inconsistency:** Same requirement classified differently for IN vs DE without a localization justification
- **Confidence cluster warning:** > 40% of a module's atoms have confidence < 0.5 (possible KB data gap)
- **Dependency conflict:** Req A is FIT (requires feature X) but Req B is GAP (disables feature X)

**Output:** `ConflictReport` with list of `ConflictEntry` objects (severity: ERROR or WARNING)

**Libraries:** NetworkX DiGraph for dependency analysis, YAML rule engine for country overrides

**File to build:** `agents/validation/consistency_checker.py`

```python
class ConsistencyChecker:
    def check(
        self,
        results: list[ClassificationResult],
        atoms: dict[UUID, RequirementAtom],
    ) -> ConflictReport:
        ...
```

---

### F-013: Fitment Matrix Excel Output
**Status:** ❌ NOT BUILT
**Phase:** 5 — Report Generator

**What it does:**
Generates the `fitment_matrix.xlsx` file using openpyxl with branded styling.

**Sheets to generate:**
1. **Fitment Matrix** — Main output: req ID, text, module, priority, verdict, confidence, matched capability, gap description, config needed, rationale, caveats, source ref
2. **Audit Trail** — Full history of AI decisions + consultant overrides
3. **Conflict Report** — Cross-requirement conflicts with severity + suggested resolution
4. **Summary Stats** — FIT/PARTIAL_FIT/GAP counts per module, total LLM cost, run metadata

**Acceptance criteria:**
- [ ] Conditional formatting: FIT = green, PARTIAL_FIT = amber, GAP = red
- [ ] Each row links to source document + row reference
- [ ] Override rows show original AI verdict and consultant override reason
- [ ] File path returned as `output_path` in state

**File to build:** `agents/validation/report_generator.py`

---

### F-014: Module-Specific Configuration
**Status:** 🔨 PARTIAL

**What it does:**
Per-module YAML files drive: signal weights, threshold overrides, localization gap notes, canonical term mappings, sub-module taxonomy.

**Built:**
- `ap.yaml` — Full AP module configuration with IN/DE/FR/BR gaps and 25+ canonical term mappings

**Missing YAMLs to build:**
| Module | Priority | Key Gaps to Document |
|---|---|---|
| `gl.yaml` | HIGH | IFRS16, FEC (France), GoBD, consolidation |
| `ar.yaml` | HIGH | e-invoicing mandates by country, SEPA Direct Debit |
| `scm.yaml` | HIGH | Trade agreement complexity, drop-ship scenarios |
| `wms.yaml` | MEDIUM | Advanced warehousing license requirements |
| `mfg.yaml` | MEDIUM | Lean manufacturing, production floor execution |
| `tax.yaml` | HIGH | GST/VAT localization complexity per country |
| `hr.yaml` | LOW | Payroll localization (mostly ISV territory) |
| `cash.yaml` | MEDIUM | Bank statement formats (MT940, BAI2) |

---

### F-015: FastAPI Application Layer
**Status:** ❌ NOT BUILT

**Endpoints to build:**
```
POST   /runs                    # Create new pipeline run (upload files)
GET    /runs/{id}               # Get run status + summary stats
GET    /runs/{id}/results       # Get classification results
PATCH  /runs/{id}/review        # Submit consultant decisions (resumes graph)
GET    /runs/{id}/download      # Download fitment_matrix.xlsx
GET    /health                  # Infrastructure health check
```

**Key implementation notes:**
- `POST /runs` saves uploaded files to `UPLOAD_DIR`, enqueues via Celery or asyncio background task
- `PATCH /runs/{id}/review` calls `graph.ainvoke({consultant_decisions: [...]}, config)` to resume from interrupt
- All routes require API key auth (rate limited to 10/hour per `API_RATE_LIMIT_PER_HOUR`)
- `GET /runs/{id}` returns `RunStatus` enum value + phase-level progress

---

### F-016: LangSmith Tracing Integration
**Status:** ✅ DONE (optional)

**What it does:**
When `LANGCHAIN_API_KEY` is set, all LLM calls are traced in LangSmith with run_id metadata.

**Activation:** Set `LANGCHAIN_API_KEY` and `LANGCHAIN_PROJECT` in `.env`
**Graceful degradation:** If LangSmith errors or is not installed, LLM call proceeds normally.

---

### F-017: LLM Cost Guard
**Status:** ✅ DONE
**Phase:** 4 — Pre-flight check in `agent_phase_4.py`

**What it does:**
Before executing LLM calls for a run, samples up to 20 atoms to estimate total cost. Aborts with `LLMCostLimitError` if projected cost exceeds `MAX_LLM_COST_USD_PER_RUN`.

**Configuration:** `MAX_LLM_COST_USD_PER_RUN=5.00` in settings.

---

### F-018: Historical Fitment Feedback Loop
**Status:** 🔨 PARTIAL

**What it does:**
Consultant override decisions are written back to the `historical_fitments` PostgreSQL table. Future waves for the same or similar requirements benefit from this accumulated precedent — the `historical_weight` signal in Phase 3 improves accuracy over time.

**Built:** Override audit trail captured in Phase 5 state
**Missing:** `override_handler.py` write-back to PostgreSQL + `pgvector_client.py`

---

## Planned Features (Backlog)

### F-019: Multi-Wave Comparison
**Status:** 💡 PLANNED
Compare fitment results across multiple implementation waves for the same client. Show verdict drift, confidence improvements from historical learning.

### F-020: KB Admin Interface
**Status:** 💡 PLANNED
Web UI for managing the D365 capability knowledge base — add/update/delete capabilities, view embedding coverage by module, trigger re-ingestion.

### F-021: Batch Re-classification
**Status:** 💡 PLANNED
Re-run Phase 4 only (skip Phases 1-3) when the LLM model is upgraded or prompts are changed, without re-ingesting documents or re-running retrieval.

### F-022: Confidence Calibration Dashboard
**Status:** 💡 PLANNED
Grafana dashboard showing: verdict distribution by module, sanity flag rate, FAST_TRACK rate, consultant override rate, LLM cost per run trend.

### F-023: Localization Gap Suggestions
**Status:** 💡 PLANNED
When a requirement is classified as GAP with a country tag, suggest relevant ISV solutions or Microsoft AppSource apps known to address that gap.

### F-024: Requirement Completeness Feedback
**Status:** 💡 PLANNED
In the output report, surface the top N requirements with low `completeness_score` and suggest how to make them more specific (e.g. "Add volume/frequency, define exception handling, specify country scope").

---

## Acceptance Test Scenarios

### Happy Path (End-to-End)
```
Input:  AP BRD with 50 requirements (Excel)
Expect: 
  - ~45 atoms after dedup/validation
  - All 45 have RetrievalContext with top_capabilities
  - ~20 FAST_TRACK, ~25 LLM-classified
  - FIT ~55%, PARTIAL_FIT ~25%, GAP ~20%
  - fitment_matrix.xlsx generated with 4 sheets
  - Total LLM cost < $1.00
```

### Localization Gap Path
```
Input:  AP requirement mentioning "TDS 194Q withholding" with country=IN
Expect: 
  - System prompt includes India AP gap note about TDS 194Q
  - Classification = GAP or PARTIAL_FIT
  - gap_description mentions TDS/custom development
  - Sanity flags empty (this is expected behaviour)
```

### Human Override Path
```
Input:  Requirement classified as GAP by LLM
Action: Consultant overrides to PARTIAL_FIT with reason
Expect:
  - validated_batch.override_count = 1
  - audit_trail has ConsultantDecision entry
  - fitment_matrix.xlsx shows original GAP + override reason
  - historical_fitments table updated for future waves
```

### Infrastructure Failure Path
```
Input:  MS Learn Qdrant collection down
Expect:
  - ms_learn_retrieval_failed warning logged
  - Pipeline continues with ms_learn=[] in context
  - sources_available does NOT include "ms_learn"
  - Classification still proceeds with D365 KB + history only
```

### Cost Limit Path
```
Input:  BRD with 2000 requirements
Expect:
  - Phase 4 preflight estimates cost > $5.00
  - LLMCostLimitError raised before any LLM calls
  - State preserved — user can increase limit and retry
```