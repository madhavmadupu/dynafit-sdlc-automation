# DYNAFIT — Requirement Fitment Engine
## Master AGENT.md — Read this first, every time.

---

## 1. PROJECT IDENTITY

**What DYNAFIT is:**
DYNAFIT is an AI-powered multi-agent system that automates the fitment analysis of business requirements against Microsoft Dynamics 365 Finance & Operations (D365 F&O) standard capabilities. It determines whether each business requirement is a FIT (covered out-of-the-box), PARTIAL FIT (needs configuration), or GAP (requires custom development).

**Why it exists:**
D365 F&O implementation projects involve hundreds to thousands of business requirements. Manually assessing each one against D365 capabilities is time-consuming, inconsistent across consultants, and error-prone. DYNAFIT reduces this from weeks to hours while producing auditable, consistent decisions.

**Output:**
A `fitment_matrix.xlsx` file classifying every requirement as FIT / PARTIAL FIT / GAP with LLM-generated rationale, confidence scores, and an audit trail. This feeds downstream into FDD FOR FITS and FDD FOR GAPS documentation modules.

---

## 2. SYSTEM ARCHITECTURE OVERVIEW

DYNAFIT is a **5-phase multi-agent pipeline** orchestrated via LangGraph StateGraph.

```
[Raw Documents]
      │
      ▼
┌─────────────────┐
│  Phase 1        │  Ingestion Agent
│  Ingestion      │  Parses raw BRDs → structured RequirementAtoms
└────────┬────────┘
         │ 265 RequirementAtom objects (typical)
         ▼
┌─────────────────┐
│  Phase 2        │  Knowledge Retrieval Agent (RAG)
│  RAG Retrieval  │  Hybrid search across 3 knowledge sources
└────────┬────────┘
         │ RetrievalContext per atom
         ▼
┌─────────────────┐
│  Phase 3        │  Semantic Matching Agent
│  Semantic Match │  Cosine similarity + confidence scoring
└────────┬────────┘
         │ MatchResult per atom (scored + ranked candidates)
         ▼
┌─────────────────┐
│  Phase 4        │  Classification Agent (LLM Reasoning)
│  Classification │  Chain-of-thought → FIT / PARTIAL / GAP
└────────┬────────┘
         │ ClassificationResult per atom
         ▼
┌─────────────────┐
│  Phase 5        │  Validation & Output Agent
│  Validation     │  Consistency checks + human review + Excel report
└────────┬────────┘
         │
         ▼
  fitment_matrix.xlsx → FDD FOR FITS / FDD FOR GAPS
```

**Orchestration layer:** LangGraph `StateGraph` with a typed `RequirementState` dict flowing between nodes. Supports checkpointing, `interrupt()` for human-in-the-loop, and conditional routing.

---

## 3. AGENT RESPONSIBILITIES AT A GLANCE

| Phase | Agent | Input | Output | Key Libraries |
|-------|-------|-------|--------|---------------|
| 1 | Ingestion | Raw docs (Excel/Word/transcripts) | `List[RequirementAtom]` | Docling, Unstructured, spaCy, Pydantic v2, RapidFuzz, FAISS |
| 2 | RAG Retrieval | `RequirementAtom` | `RetrievalContext` | Qdrant, bge-large, pgvector, rank_bm25, CrossEnc |
| 3 | Semantic Matching | `RetrievalContext` | `MatchResult` | sentence-transformers, numpy, scikit-learn, spaCy |
| 4 | Classification | `MatchResult` | `ClassificationResult` | LangChain, Pydantic, Jinja2, tiktoken, LangSmith |
| 5 | Validation | `List[ClassificationResult]` | `fitment_matrix.xlsx` | NetworkX, PostgreSQL, openpyxl, Prometheus, Grafana |

---

## 4. CRITICAL INVARIANTS — NEVER VIOLATE THESE

