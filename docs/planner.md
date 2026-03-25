# DYNAFIT — Planner Context
> Antigravity IDE | Project: DYNAFIT Requirement Fitment Engine
> Use this file for sprint planning, task decomposition, and architectural decisions.

---

## Project Identity

**Name:** DYNAFIT — Requirement Fitment Engine
**Domain:** Microsoft Dynamics 365 F&O ERP Implementation
**Core Problem:** Automates the manual, error-prone process of assessing whether client business requirements are covered by standard D365 F&O capabilities (FIT), need configuration (PARTIAL_FIT), or require custom development (GAP).
**Output:** `fitment_matrix.xlsx` — feeds directly into FDD FOR FITS and FDD FOR GAPS downstream modules.
**LLM Backbone:** Anthropic Claude (haiku for ingestion, sonnet for classification)
**Orchestration:** LangGraph StateGraph (5 nodes, checkpointed, interrupt-capable)

---

## Repository Structure

```
dynafit/
├── agents/
│   ├── ingestion/
│   │   ├── agent.py               # Phase 1 LangGraph node
│   │   ├── doc_parser.py          # Format detection + raw chunk extraction
│   │   ├── req_extractor.py       # LLM-based atomization (haiku)
│   │   ├── normalizer.py          # Dedup + term alignment + MoSCoW
│   │   └── validator.py           # Schema + completeness QA gate
│   ├── retrieval/
│   │   ├── agent.py               # Phase 2 LangGraph node [MISSING - needs build]
│   │   ├── query_builder.py       # Atom → dense + sparse query
│   │   ├── parallel_retriever.py  # Fan-out to 3 knowledge sources
│   │   ├── rrf_fusion.py          # Reciprocal Rank Fusion (k=60, ADR-locked)
│   │   ├── reranker.py            # CrossEncoder top-20 → top-5
│   │   └── context_assembler.py   # Assembles RetrievalContext + Redis cache
│   ├── matching/
│   │   ├── agent.py               # Phase 3 LangGraph node
│   │   ├── embedding_match.py     # Cosine + entity overlap per candidate
│   │   ├── confidence_scorer.py   # Composite score + routing decision
│   │   └── candidate_ranker.py    # Multi-factor rank + dedup → top-5
│   ├── classification/
│   │   ├── agent.py               # Phase 4 LangGraph node
│   │   ├── prompt_builder.py      # Jinja2 system+user prompt with module notes
│   │   ├── llm_classifier.py      # LLM call wrapper
│   │   ├── response_parser.py     # XML → regex → fallback parse strategy
│   │   └── sanity_checker.py      # Post-classification consistency rules
│   └── validation/
│       ├── agent.py               # Phase 5 LangGraph node (interrupt-capable)
│       ├── consistency_checker.py # Cross-req conflict detection [STUB - needs build]
│       ├── override_handler.py    # Consultant decision application [STUB - needs build]
│       └── report_generator.py    # fitment_matrix.xlsx via openpyxl [STUB - needs build]
├── core/
│   ├── config/
│   │   ├── settings.py            # pydantic-settings, all env-driven
│   │   ├── thresholds.py          # Single source of truth for all thresholds
│   │   └── module_config/
│   │       └── ap.yaml            # AP module: weights, gaps, term maps
│   ├── prompts/
│   │   ├── classification_system.j2   [MISSING - needs build]
│   │   ├── classification_user.j2     [MISSING - needs build]
│   │   └── ingestion_extract.j2       [MISSING - needs build]
│   ├── schemas/
│   │   ├── enums.py               # All categorical enums (D365Module, Verdict, etc.)
│   │   ├── requirement_atom.py    # Primary unit of work (frozen Pydantic v2)
│   │   ├── retrieval_context.py   # Phase 2 output schema
│   │   ├── match_result.py        # Phase 3 output schema
│   │   └── classification_result.py # Phase 4+5 output schemas
│   └── state/
│       ├── graph.py               # LangGraph StateGraph compilation
│       └── requirement_state.py   # RequirementState TypedDict (pipeline contract)
└── infrastructure/
    ├── llm/
    │   └── client.py              # ONLY LLM entry point (tenacity + cost tracking)
    ├── vector_db/
    │   ├── embedder.py            # BgeEmbedder singleton (bge-large-en-v1.5)
    │   └── qdrant_client.py       # AsyncQdrantClient (vector + keyword search)
    └── storage/
        └── redis_client.py        # RetrievalContext cache [MISSING - needs build]
```

