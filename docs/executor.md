# DYNAFIT — Executor Context
> Antigravity IDE | Project: DYNAFIT Requirement Fitment Engine
> Use this file for running the pipeline, debugging failures, tracing data flow, and operating the system.

---

## How to Run the Pipeline

### Minimal Local Run (Dev / Testing)

```python
import asyncio
from uuid import uuid4
from core.state.graph import build_graph
from core.state.requirement_state import make_initial_state
from core.config.settings import settings

async def run():
    graph = build_graph()  # Uses MemorySaver (in-memory checkpoint)
    
    state = make_initial_state(
        run_id=str(uuid4()),
        source_files=["path/to/brd.xlsx"],
        kb_version=settings.KB_VERSION,
    )
    config = {"configurable": {"thread_id": state["run_id"]}}
    
    # Run until interrupt (Phase 4 → Phase 5 boundary)
    result = await graph.ainvoke(state, config=config)
    print(f"Status: AWAITING_REVIEW")
    print(f"Items needing review: {result.get('human_review_required', [])}")
    
    # Resume after consultant review
    from core.schemas.classification_result import ConsultantDecision
    decisions = []  # Inject consultant decisions here
    
    result = await graph.ainvoke(
        {"consultant_decisions": decisions},
        config=config,
    )
    print(f"Output: {result.get('output_path')}")

asyncio.run(run())
```

### Production Run (with PostgresSaver)

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from core.config.settings import settings

async def run_production():
    async with AsyncPostgresSaver.from_conn_string(settings.POSTGRES_URL) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        state = make_initial_state(run_id=run_id, source_files=[...], kb_version=settings.KB_VERSION)
        config = {"configurable": {"thread_id": run_id}}
        result = await graph.ainvoke(state, config=config)
```

---

## Graph Execution Flow

```
graph.ainvoke(state)
  │
  ├─► ingestion node     → atoms, rejected_atoms, ingestion_errors
  ├─► retrieval node     → retrieval_contexts, retrieval_errors
  ├─► matching node      → match_results, matching_errors
  ├─► classification node → classification_results, llm_cost_usd, human_review_required
  │
  ├─► [interrupt() fires here if review_required or blocking conflicts]
  │    Graph pauses. Checkpointed to PostgreSQL.
  │    API: PATCH /runs/{id}/review injects consultant_decisions
  │    graph.ainvoke({consultant_decisions: [...]}, config) resumes
  │
  └─► validation node    → validated_batch, output_path, conflict_report