These are non-negotiable rules the agent must enforce in all code it writes or modifies:

### 4.1 Data Contracts
- **Every inter-agent data structure MUST be a Pydantic v2 model** defined in `core/schemas/`. No ad-hoc dicts crossing phase boundaries.
- **`RequirementState` is the single source of truth** flowing through LangGraph. Never mutate it in place; always return a new partial dict from each node.
- **Schema changes require a migration record** in `docs/architecture/schema_changelog.md`.

### 4.2 LLM Usage
- **All LLM prompts live in `core/prompts/`** as Jinja2 templates. No f-strings or hardcoded prompts in agent code.
- **Every LLM call must be wrapped in the `llm_call()` utility** from `infrastructure/llm/client.py` — this enforces retry logic, token counting, cost tracking, and LangSmith tracing.
- **Structured output is mandatory for Phase 4.** The classification agent MUST parse LLM output via Pydantic — never trust raw LLM strings.
- **Always count tokens before making large batch LLM calls.** Use `tiktoken` to estimate cost. Abort if projected cost exceeds `config.MAX_LLM_COST_USD_PER_RUN`.

### 4.3 State & Checkpointing
- **LangGraph checkpointing is always ON.** Every run gets a `thread_id` UUID. Never disable checkpointing even in dev.
- **Phase 5 MUST use `interrupt()`** for human-in-the-loop. Auto-approval of classifications is only allowed when `confidence >= 0.85` AND `historical_precedent_exists == True`.
- **All consultant overrides MUST be written to `historical_fitments` DB** via the feedback writer. This is how the system learns.

### 4.4 Retrieval
- **Vector search and BM25 are always run in parallel**, never one-or-the-other. Use RRF fusion to merge results.
- **Always retrieve from all 3 knowledge sources**: D365 capability KB, MS Learn corpus, historical fitments. Missing a source is a hard error, not a warning.
- **Top-K for final candidates = 5.** Top-20 from each source → RRF fusion → top-20 → cross-encoder rerank → top-5. Do not shortcut this pipeline.

### 4.5 Confidence Thresholds
```python
CONFIDENCE_THRESHOLDS = {
    "fast_track_fit": 0.85,   # Auto-FIT with historical precedent
    "llm_reasoning": 0.60,    # Route to Phase 4 LLM
    "likely_gap": 0.60,       # Below this = likely GAP (still runs Phase 4)
}
```
These values are in `core/config/thresholds.py`. **Never hardcode them in agent logic.**

### 4.6 Error Handling
- **Never silently swallow exceptions.** Every caught exception must be logged with `structlog` at ERROR level with full context.
- **Phase-level retries**: Each phase retries up to 3 times with exponential backoff. After 3 failures, the `RequirementAtom` is flagged as `status=ERROR` and continues through the pipeline (does not block others).
- **Batch processing**: Requirements are processed in batches of 50. A single requirement failure cannot abort the batch.

### 4.7 Testing
- **Every new function requires a unit test.** No exceptions. Coverage threshold: 85% minimum.
- **Every agent requires an integration test** that runs the full agent in isolation with fixture data.
- **Prompt changes require a regression test** run against the golden eval set in `tests/fixtures/golden_fitments.json`.

---

## 5. FOLDER STRUCTURE