---

## What's Built vs What's Missing

### ✅ Fully Implemented
- All 5 Phase agent orchestration nodes
- Phase 1: doc_parser, req_extractor, normalizer, validator
- Phase 2: query_builder, parallel_retriever, rrf_fusion, reranker, context_assembler
- Phase 3: embedding_match, confidence_scorer, candidate_ranker
- Phase 4: prompt_builder, llm_classifier, response_parser, sanity_checker
- Phase 5: agent (interrupt + override + report generation calls)
- All core schemas (frozen Pydantic v2)
- LLM client with retry + cost tracking
- Qdrant client (vector + keyword + MS Learn)
- BgeEmbedder with instruction prefix handling
- LangGraph graph with checkpointing + interrupt_before
- Settings + thresholds configuration layer
- AP module YAML config

### ❌ Missing / Stubs (Needs Build)
- `agents/retrieval/agent.py` — Phase 2 LangGraph node orchestrator
- `agents/validation/consistency_checker.py` — NetworkX conflict detection
- `agents/validation/override_handler.py` — Consultant decision application
- `agents/validation/report_generator.py` — openpyxl Excel output
- `infrastructure/storage/redis_client.py` — RetrievalContext cache
- `infrastructure/vector_db/pgvector_client.py` — Historical fitments lookup
- `core/prompts/*.j2` — All Jinja2 prompt templates (3 files)
- `core/config/module_config/*.yaml` — All module configs except AP (GL, AR, SCM, WMS, etc.)
- FastAPI application layer (`api/`)
- Database migrations (Alembic)
- KB ingestion scripts (`scripts/setup_vector_db.py`)
- Test suite

---

## Pipeline Data Flow

```
source_files (list[str])
    ↓ Phase 1 — Ingestion
atoms: list[RequirementAtom]           ← frozen Pydantic, SHA256 hash, MoSCoW/module/country
    ↓ Phase 2 — RAG Retrieval
retrieval_contexts: list[RetrievalContext]  ← top-5 caps + MS Learn refs + prior fitments
    ↓ Phase 3 — Semantic Matching
match_results: list[MatchResult]       ← composite score + band + route: FAST_TRACK/LLM/SOFT_GAP
    ↓ Phase 4 — Classification (LLM)
classification_results: list[ClassificationResult]  ← FIT/PARTIAL_FIT/GAP + confidence + rationale
    ↓ [interrupt() — human review via PATCH /runs/{id}/review]
    ↓ Phase 5 — Validation & Output
validated_batch: ValidatedFitmentBatch  ← final verdicts + overrides + audit trail
output_path: str                        → fitment_matrix.xlsx
```

---

## Routing Logic (Phase 3 → Phase 4)

| Condition | Route | Phase 4 Behavior |
|---|---|---|
| composite ≥ 0.85 AND exact history match | FAST_TRACK | Skip LLM, emit FIT immediately |
| composite < 0.40 AND no history AND no candidates | SOFT_GAP | Skip LLM, emit GAP + needs_review |
| Everything else | LLM | Full claude-3-5-sonnet chain-of-thought |

Module override: AP uses `fast_track_fit: 0.82` (lower threshold — AP is well-documented)

---

## Confidence Composite Formula

```
composite = 0.50 × max_cosine
          + 0.30 × max_overlap
          + 0.20 × historical_weight
```

Where `historical_weight`:
- `1.0` if exact atom_hash match in history
- `best_similarity × 0.8` if similar history found
- `0.0` if no history