```

---

## Phase-by-Phase Debugging Guide

### Phase 1 — Ingestion Failures

**Symptom:** `atoms` list is empty or smaller than expected.

**Check:**
```python
state["rejected_atoms"]        # Hard-rejected atoms with rejection_reason
state["ingestion_errors"]      # File-level errors (parse failures)
```

**Common causes:**
- `completeness_score < 20` → atom hard-rejected. Check LLM extraction quality.
- LLM returned non-JSON → `extraction_json_parse_failed` log event. Check `ingestion_extract.j2` prompt.
- File format not supported → check `SUPPORTED_EXTENSIONS` in `doc_parser.py`.
- LLM returned empty list → triggers retry (up to `MAX_INGESTION_RETRIES=2`). If still empty, check chunk text.

**Log events to watch:**
```
ingestion.start          → file_count
ingestion.parsed         → chunks per file
ingestion.extracted      → atom_count per batch
normalization_dedup      → before/after dedup counts
validation_complete      → valid vs rejected
atom_rejected            → individual rejection with reason
```

---

### Phase 2 — Retrieval Failures

**Symptom:** `retrieval_contexts` missing atoms, or contexts have empty `top_capabilities`.

**Check:**
```python
state["retrieval_errors"]      # Per-atom errors
context.sources_available      # Which knowledge sources responded
context.cache_hit              # Whether Redis served this context
```

**Common causes:**
- Qdrant unreachable → hard-raises, atom fails entirely. Check `QDRANT_HOST`, `QDRANT_PORT`.
- D365 KB collection missing → `qdrant_collections_missing` log. Run `scripts/setup_vector_db.py`.
- Redis down → soft failure, retrieval proceeds without cache. Check `REDIS_URL`.
- pgvector down → soft failure, `historical` is empty. Check `POSTGRES_URL`.
- Module filter returning 0 results → KB may not have capabilities for that module. Check `d365_capabilities` collection for that module value.

**Log events to watch:**
```
retrieval.start              → atom_count
retrieval.cache_hit          → skipped retrieval
capabilities_retrieval_failed → hard error (raises)
ms_learn_retrieval_failed    → soft warning (continues)
historical_retrieval_failed  → soft warning (continues)
reranker_complete            → input_count, top_score, top_cap
```

---

### Phase 3 — Matching Anomalies

**Symptom:** Unexpected routing decisions (too many FAST_TRACK or SOFT_GAP).

**Check:**
```python
mr.composite_score       # Should be 0.0–1.0
mr.confidence_band       # HIGH / MED / LOW
mr.route_decision        # FAST_TRACK / LLM / SOFT_GAP
mr.has_exact_history     # True only if atom_hash matched exactly
mr.candidates            # Should be 1–5 ScoredCandidate objects
```

**Routing thresholds (from thresholds.py):**
```
composite ≥ 0.85 AND has_exact_history → FAST_TRACK
composite < 0.40 AND no history AND no candidates → SOFT_GAP
everything else → LLM
```

**If composite is always 0:** Embeddings may be null on `D365CapabilityMatch` (Qdrant not returning vectors). Check `with_payload=True` and `with_vectors=True` in qdrant_client search calls.

**Module threshold override:** AP uses `fast_track_fit: 0.82`, not 0.85. Check `ap.yaml`.

---

### Phase 4 — Classification Errors

**Symptom:** GAP verdicts with `confidence=0.0` or `needs_review=True` unexpectedly.

**Check:**
```python
result.route_taken       # FAST_TRACK / LLM / SOFT_GAP
result.sanity_flags      # List of triggered sanity rules
result.needs_review      # True if flagged
result.rationale         # LLM explanation
```

**Sanity flags explained:**
| Flag | Cause | Action |
|---|---|---|
| "High match score (X) but classified GAP" | composite ≥ 0.80 but LLM said GAP | Review LLM rationale — may be a localization gap |
| "Low match score (X) but classified FIT" | composite ≤ 0.35 but LLM said FIT | Likely hallucination — verify candidates |
| "LLM confidence diverges from match score" | \|llm_conf - composite\| > 0.40 | Investigate mismatch |
| "No D365 capability candidates but FIT" | candidates list empty but FIT | Likely hallucination — escalate |
| "Parse failure" | LLM response was not parseable XML or regex | Check model output, prompt template |
| "Soft GAP — no candidates found" | SOFT_GAP route taken | May need more KB data for this module |
| "Processing error — manual review required" | Exception during classification | Check `classification_errors` |

**LLM cost preflight rejected:**
```
LLMCostLimitError: Projected cost $X.XX exceeds limit $5.00
→ Reduce BATCH_SIZE or increase MAX_LLM_COST_USD_PER_RUN in settings
```

**Log events to watch:**
```
cost_preflight               → estimated_tokens, estimated_cost_usd
classification.start         → result_count
sanity_high_score_gap        → warning with atom_id, score
sanity_low_score_fit         → warning with atom_id, score
sanity_no_candidates_fit     → error — hallucination risk
response_parser_total_failure → error — all parse strategies failed
classification.complete      → fit/partial/gap counts, llm_cost_usd
```

---

### Phase 5 — Validation / Output Issues

**Symptom:** Pipeline hangs at Phase 5 or output file not generated.

**Check:**
- Is `interrupt()` firing? → Expected behaviour if `human_review_required` is non-empty.
- Graph state is: `AWAITING_REVIEW`. Resume via API or direct `ainvoke` with decisions.
- `conflict_report.error_count > 0` → blocking conflicts trigger interrupt even with 0 review items.
- `output_path` is None → `ReportGenerator.generate()` failed. Check openpyxl, disk permissions.

```python
state["conflict_report"].conflicts     # List of ConflictEntry objects
state["consultant_decisions"]          # Should be non-empty after resume
state["validated_batch"].override_count
state["validated_batch"].total_llm_cost_usd
```

---

## Key State Fields at Each Phase Boundary

### After Phase 1
```python
state["atoms"]                  # list[RequirementAtom]
state["rejected_atoms"]         # list[RejectedAtom]
len(state["atoms"])             # Expected: 80-90% of raw requirements
```

### After Phase 2
```python
state["retrieval_contexts"]     # list[RetrievalContext] — one per atom
ctx.top_capabilities            # Should have 1-5 D365CapabilityMatch
ctx.cache_hit                   # True = Redis served this
ctx.has_historical_precedent    # True = prior wave data found
```

### After Phase 3
```python
state["match_results"]          # list[MatchResult] — one per atom
mr.route_decision               # Distribution: mostly LLM, some FAST_TRACK/SOFT_GAP
mr.composite_score              # Range: 0.0-1.0
mr.candidates                   # 0-5 ScoredCandidate
```

### After Phase 4
```python
state["classification_results"]         # list[ClassificationResult]
state["llm_cost_usd"]                   # Should be < MAX_LLM_COST_USD_PER_RUN (default $5)
state["human_review_required"]          # atom_ids needing consultant review
# Typical distribution:
# FIT: 40-60%, PARTIAL_FIT: 20-30%, GAP: 15-25%
```

### After Phase 5
```python
state["validated_batch"].fit_rate       # float
state["validated_batch"].gap_rate       # float
state["output_path"]                    # /tmp/.../fitment_matrix.xlsx
```

---

## LLM Cost Monitoring

Costs are tracked per-run and per-call. All tracking is in `infrastructure/llm/client.py`.

```python
# Pricing table (update when Anthropic changes pricing)
"claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00}  # per 1M tokens
"claude-3-haiku-20240307":    {"input": 0.25, "output": 1.25}
"claude-sonnet-4-20250514":   {"input": 3.00, "output": 15.00}