```
dynafit/
├── AGENT.md                          ← YOU ARE HERE (master context)
├── README.md                         ← Human-facing project overview
├── pyproject.toml                    ← Dependencies, tooling config
├── .env.example                      ← All env vars documented
├── docker-compose.yml                ← Local dev stack
│
├── agents/                           ← One folder per phase agent
│   ├── AGENT.md                      ← Agent layer rules
│   ├── ingestion/
│   │   ├── AGENT.md
│   │   ├── agent.py                  ← LangGraph node entry point
│   │   ├── doc_parser.py             ← Format detection + extraction
│   │   ├── req_extractor.py          ← LLM-based atomization
│   │   ├── normalizer.py             ← Dedup + term alignment
│   │   └── validator.py              ← Schema + completeness check
│   ├── retrieval/
│   │   ├── AGENT.md
│   │   ├── agent.py
│   │   ├── query_builder.py          ← Atom → dense + sparse query
│   │   ├── parallel_retriever.py     ← Fan-out to 3 sources
│   │   ├── rrf_fusion.py             ← Reciprocal rank fusion
│   │   ├── reranker.py               ← CrossEncoder reranking
│   │   └── context_assembler.py      ← Merge into RetrievalContext
│   ├── matching/
│   │   ├── AGENT.md
│   │   ├── agent.py
│   │   ├── embedding_match.py        ← Cosine + entity overlap
│   │   ├── confidence_scorer.py      ← Threshold + band assignment
│   │   └── candidate_ranker.py       ← Top-K with historical boost
│   ├── classification/
│   │   ├── AGENT.md
│   │   ├── agent.py
│   │   ├── prompt_builder.py         ← Jinja2 prompt assembly
│   │   ├── llm_classifier.py         ← LLM call + structured parse
│   │   ├── response_parser.py        ← XML → Pydantic with fallback
│   │   └── sanity_checker.py         ← Score-vs-classification check
│   └── validation/
│       ├── AGENT.md
│       ├── agent.py
│       ├── consistency_checker.py    ← Cross-req conflict detection
│       ├── human_review.py           ← LangGraph interrupt handler
│       ├── override_handler.py       ← Capture + write to history
│       └── report_generator.py       ← Excel output + audit trail
│
├── core/                             ← Shared, agent-agnostic code
│   ├── AGENT.md
│   ├── state/
│   │   ├── AGENT.md
│   │   ├── graph.py                  ← LangGraph StateGraph definition
│   │   └── requirement_state.py      ← Typed RequirementState dict
│   ├── schemas/
│   │   ├── AGENT.md
│   │   ├── requirement_atom.py       ← RequirementAtom Pydantic model
│   │   ├── retrieval_context.py      ← RetrievalContext model
│   │   ├── match_result.py           ← MatchResult model
│   │   ├── classification_result.py  ← ClassificationResult model
│   │   └── fitment_batch.py          ← ValidatedFitmentBatch model
│   ├── config/
│   │   ├── AGENT.md
│   │   ├── settings.py               ← Pydantic Settings (env-driven)
│   │   ├── thresholds.py             ← Confidence + routing thresholds
│   │   └── module_config/            ← Per-D365-module YAML configs
│   │       ├── ap.yaml
│   │       ├── ar.yaml
│   │       ├── gl.yaml
│   │       └── scm.yaml
│   └── prompts/
│       ├── AGENT.md
│       ├── classification_system.j2  ← Phase 4 system prompt template
│       ├── classification_user.j2    ← Phase 4 user prompt template
│       ├── ingestion_extract.j2      ← Phase 1 extraction prompt
│       └── ingestion_normalize.j2    ← Phase 1 normalization prompt
│
├── infrastructure/                   ← External service clients
│   ├── AGENT.md
│   ├── vector_db/
│   │   ├── AGENT.md
│   │   ├── qdrant_client.py          ← Qdrant operations wrapper
│   │   ├── pgvector_client.py        ← Historical fitments in PG
│   │   └── embedder.py               ← bge-large embedding wrapper
│   ├── llm/
│   │   ├── AGENT.md
│   │   ├── client.py                 ← llm_call() with retry + tracing
│   │   └── cost_tracker.py           ← Token count + USD estimation
│   └── storage/
│       ├── AGENT.md
│       ├── redis_client.py           ← Cache + Celery broker
│       └── postgres_client.py        ← Audit trail + history writes
│
├── knowledge_base/                   ← KB ingestion and management
│   ├── AGENT.md
│   ├── d365_capabilities/
│   │   ├── AGENT.md
│   │   ├── ingest_capabilities.py    ← Upsert D365 caps to Qdrant
│   │   └── capabilities_schema.py    ← D365Capability Pydantic model
│   ├── ms_learn/
│   │   ├── AGENT.md
│   │   ├── ingest_ms_learn.py        ← Crawl + chunk + embed MS Learn
│   │   └── chunker.py                ← Doc chunking strategy
│   └── historical_fitments/
│       ├── AGENT.md
│       ├── ingest_history.py         ← Load prior wave decisions
│       └── history_schema.py         ← HistoricalFitment model
│
├── api/                              ← FastAPI service layer
│   ├── AGENT.md
│   ├── main.py                       ← App factory
│   ├── routers/
│   │   ├── runs.py                   ← POST /runs, GET /runs/{id}
│   │   └── review.py                 ← PATCH /runs/{id}/review
│   ├── dependencies.py               ← DI: DB sessions, LangGraph
│   └── middleware.py                 ← Auth, rate limit, request ID
│
├── tests/
│   ├── AGENT.md                      ← Testing rules + patterns
│   ├── unit/
│   │   ├── agents/                   ← Unit tests per agent module
│   │   ├── core/                     ← Schema + config + state tests
│   │   └── infrastructure/           ← Mocked client tests
│   ├── integration/
│   │   ├── test_ingestion_agent.py
│   │   ├── test_retrieval_agent.py
│   │   ├── test_matching_agent.py
│   │   ├── test_classification_agent.py
│   │   └── test_validation_agent.py
│   ├── e2e/
│   │   └── test_full_pipeline.py     ← Full run with sample BRD
│   └── fixtures/
│       ├── sample_brd.xlsx           ← Sample business requirements
│       ├── golden_fitments.json      ← Ground truth for eval
│       └── mock_d365_capabilities.json
│
├── docs/
│   ├── architecture/
│   │   ├── overview.md
│   │   ├── data_flow.md
│   │   ├── schema_changelog.md       ← REQUIRED for all schema changes
│   │   └── adr/                      ← Architecture Decision Records
│   │       └── ADR-001-langgraph.md
│   ├── agents/                       ← Per-agent deep-dive docs
│   ├── api/                          ← OpenAPI + usage examples
│   └── runbooks/                     ← Ops runbooks
│
├── scripts/
│   ├── setup_vector_db.py            ← Init Qdrant collections
│   ├── ingest_knowledge_base.py      ← Full KB ingestion pipeline
│   ├── run_eval.py                   ← Eval against golden set
│   └── export_fitment_matrix.py      ← Manual re-export trigger
│
└── monitoring/
    ├── prometheus.yml
    ├── grafana_dashboard.json
    └── alerts.yml
```