Module YAML can override weights (must sum to 1.0).

---

## Threshold Reference (core/config/thresholds.py)

| Threshold | Value | Effect |
|---|---|---|
| fast_track_fit | 0.85 | FAST_TRACK routing |
| soft_gap | 0.40 | SOFT_GAP routing |
| sanity_high_score_gap | 0.80 | Flag high-score GAPs |
| sanity_low_score_fit | 0.35 | Flag low-score FITs |
| sanity_confidence_divergence | 0.40 | Flag LLM vs composite divergence |
| completeness_reject | 20.0 | Hard reject atom |
| completeness_flag | 40.0 | Soft flag atom for review |

---

## D365 Modules Supported

`AP, AR, GL, FA, SCM, WMS, MFG, PM, HR, PAYROLL, BUDGET, CASH, TAX, CONSOLIDATION, UNKNOWN`

Only AP has a module config YAML. All others fall back to global thresholds and default weights.

---

## Key Architectural Decisions (ADRs)

| Decision | Value | Rationale |
|---|---|---|
| RRF k=60 | Locked, do not change | Per ADR-001; change requires docs/architecture/adr update |
| Module filter on Qdrant | Always mandatory | Cross-module capability retrieval architecturally prevented |
| Single LLM entry point | `llm_call()` in client.py | Centralized retry, cost tracking, tracing |
| No re-embedding in Phase 3 | Reuse Phase 2 embeddings | Performance; vectors stored on D365CapabilityMatch |
| Frozen schemas | Pydantic frozen=True | Immutability guarantees across async pipeline |
| Soft vs hard failures | D365 KB = hard, others = soft | KB failure means useless output; MS Learn/history optional |
| Haiku for ingestion, Sonnet for classification | Cost optimization | Ingestion is high-volume, low-precision; classification is low-volume, high-precision |

---

## Sprint Planning: Recommended Build Order

### Sprint 1 — Close the Gaps (Infrastructure)
1. `infrastructure/storage/redis_client.py` — RetrievalContext cache (needed by context_assembler)
2. `infrastructure/vector_db/pgvector_client.py` — Historical fitments (needed by parallel_retriever)
3. `agents/retrieval/agent.py` — Phase 2 orchestrator (pipeline won't run without it)

### Sprint 2 — Prompts + Validation
4. `core/prompts/ingestion_extract.j2` — Ingestion LLM prompt
5. `core/prompts/classification_system.j2` + `classification_user.j2` — Classification prompts
6. `agents/validation/consistency_checker.py` — NetworkX conflict graph
7. `agents/validation/override_handler.py` — Consultant override logic
8. `agents/validation/report_generator.py` — Excel output via openpyxl

### Sprint 3 — Module Configs + API
9. Module YAML configs: `gl.yaml`, `ar.yaml`, `scm.yaml`, `wms.yaml`, `mfg.yaml`
10. FastAPI application (`api/main.py`, `api/routes/runs.py`, `api/routes/review.py`)
11. `PATCH /runs/{id}/review` endpoint (resume LangGraph after interrupt)

### Sprint 4 — Hardening
12. Alembic migrations for historical fitments table
13. `scripts/setup_vector_db.py` — Qdrant collection setup
14. Full test suite (pytest + async fixtures)
15. Prometheus metrics integration

---

## Environment Variables Required

```env
ANTHROPIC_API_KEY=           # Required
QDRANT_HOST=localhost
QDRANT_PORT=6333
POSTGRES_URL=postgresql+asyncpg://dynafit:password@localhost:5432/dynafit
REDIS_URL=redis://localhost:6379/0
CLASSIFICATION_MODEL=claude-3-5-sonnet-20241022
INGESTION_MODEL=claude-3-haiku-20240307
MAX_LLM_COST_USD_PER_RUN=5.00
KB_VERSION=v1.0.0
LANGCHAIN_API_KEY=           # Optional, enables LangSmith tracing
```