# Per-run limit
MAX_LLM_COST_USD_PER_RUN = 5.00   # Override in .env to change

# Track actual cost
state["llm_cost_usd"]              # Accumulated after Phase 4
```

**Cost estimation formula:**
```
Phase 4 preflight: samples 20 atoms → estimates avg_tokens × total_LLM_atoms × (cost_per_1k / 1000)
Actual cost: Σ (prompt_tokens/1M × input_rate) + (completion_tokens/1M × output_rate) per call
```

---

## Redis Cache Behaviour

- **Cache key:** `retrieval:{atom_hash}:{kb_version}` — changes with KB updates (intentional)
- **TTL:** 24 hours (`RETRIEVAL_CACHE_TTL_SEC=86400`)
- **Cache miss causes:** first run for an atom, KB version bumped, TTL expired, Redis down
- **Cache hit:** `context.cache_hit = True`, skips all retrieval, proceeds directly to Phase 3
- Redis failures are **soft** — logged as warning, pipeline continues without cache

---

## LangGraph Checkpointing

The pipeline is fully checkpointable. After any node completes, state is saved.

```python
# Check current graph state (useful for debugging mid-run)
config = {"configurable": {"thread_id": run_id}}
snapshot = graph.get_state(config)
snapshot.values          # Current state dict
snapshot.next            # Next node to execute
snapshot.metadata        # Step count, source node

# Resume after interrupt
graph.ainvoke(
    {"consultant_decisions": [...]},
    config=config,
)

# Get full history
for state in graph.get_state_history(config):
    print(state.metadata["step"], state.next)
```

---

## Qdrant Collection Schema

### `d365_capabilities` collection
```
Required payload fields:
  capability_id: str    # e.g. "AP-001"
  name: str
  description: str
  module: str           # D365Module value
  sub_module: str | null
  license_requirement: str | null
  configuration_notes: str | null
  localization_gaps: dict

Required vectors:
  "" (default dense): 1024-dim float (bge-large-en-v1.5, no prefix)
  "text_sparse": sparse (BM25 tokens as index:weight)

Required filter index:
  module (keyword)