---

## 6. DATA FLOW — CANONICAL OBJECT LIFECYCLE

```
Raw document
    │
    ▼ Phase 1
RequirementAtom {
    id: UUID
    text: str                    # normalized, unambiguous
    module: D365Module           # AP | AR | GL | SCM | ...
    priority: MoSCoW             # MUST | SHOULD | COULD | WONT
    country: str | None
    intent: IntentType           # FUNCTIONAL | NFR
    completeness_score: float    # 0-100
    source_ref: str              # origin doc + row/para
}
    │
    ▼ Phase 2
RetrievalContext {
    atom: RequirementAtom
    top_capabilities: List[D365Capability]   # top-5 after rerank
    ms_learn_refs: List[DocChunk]            # top-3
    prior_fitments: List[HistoricalFitment]  # matching history
    confidence_signals: dict                 # raw retrieval scores
}
    │
    ▼ Phase 3
MatchResult {
    atom_id: UUID
    candidates: List[ScoredCandidate]        # ranked top-5
    composite_score: float                   # 0.0-1.0
    confidence_band: ConfidenceBand          # HIGH | MED | LOW
    route_decision: RouteDecision            # FAST_TRACK | LLM | GAP
    similarity_vectors: dict                 # diagnostic
}
    │
    ▼ Phase 4
ClassificationResult {
    atom_id: UUID
    verdict: Verdict                         # FIT | PARTIAL_FIT | GAP
    confidence: float
    matched_capability: str | None
    gap_description: str | None
    config_needed: str | None
    rationale: str                           # LLM explanation
    caveats: List[str]
    llm_model: str
    prompt_tokens: int
    completion_tokens: int
}
    │
    ▼ Phase 5
ValidatedFitmentBatch {
    run_id: UUID
    results: List[ClassificationResult]     # post human review
    overrides: List[ConsultantOverride]
    conflict_report: ConflictReport
    audit_trail: List[AuditEntry]
    output_path: Path                        # fitment_matrix.xlsx
}
```

---

## 7. DEVELOPMENT WORKFLOW

### Before writing any code:
1. Check if the function/class belongs in `agents/`, `core/`, or `infrastructure/` — wrong placement is a hard review failure.
2. Check `core/schemas/` to see if the data model you need already exists.
3. Check `core/prompts/` before writing any LLM prompt.

### When adding a new feature:
1. Define/update the Pydantic schema first (in `core/schemas/`)
2. Write the unit tests (in `tests/unit/`)
3. Implement the feature
4. Write or update the integration test
5. Update relevant `docs/` files
6. If schema changed: add entry to `docs/architecture/schema_changelog.md`

### When modifying prompts:
1. Edit the `.j2` template in `core/prompts/`
2. Run `scripts/run_eval.py` against golden set
3. If accuracy drops > 2%: do NOT merge — investigate and revise
4. Document change in `docs/agents/classification.md`

### Commit message format:
```
[phase|core|infra|test|docs]: short description

- Detail 1
- Detail 2

Refs: #issue-number
```

---

## 8. ENVIRONMENT & CONFIGURATION

All configuration is driven by environment variables, loaded via `core/config/settings.py` (Pydantic Settings). See `.env.example` for all required vars.

**Key config groups:**
- `LLM_*` — model selection, temperature, max tokens, cost limits
- `QDRANT_*` — host, port, collection names
- `POSTGRES_*` — connection string for audit trail + history
- `REDIS_*` — cache + Celery broker
- `CONFIDENCE_*` — threshold overrides (normally use defaults)
- `BATCH_SIZE` — requirements per processing batch (default: 50)
- `MAX_LLM_COST_USD_PER_RUN` — safety cap (default: $5.00)

---

## 9. OBSERVABILITY

- **Structured logging**: All logs via `structlog` with JSON output. Every log entry includes `run_id`, `phase`, `atom_id` (where applicable).
- **Tracing**: LangSmith for LLM call traces. Every `llm_call()` auto-traces.
- **Metrics**: Prometheus counters/histograms exposed at `/metrics`. Grafana dashboard in `monitoring/`.
- **Key metrics to monitor**:
  - `dynafit_requirements_processed_total` (by phase, status)
  - `dynafit_classification_verdict_total` (by verdict)
  - `dynafit_llm_cost_usd_total`
  - `dynafit_phase_duration_seconds` (histogram, by phase)
  - `dynafit_human_overrides_total`

---

## 10. KNOWN RISKS & MITIGATIONS

| Risk | Mitigation |
|------|------------|
| LLM hallucination on classification | Structured output + sanity checker + human review |
| Prompt injection via BRD content | Input sanitization in ingestion agent; prompt has clear delimiters |
| Cost overrun on large batches | `MAX_LLM_COST_USD_PER_RUN` hard cap + pre-flight token estimate |
| Knowledge base staleness | KB versioning + re-ingestion scripts with checksums |
| Schema drift across waves | `schema_changelog.md` + Pydantic strict mode |
| Single point of failure (Qdrant) | Health check on startup; fail fast with clear error message |