```

### `ms_learn_docs` collection
```
Required payload fields:
  chunk_id: str
  source_url: str
  page_title: str
  section_heading: str | null
  text: str

Required vectors:
  "" (default dense): 1024-dim float
```

---

## PostgreSQL Schema (historical_fitments table)

```sql
CREATE TABLE historical_fitments (
    fitment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    atom_hash VARCHAR(64) NOT NULL,
    original_text TEXT NOT NULL,
    module VARCHAR(20) NOT NULL,
    verdict VARCHAR(20) NOT NULL,
    confidence FLOAT NOT NULL,
    rationale TEXT NOT NULL,
    matched_capability TEXT,
    wave_id VARCHAR(50) NOT NULL,
    overridden_by_consultant BOOLEAN DEFAULT FALSE,
    embedding VECTOR(1024),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX ON historical_fitments (atom_hash, module);
CREATE INDEX ON historical_fitments USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

---

## Health Checks

```python
# Run before pipeline to validate infrastructure
from infrastructure.vector_db.qdrant_client import qdrant_client
from infrastructure.vector_db.embedder import embedder
from infrastructure.storage.redis_client import redis_client

async def health_check_all():
    results = {
        "qdrant": await qdrant_client.health_check(),
        "embedder": await embedder.health_check(),
        "redis": await redis_client.health_check(),
    }
    print(results)
    assert all(results.values()), f"Infrastructure health check failed: {results}"
```

---

## Common Error Reference

| Error | Location | Meaning | Fix |
|---|---|---|---|
| `LLMCostLimitError` | Phase 4 preflight | Projected cost > MAX_LLM_COST_USD_PER_RUN | Increase limit or reduce BATCH_SIZE |
| `LLMAuthError` | llm/client.py | Invalid ANTHROPIC_API_KEY | Check .env |
| `LLMRateLimitError` | llm/client.py | Rate limited (auto-retried 3x) | Reduce concurrency or wait |
| `LLMBadRequestError` | llm/client.py | Prompt too long or bad params | Check CLASSIFICATION_MAX_TOKENS |
| `qdrant_collections_missing` | qdrant_client | Collections not created | Run scripts/setup_vector_db.py |
| `extraction_json_parse_failed` | req_extractor | LLM returned non-JSON | Check ingestion_extract.j2 template |
| `sanity_no_candidates_fit` | sanity_checker | No candidates but LLM said FIT | Likely hallucination, always review |
| `response_parser_total_failure` | response_parser | All parse strategies failed | Check classification prompt templates |
| `docling_failed_falling_back` | doc_parser | Docling parse failed, using Unstructured | Normal fallback, warn if frequent |

---

## Performance Benchmarks (Expected)

| Phase | Time (265 atoms) | Notes |
|---|---|---|
| Phase 1 — Ingestion | 30–60s | Dominated by LLM batch calls |
| Phase 2 — Retrieval | 15–30s | Parallel fan-out; cache hits ~50% on repeat runs |
| Phase 3 — Matching | 5–10s | CPU-bound CrossEncoder in thread pool |
| Phase 4 — Classification | 60–120s | ~200 LLM calls at 50 batch size |
| Phase 5 — Validation | 5–15s | After human review resumed |
| **Total (no cache)** | **~3–4 min** | |
| **Total (warm cache)** | **~2 min** | 50% retrieval cache hit |

---

## Observability Stack

- **Structured logging:** structlog → JSON to stdout → aggregate in Grafana Loki
- **Metrics:** Prometheus on port 9090 (configured in settings.METRICS_PORT)
- **Tracing:** LangSmith (optional) — set `LANGCHAIN_API_KEY` to enable
- **LLM cost per run:** `state["llm_cost_usd"]` and `validated_batch.total_llm_cost_usd`
- **Dashboard:** Grafana (connected to Prometheus)

Key metrics to instrument:
```
dynafit_run_total{status}              # Total pipeline runs by status
dynafit_verdict_total{module,verdict}  # FIT/PARTIAL_FIT/GAP distribution
dynafit_llm_cost_usd                   # Cost per run
dynafit_phase_duration_seconds{phase}  # Latency per phase
dynafit_cache_hits_total               # Redis cache effectiveness
```