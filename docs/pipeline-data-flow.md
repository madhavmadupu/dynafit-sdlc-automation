# DYNAFIT Pipeline — Complete Data Flow Reference

> End-to-end trace of how data moves through the 5-phase multi-agent pipeline,
> from BRD file upload to final FDD document download.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Upload & Run Creation](#2-upload--run-creation)
3. [Pipeline Orchestration (LangGraph)](#3-pipeline-orchestration-langgraph)
4. [Pipeline State Shape](#4-pipeline-state-shape)
5. [Phase 1 — Ingestion Agent](#5-phase-1--ingestion-agent)
6. [Phase 2 — Retrieval Agent (RAG)](#6-phase-2--retrieval-agent-rag)
7. [Phase 3 — Matching Agent](#7-phase-3--matching-agent)
8. [Phase 4 — Classification Agent](#8-phase-4--classification-agent)
9. [Human-in-the-Loop Interrupt](#9-human-in-the-loop-interrupt)
10. [Phase 5 — Validation & Output Agent](#10-phase-5--validation--output-agent)
11. [SSE Streaming & Frontend State](#11-sse-streaming--frontend-state)
12. [Final Outputs](#12-final-outputs)
13. [External Services](#13-external-services)
14. [Data Shape Summary Table](#14-data-shape-summary-table)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  FRONTEND  (Next.js 16 / React 19 / Zustand / Tailwind)           │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐ │
│  │ Phase 1  │→ │ Phase 2  │→ │ Phase 3  │→ │ Phase 4  │→ │ Ph.5 │ │
│  │Ingestion │  │Retrieval │  │Matching  │  │Classify  │  │Valid.│ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────┘ │
│       ↕ SSE          ↕ SSE        ↕ SSE         ↕ SSE       ↕ SSE │
└───────┬──────────────┬────────────┬─────────────┬────────────┬─────┘
        │              │            │             │            │
┌───────▼──────────────▼────────────▼─────────────▼────────────▼─────┐
│  BACKEND  (FastAPI / LangGraph / Python 3.11+)                     │
│                                                                     │
│  POST /runs → asyncio background task                               │
│       ↓                                                             │
│  LangGraph StateGraph (sequential nodes, interrupt_before=validation)│
│       ↓                                                             │
│  ┌──────────┐→┌──────────┐→┌──────────┐→┌──────────┐→┌──────────┐ │
│  │Ingestion │ │Retrieval │ │Matching  │ │Classify  │ │Validation│ │
│  │  Agent   │ │  Agent   │ │  Agent   │ │  Agent   │ │  Agent   │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│       │            │            │             │            │        │
│       ▼            ▼            ▼             ▼            ▼        │
│  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Docling  │ │ Qdrant   │ │Embedder │ │ Claude   │ │ openpyxl │  │
│  │ Unstruct.│ │ pgvector │ │CrossEnc.│ │   API    │ │python-docx│ │
│  └─────────┘ │ Redis    │ └─────────┘ └──────────┘ └──────────┘  │
│              └──────────┘                                          │
└────────────────────────────────────────────────────────────────────┘
```

**Tech Stack:**

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16, React 19, Zustand, Tailwind CSS 4, shadcn/ui |
| Backend API | FastAPI, Uvicorn |
| Orchestration | LangGraph (StateGraph with checkpointing) |
| LLM | Anthropic Claude (ingestion + classification) |
| Vector DB | Qdrant (D365 KB, MS Learn corpus) |
| Relational DB | PostgreSQL + pgvector (run tracking, audit, historical fitments) |
| Cache | Redis (retrieval context cache, 24h TTL) |
| Embeddings | BAAI/bge-large-en-v1.5 |
| Reranking | ms-marco-MiniLM-L-6-v2 (CrossEncoder) |
| Document Gen | openpyxl (Excel), python-docx (Word FDD) |

---

## 2. Upload & Run Creation

### Frontend Flow

```
User drags/clicks files (.xlsx, .xls, .docx, .doc, .pdf, .txt, .csv)
       ↓
Phase1Ingestion component
  → Files stored in realFilesRef (React ref with native File objects)
  → Files added to Zustand store as UploadedFile[] (name, size, type, id)
  → UI shows file list with progress bars
       ↓
User clicks "Run Ingestion"
  → runIngestion(realFilesRef.current)
       ↓
DynafitAPI.createRun(files)
  → FormData with all files
  → POST /api/v1/runs (multipart/form-data, x-api-key header)
       ↓
Returns: { run_id: UUID, status: "RUNNING", message: "..." }
```

### Backend Flow (`api/routes.py` → `POST /runs`)

```python
# 1. Generate run ID
run_id = str(uuid4())

# 2. Save files to disk
for file in files:
    safe_name = f"{run_id}_{file.filename}"
    path = settings.UPLOAD_DIR / safe_name
    # Write binary content
    saved_paths.append(str(path))

# 3. Create run record in Postgres
await postgres_client.create_run(run_id=run_id, source_files=saved_paths)
await postgres_client.update_run_status(run_id, RunStatus.RUNNING)

# 4. Build initial state and start pipeline in background
state = make_initial_state(run_id=run_id, source_files=saved_paths)
config = {"configurable": {"thread_id": run_id}}
asyncio.create_task(_run_pipeline_background(run_id, state, config))

# 5. Return immediately (non-blocking)
return RunResponse(run_id=run_id, status="RUNNING", message="...")
```

**Key point:** The API returns the `run_id` immediately. The pipeline runs asynchronously in the background. The frontend connects to SSE for real-time progress updates.

### Files on Disk

```
uploads/
  636968f4_requirements.xlsx
  636968f4_design_spec.docx
```

---

## 3. Pipeline Orchestration (LangGraph)

### Graph Definition (`core/state/graph.py`)

```python
graph = StateGraph(RequirementState)

# Register nodes (each is an async function)
graph.add_node("ingestion",      ingestion_agent.run)
graph.add_node("retrieval",      retrieval_agent.run)
graph.add_node("matching",       matching_agent.run)
graph.add_node("classification", classification_agent.run)
graph.add_node("validation",     validation_agent.run)

# Linear pipeline edges
graph.set_entry_point("ingestion")
graph.add_edge("ingestion",      "retrieval")
graph.add_edge("retrieval",      "matching")
graph.add_edge("matching",       "classification")
graph.add_edge("classification", "validation")
graph.add_edge("validation",     END)

# Compile with checkpointing and human interrupt
compiled = graph.compile(
    checkpointer=MemorySaver(),           # In-memory for prototype
    interrupt_before=["validation"]        # Pause BEFORE Phase 5
)
```

### Execution Model

- Each node is an `async def run(state: dict) -> dict` function
- Nodes read from the shared `RequirementState` dict
- Each node returns a **partial dict** — LangGraph merges it back into state
- The graph streams events via `graph.astream(state, stream_mode="updates")`
- The graph **pauses before validation** for human review (consultant override)
- After human decisions are submitted, the graph resumes from the interrupt point

### Background Pipeline Execution

```python
async def _run_pipeline_background(run_id, state, config):
    # Stream mode="updates" yields {node_name: state_update} per node
    async for event in graph.astream(state, config=config, stream_mode="updates"):
        for node_name, node_output in event.items():
            # Build frontend-friendly stats
            stats = _build_phase_stats(node_name, node_output)
            # Emit SSE events to connected frontend
            await _emit_event(run_id, {
                "type": "phase_complete",
                "phase": node_name,
                "stats": stats,
            })

    # After stream ends: either COMPLETED or AWAITING_REVIEW (interrupted)
```

---

## 4. Pipeline State Shape

### `RequirementState` TypedDict (`core/state/requirement_state.py`)

This is the **single source of truth** that flows through all 5 phases:

```python
class RequirementState(TypedDict, total=False):
    # ── Run Metadata ──────────────────────────────────────────
    run_id: str                          # UUID string
    created_at: str                      # ISO datetime
    source_files: list[str]              # Absolute paths to uploaded files
    kb_version: str                      # Knowledge base version (cache key)

    # ── Phase 1: Ingestion Output ─────────────────────────────
    atoms: list[RequirementAtom]         # Validated requirement atoms
    rejected_atoms: list[RejectedAtom]   # Hard rejections (for audit)
    ingestion_errors: list[dict]         # File-level parse failures

    # ── Phase 2: Retrieval Output ─────────────────────────────
    retrieval_contexts: list[RetrievalContext]  # One per atom
    retrieval_errors: list[dict]

    # ── Phase 3: Matching Output ──────────────────────────────
    match_results: list[MatchResult]     # Scoring + route decisions
    matching_errors: list[dict]

    # ── Phase 4: Classification Output ────────────────────────
    classification_results: list[ClassificationResult]  # FIT/PARTIAL/GAP
    classification_errors: list[dict]
    llm_cost_usd: float                  # Running total of LLM spend

    # ── Phase 5: Validation Output ────────────────────────────
    validated_batch: ValidatedFitmentBatch | None
    output_path: str | None              # Path to fitment_matrix.xlsx

    # ── Human-in-the-Loop ─────────────────────────────────────
    human_review_required: list[str]     # Atom IDs flagged for review
    consultant_decisions: list[ConsultantDecision]  # From PATCH /review

    # ── Cross-phase ───────────────────────────────────────────
    pipeline_errors: list[dict]          # Append-only across all phases
```

### How State Flows Between Phases

```
Initial State (run_id, source_files)
    │
    ├─ Phase 1 adds: atoms, rejected_atoms
    │
    ├─ Phase 2 adds: retrieval_contexts
    │
    ├─ Phase 3 adds: match_results
    │
    ├─ Phase 4 adds: classification_results, llm_cost_usd, human_review_required
    │
    │── [INTERRUPT — human adds consultant_decisions via PATCH]
    │
    └─ Phase 5 adds: validated_batch, output_path
```

---

## 5. Phase 1 — Ingestion Agent

> **Purpose:** Parse uploaded BRD documents and extract individual, normalized requirement atoms.

### Input

```python
{
    "run_id": "636968f4-...",
    "source_files": ["/uploads/636968f4_requirements.xlsx"]
}
```

### Processing Steps

#### Step 1: Document Parsing (`doc_parser.py`)

| File Type | Parser | Method |
|-----------|--------|--------|
| `.xlsx` / `.xls` | openpyxl | Auto-detect header row, merge cells into pipe-separated text |
| `.docx` / `.doc` | Docling (primary) + Unstructured (fallback) | Extract paragraphs + tables |
| `.pdf` | Docling with OCR + Unstructured fallback | OCR for scanned docs |
| `.txt` / `.md` | Built-in | Split on double newlines |
| `.csv` | Built-in | Row-by-row text extraction |

**Output:** `list[RawChunk]` — each with `text`, `source_ref` (e.g., `"file.xlsx:row_42"`), `chunk_index`

#### Step 2: LLM Atom Extraction (`req_extractor.py`)

- Chunks batched into groups of **20** (configurable `BATCH_SIZE`)
- Each batch rendered with Jinja2 template `ingestion_extract.j2`
- **LLM call to Claude** extracts structured atoms from raw text

```
Prompt: "Here are 20 chunks from a BRD document. Extract each distinct
         business requirement as a structured atom with module, priority,
         intent, country, completeness_score..."

Response: JSON array of extracted atoms
```

**Per atom extracted:**
- `text` — normalized requirement text
- `raw_text` — original text from LLM
- `module` — D365 module (AP, AR, GL, FA, SCM, WMS, etc.)
- `sub_module` — optional sub-module
- `priority` — MUST / SHOULD / COULD / WONT
- `intent` — FUNCTIONAL / NFR / INTEGRATION / REPORTING / DATA_MIGRATION
- `country` — 2-letter ISO code (if applicable)
- `completeness_score` — 0-100

#### Step 3: Normalization (`normalizer.py`)

Three sub-steps:

1. **MoSCoW Priority Enrichment**
   - Scan raw text for priority signal words
   - `"must"`, `"mandatory"`, `"required"`, `"critical"` → MUST
   - `"should"`, `"recommended"` → SHOULD
   - `"could"`, `"nice to have"` → COULD
   - `"won't"`, `"out of scope"` → WONT
   - Only overrides default SHOULD assignments

2. **D365 Term Alignment**
   - Loads `core/config/module_config/{module}.yaml`
   - Maps business jargon → canonical D365 terminology
   - Example: `"three-way match"` → `"Three-Way Matching (AP)`

3. **Deduplication**
   - Group atoms by module
   - Pairwise comparison with `RapidFuzz.token_sort_ratio()`
   - Similarity > **90%** → keep atom with higher completeness_score
   - Lower-scoring duplicate is removed

#### Step 4: Validation (`validator.py`)

| Check | Threshold | Action |
|-------|-----------|--------|
| text length < 10 chars | — | **Hard reject** |
| completeness_score < 20 | `THRESHOLDS["completeness_reject"]` | **Hard reject** |
| Invalid module enum | — | **Hard reject** |
| completeness_score < 40 | `THRESHOLDS["completeness_flag"]` | Soft flag (`needs_review = true`) |
| module == UNKNOWN | — | Soft flag (`needs_review = true`) |

**Retry loop:** If atoms are rejected, re-extract with rejection reason in prompt (up to 3 retries).

**On success, create:**
```python
RequirementAtom(
    id=UUID(...),
    atom_hash=SHA256(normalized_text),   # For dedup + history matching
    text="Support three-way matching for vendor invoices",
    raw_text="System must support 3-way matching...",
    module=D365Module.AP,
    sub_module="Vendor Invoicing",
    priority=MoSCoW.MUST,
    intent=IntentType.FUNCTIONAL,
    country=None,
    completeness_score=85.0,
    source_ref="requirements.xlsx:row_42",
    source_file="requirements.xlsx",
    needs_review=False,
    status=AtomStatus.ACTIVE,
)
```

### Output

```python
{
    "atoms": list[RequirementAtom],           # Validated, normalized
    "rejected_atoms": list[RejectedAtom],     # Hard rejections (audit)
    "ingestion_errors": [...],                # File-level failures
}
```

---

## 6. Phase 2 — Retrieval Agent (RAG)

> **Purpose:** For each atom, retrieve the most relevant D365 capabilities, MS Learn documentation, and historical fitment decisions using hybrid RAG.

### Input

```python
{
    "atoms": list[RequirementAtom],   # 18-500 atoms typically
    "kb_version": "v1.0.0"
}
```

### Processing Steps (all atoms in parallel via `asyncio.gather`)

#### Step 1: Query Building (`query_builder.py`)

For each atom:
```python
RetrievalQuery(
    atom_id=str(atom.id),
    atom_hash=atom.atom_hash,
    dense_vector=await embedder.embed_requirement(atom.text),  # bge-large-en-v1.5
    sparse_tokens=tokenize(atom.text),   # BM25 tokens (lowercase, >2 chars, no stopwords)
    module_filter=atom.module.value,     # For Qdrant collection filtering
    country_filter=atom.country,
)
```

#### Step 2: Cache Check (Redis)

```python
cache_key = f"retrieval:{atom.atom_hash}:{kb_version}"
cached = await redis_client.get_retrieval_context(cache_key)
if cached:
    return cached   # Skip all retrieval, serve from Redis (24h TTL)
```

#### Step 3: Parallel Retrieval (3 sources simultaneously)

```
┌──────────────────────────────┐
│     asyncio.gather()         │
├──────────┬──────────┬────────┤
│ Source 1 │ Source 2 │Source 3│
│ D365 KB  │ MS Learn │History │
│ (Qdrant) │ (Qdrant) │(pgvec) │
└──────────┴──────────┴────────┘
```

**Source 1: D365 Capability KB** (Qdrant vector DB)
- Dense vector search (top-20 by cosine similarity)
- BM25 keyword search (top-20 by term frequency)
- Filtered by D365 module
- Returns: `list[D365CapabilityMatch]` with scores

**Source 2: MS Learn Corpus** (Qdrant vector DB)
- Dense vector search only (top-3)
- Returns: `list[DocChunkMatch]` with title, URL, snippet, score
- **Failure mode:** Soft — empty list, pipeline continues

**Source 3: Historical Fitments** (pgvector in PostgreSQL)
- Exact match by `atom_hash` first (prior identical requirement)
- Fuzzy match by embedding similarity (top-5)
- Returns: `list[HistoricalFitmentMatch]` with verdict, confidence, similarity
- **Failure mode:** Soft — empty list, pipeline continues

#### Step 4: Fusion & Reranking

```
Dense results (20)  ─┐
                     ├─→ RRF Fusion (k=60) ─→ Fused (20)
BM25 results (20)   ─┘                            │
                                                   ↓
                                        CrossEncoder Reranking
                                     (ms-marco-MiniLM-L-6-v2)
                                                   │
                                                   ↓
                                           Top-5 capabilities
```

**Reciprocal Rank Fusion formula:**
```
score(doc) = Σ  1 / (k + rank_i)     where k = 60
```

**CrossEncoder reranking:**
- Takes `(requirement_text, capability_description)` pairs
- Produces relevance score
- Returns top-5 most relevant capabilities

#### Step 5: Context Assembly

```python
RetrievalContext(
    atom_id=atom.id,
    atom_hash=atom.atom_hash,
    top_capabilities=[...],        # Top-5 after reranking
    ms_learn_refs=[...],           # Top-3 MS Learn chunks
    prior_fitments=[...],          # Historical matches
    confidence_signals={
        "max_rerank_score": 0.95,
        "max_vector_score": 0.92,
        "has_history": True,
        "has_exact_history": True,
        "n_capabilities": 5,
        "n_sources": 3,
    },
    cache_hit=False,
    kb_version="v1.0.0",
    sources_available=["d365_kb", "ms_learn", "history"],
)
```

#### Step 6: Cache Write (Redis)

```python
await redis_client.set_retrieval_context(context, kb_version, ttl=86400)  # 24h
```

### Output

```python
{
    "retrieval_contexts": list[RetrievalContext],  # One per atom
    "retrieval_errors": [...],
}
```

---

## 7. Phase 3 — Matching Agent

> **Purpose:** Score each atom's candidates, compute composite scores, and decide the routing strategy (FAST_TRACK / LLM / SOFT_GAP) for Phase 4.

### Input

```python
{
    "atoms": list[RequirementAtom],
    "retrieval_contexts": list[RetrievalContext],
}
```

### Processing Steps (all atoms in parallel)

#### Step 1: Capability Scoring

For each of the top-5 capabilities per atom:

```python
ScoredCandidate(
    capability_id="AP-001",
    name="Three-Way Matching",
    cosine_score=0.92,           # Dense embedding similarity
    overlap_score=0.78,          # Jaccard entity overlap
    rerank_score=0.95,           # CrossEncoder from Phase 2
    historical_boost=0.80,       # Match with prior fitment (0.0 if none)
    final_score = (
        0.50 * rerank_score +    # Reranker weight
        0.25 * cosine_score +    # Embedding weight
        0.15 * overlap_score +   # Entity weight
        0.10 * historical_boost  # History weight
    ),  # = 0.87
)
```

#### Step 2: Composite Score & Confidence Band

```python
composite = (
    0.50 * max_cosine +          # Best cosine across candidates
    0.30 * max_overlap +         # Best overlap across candidates
    0.20 * historical_weight     # 1.0 if exact hash, 0.8×similarity if fuzzy, 0.0 if none
)

confidence_band:
  HIGH  → composite >= 0.75
  MED   → composite >= 0.50
  LOW   → composite < 0.50
```

#### Step 3: Route Decision

This is the **cost optimization step** — determines whether to call Claude or skip LLM entirely:

```
┌────────────────────────────────────────────────────────────┐
│                  ROUTING DECISION TREE                      │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  composite >= 0.80 AND has_exact_history?                  │
│    YES → FAST_TRACK (auto-FIT, $0.00)                     │
│    NO  ↓                                                   │
│                                                            │
│  composite < 0.40 AND no_candidates AND no_history?        │
│    YES → SOFT_GAP (auto-GAP, $0.00)                       │
│    NO  ↓                                                   │
│                                                            │
│  Otherwise → LLM (full Claude chain-of-thought, ~$0.01)   │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

Module-specific YAML files can override `fast_track_fit` and `soft_gap` thresholds.

### Output

```python
{
    "match_results": [
        MatchResult(
            atom_id=UUID("..."),
            candidates=[ScoredCandidate(...)],
            composite_score=0.82,
            confidence_band=ConfidenceBand.HIGH,
            route_decision=RouteDecision.LLM,
            has_exact_history=True,
        ),
        ...
    ],
    "matching_errors": [...],
}
```

---

## 8. Phase 4 — Classification Agent

> **Purpose:** Produce the final FIT / PARTIAL_FIT / GAP verdict for each requirement atom, either via LLM chain-of-thought or automatic classification based on the Phase 3 route.

### Input

```python
{
    "atoms": list[RequirementAtom],
    "match_results": list[MatchResult],
    "retrieval_contexts": list[RetrievalContext],
    "llm_cost_usd": 0.0,
}
```

### Processing Steps (batched, 10 atoms at a time)

#### Pre-flight: Cost Check

```python
# Estimate total LLM cost before starting
# Warn if exceeds budget threshold
# Hard stop if > MAX_LLM_COST_USD_PER_RUN ($5.00 default)
```

#### Route-Based Classification

| Route | Action | LLM Cost | Confidence |
|-------|--------|----------|------------|
| **FAST_TRACK** | Auto-classify as FIT using best historical match | $0.00 | 0.95 |
| **SOFT_GAP** | Auto-classify as GAP, flag for human review | $0.00 | 0.50 |
| **LLM** | Full Claude chain-of-thought classification | ~$0.01/atom | varies |

#### FAST_TRACK Path (no LLM)

```python
ClassificationResult(
    verdict=Verdict.FIT,
    confidence=0.95,
    matched_capability=best_candidate.name,
    rationale="FAST_TRACK: Exact match found in historical fitment database...",
    route_taken=RouteDecision.FAST_TRACK,
    llm_model=None,
    prompt_tokens=0,
    completion_tokens=0,
)
```

#### SOFT_GAP Path (no LLM)

```python
ClassificationResult(
    verdict=Verdict.GAP,
    confidence=0.50,
    gap_description="No matching D365 capabilities were retrieved...",
    rationale="SOFT_GAP: Composite retrieval score below threshold...",
    caveats=["Confidence is low — recommend consultant manual review"],
    route_taken=RouteDecision.SOFT_GAP,
    needs_review=True,             # Flagged for human review
    sanity_flags=["soft_gap_auto_classified"],
)
```

#### LLM Path (Claude chain-of-thought)

**System Prompt** (`classification_system.j2`):
```
You are a D365 fitment classifier. Classify business requirements against
Dynamics 365 capabilities.

Guidelines:
- FIT: D365 capability fully satisfies the requirement
- PARTIAL_FIT: Capability satisfies with configuration or ISV addon
- GAP: No D365 capability covers this requirement

Output XML with: verdict, confidence, matched_capability, gap_description,
config_needed, rationale, caveats
```

**User Prompt** (`classification_user.j2`):
```
Requirement: "Support three-way matching for vendor invoices"
Module: AP | Priority: MUST | Country: DE | Intent: FUNCTIONAL

Semantic Match Score: 0.82 (HIGH)

Top Candidates:
1. Three-Way Matching: Validates vendor invoices against PO and receipt...
2. Invoice Register: Preliminary AP entry before full approval...

Historical Decisions:
- "Three-way matching for invoices" → FIT (confidence: 1.0)

Classify this requirement.
```

**LLM Response (XML):**
```xml
<classification>
    <verdict>FIT</verdict>
    <confidence>0.92</confidence>
    <matched_capability>Three-Way Matching</matched_capability>
    <gap_description></gap_description>
    <config_needed>Enable invoice matching policy in AP parameters</config_needed>
    <rationale>The requirement for three-way matching is directly supported
    by D365's built-in invoice matching validation...</rationale>
    <caveats>Requires AP license; MS Learn verification recommended</caveats>
</classification>
```

#### Sanity Checking

After classification, rules check for inconsistencies:
- FIT without `matched_capability` → flag for review
- Confidence < 0.50 for FIT → flag
- Contradicts match result heavily → flag

Flagged atoms are added to `human_review_required[]`.

### Output

```python
{
    "classification_results": list[ClassificationResult],
    "llm_cost_usd": 3.42,                    # Updated running total
    "human_review_required": ["atom-id-1", "atom-id-2"],
    "classification_errors": [...],
}
```

### Example ClassificationResult

```python
ClassificationResult(
    id=UUID("..."),
    atom_id=UUID("550e8400-..."),
    verdict=Verdict.FIT,
    confidence=0.92,
    matched_capability="Three-Way Matching",
    gap_description=None,
    config_needed="Enable invoice matching policy in AP module settings",
    rationale="The requirement for three-way matching...",
    caveats=["Requires AP license"],
    route_taken=RouteDecision.LLM,
    llm_model="claude-3-5-sonnet-20241022",
    prompt_tokens=428,
    completion_tokens=156,
    needs_review=False,
    sanity_flags=[],
)
```

---

## 9. Human-in-the-Loop Interrupt

> **Purpose:** Pause the pipeline after Phase 4 so a D365 consultant can review AI classifications and override incorrect verdicts before final validation.

### How It Works

```
Phase 4 completes
       ↓
LangGraph hits interrupt_before=["validation"]
       ↓
Pipeline PAUSES — state is checkpointed
       ↓
SSE event to frontend: { type: "pipeline_paused", status: "AWAITING_REVIEW" }
       ↓
Frontend fetches results: GET /runs/{id}/results
       ↓
Phase5Validation component shows review queue
       ↓
Consultant reviews items (especially needs_review=true atoms)
  - Can approve AI verdict (same verdict)
  - Can override to different verdict (FIT→GAP, GAP→PARTIAL_FIT, etc.)
  - Must provide reason (min 10 chars) for overrides
       ↓
Frontend submits: PATCH /runs/{id}/review
  {
    "decisions": [
      { "atom_id": "...", "verdict": "PARTIAL_FIT", "reason": "...", "reviewed_by": "john" },
      { "atom_id": "...", "verdict": "FIT", "reason": "Approved", "reviewed_by": "john" },
    ]
  }
       ↓
Backend:
  1. Convert to ConsultantDecision objects
  2. graph.aupdate_state(config, {"consultant_decisions": decisions})
  3. graph.ainvoke(None, config=config)  → resumes pipeline
       ↓
Phase 5 (Validation) node executes
```

### What the Consultant Sees

The review queue table shows:

| Column | Source |
|--------|--------|
| Atom ID | `classificationResult.requirementId` |
| Requirement Text | `classificationResult.requirementText` |
| AI Verdict | `classificationResult.classification` (FIT/PARTIAL_FIT/GAP) |
| Confidence | `classificationResult.confidence` (0-100% meter) |
| Action | Override button → opens modal |

Low-confidence items (< 65%) are highlighted with amber border.

---

## 10. Phase 5 — Validation & Output Agent

> **Purpose:** Apply consultant overrides, detect cross-requirement conflicts, generate audit trail, produce the Excel fitment matrix and Word FDD document.

### Input

```python
{
    "classification_results": list[ClassificationResult],
    "atoms": list[RequirementAtom],
    "retrieval_contexts": list[RetrievalContext],
    "consultant_decisions": list[ConsultantDecision],
    "llm_cost_usd": 3.42,
    "run_id": "636968f4-...",
}
```

### Processing Steps

#### Step 1: Apply Overrides (`override_handler.py`)

For each consultant decision:

```python
if decision.is_override:
    # Replace verdict and prepend rationale
    new_result = original.model_copy(update={
        "verdict": decision.verdict,
        "rationale": f"CONSULTANT OVERRIDE: {decision.reason}\n\n"
                     f"ORIGINAL AI RATIONALE: {original.rationale}",
        "needs_review": False,
    })
else:
    # Approve — just clear the review flag
    new_result = original.model_copy(update={"needs_review": False})

# Record override for audit
ConsultantOverride(
    atom_id, original_verdict, override_verdict,
    reason, reviewed_by, reviewed_at
)
```

**Persist to databases (graceful if unavailable):**
- PostgreSQL `consultant_overrides` table — audit record
- pgvector `historical_fitments` — re-embed atom text, write for future RAG retrieval

#### Step 2: Conflict Detection (`consistency_checker.py`)

Detects cross-requirement inconsistencies:

| Conflict Type | Detection Rule | Severity |
|--------------|----------------|----------|
| `capability_contradiction` | Same capability → conflicting verdicts | WARNING |
| `country_inconsistency` | Same requirement, different countries → different verdicts | WARNING |
| `confidence_cluster_warning` | Cluster of low-confidence results | WARNING |
| `dependency_conflict` | Cross-requirement dependency issues | WARNING |

Returns `ConflictReport` with list of `ConflictEntry` objects.

#### Step 3: Audit Trail

One `AuditEntry` per classification result:

```python
AuditEntry(
    run_id=run_id,
    atom_id=result.atom_id,
    phase="validation",
    action="validated",
    verdict=result.verdict,
    actor="system",
    metadata={
        "route": result.route_taken.value,
        "confidence": result.confidence,
        "overridden": True/False,
    },
)
```

Written to PostgreSQL `audit_trail` table (graceful if unavailable).

#### Step 4: Final Batch Construction

```python
ValidatedFitmentBatch(
    run_id=run_id,
    run_status=RunStatus.COMPLETED,
    results=updated_results,          # Post-override classifications
    overrides=overrides_applied,      # All consultant overrides
    conflict_report=conflict_report,  # Cross-requirement conflicts
    audit_trail=audit_trail,          # Full decision history
    total_atoms=len(atoms),
    total_llm_cost_usd=3.42,
    completed_at=datetime.utcnow(),
)
```

#### Step 5: Excel Report Generation (`report_generator.py`)

Generates `fitment_matrix_{run_id}_{timestamp}.xlsx` with **18 columns**:

| Column | Description |
|--------|------------|
| Atom ID | UUID |
| Module | D365 module (AP, AR, GL, etc.) |
| Sub-module | Sub-module name |
| Priority | MUST / SHOULD / COULD / WONT |
| Intent | FUNCTIONAL / NFR / INTEGRATION / etc. |
| Country | 2-letter ISO code |
| Completeness Score | 0-100 |
| Source Ref | File + row/section reference |
| Requirement Text | Full normalized text |
| **Verdict** | **FIT / PARTIAL_FIT / GAP** (color-coded) |
| Matched Capability | D365 capability name |
| Gap Description | What D365 can't cover |
| Configuration Needed | Config steps for PARTIAL_FIT |
| Caveats | License, localization notes |
| Rationale | AI chain-of-thought or override reason |
| Route Taken | FAST_TRACK / LLM / SOFT_GAP |
| Sanity Flags | Triggered sanity check rules |
| Overridden By | Consultant name (if overridden) |

**Color coding:** Green (FIT), Yellow (PARTIAL_FIT), Red (GAP)

#### Step 6: FDD Document (on-demand via API)

The FDD (`.docx`) is generated on-demand when the user clicks "Download FDD" in the UI.
It calls `GET /runs/{id}/fdd` which invokes `fdd_generator.generate_fdd()`.

**Document structure:**
1. **Cover page** — Title, run ID, generation timestamp
2. **Executive Summary** — Color-coded stats table (FIT/PARTIAL/GAP counts + percentages)
3. **FIT Requirements** — Each requirement with matched D365 capability, config notes, rationale
4. **PARTIAL FIT Requirements** — Requirements needing configuration/customization
5. **GAP Requirements** — Custom X++ development requirements with gap descriptions
6. **Consultant Overrides** — Table of all overrides with reasons (if any)

### Output

```python
{
    "validated_batch": ValidatedFitmentBatch,
    "output_path": "/outputs/fitment_matrix_636968f4_20250330_144532.xlsx",
}
```

---

## 11. SSE Streaming & Frontend State

### SSE Event Types

The backend emits these events during pipeline execution:

| Event Type | When | Payload |
|-----------|------|---------|
| `state` | On SSE connect (initial snapshot) | Full progress state |
| `phase_start` | Phase begins processing | `{ phase: "ingestion" }` |
| `phase_complete` | Phase finishes successfully | `{ phase: "ingestion", stats: {...} }` |
| `pipeline_paused` | Interrupted before validation | `{ status: "AWAITING_REVIEW", message: "..." }` |
| `pipeline_complete` | All phases done | `{ status: "COMPLETED" }` |
| `pipeline_error` | Fatal error | `{ message: "..." }` |
| `keepalive` | No events for 300s | `{}` |
| `done` | Stream finished | `{}` |

### Phase Stats Emitted

| Phase | Stats Keys |
|-------|-----------|
| Ingestion | `totalAtoms`, `modules`, `ambiguous`, `duplicates` |
| Retrieval | `capabilitiesRetrieved`, `msLearnRefs`, `historicalMatches`, `avgConfidence` |
| Matching | `fastTrack`, `needsLLM`, `likelyGap`, `avgScore` |
| Classification | `fit`, `partialFit`, `gap`, `avgConfidence`, `lowConfidence` |
| Validation | `totalVerified`, `overrides`, `conflicts`, `exportReady` |

### Frontend SSE Connection (`api.ts` → `connectToStream`)

```typescript
const es = new EventSource(`/api/v1/runs/${runId}/stream`);

es.onmessage = (e) => {
    const event = JSON.parse(e.data);
    switch (event.type) {
        case "state":            // Initial progress snapshot
        case "phase_start":      // → startPhase(phase) in Zustand
        case "phase_complete":   // → completePhase(phase, stats) in Zustand
        case "pipeline_paused":  // → fetch results, show review queue
        case "pipeline_complete":// → mark run complete, enable exports
        case "pipeline_error":   // → show error banner
        case "done":             // → close EventSource
    }
};
```

### Zustand Store Updates

```typescript
// Phase lifecycle
startPhase("ingestion")       // status → "processing", progress → 0
updatePhaseProgress("ingestion", 50, { step: "Parsing..." })
completePhase("ingestion", { totalAtoms: 18, modules: 5 })

// Data population (after fetching results)
setRequirementAtoms(atoms)
setClassificationResults(results)
setValidatedFitments(fitments)
setRunStats({ totalRequirements: 18, fit: 10, partialFit: 5, gap: 3 })

// Override (from consultant review)
overrideClassification(requirementId, "PARTIAL_FIT", "Needs config", "john")
```

### Dashboard UI (`app/dashboard/page.tsx`)

```
activePhaseIndex determines which component renders:

  0 → Phase1Ingestion   (file upload + atom extraction)
  1 → Phase2Retrieval   (RAG search progress)
  2 → Phase3Matching    (scoring + routing stats)
  3 → Phase4Classification (FIT/PARTIAL/GAP verdicts)
  4 → Phase5Validation  (review queue + export + FDD download)
```

---

## 12. Final Outputs

### Available Downloads

| Endpoint | Format | Filename | Content |
|----------|--------|----------|---------|
| `GET /runs/{id}/export` | `.xlsx` | `fitment_matrix.xlsx` | Full fitment matrix with 18 columns, color-coded |
| `GET /runs/{id}/fdd` | `.docx` | `FDD_{run_id}.docx` | Structured FDD organized by verdict category |

### API Endpoints Summary

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/v1/runs` | Upload BRD files, start pipeline |
| `GET` | `/api/v1/runs/{id}/stream` | SSE real-time progress events |
| `GET` | `/api/v1/runs/{id}/status` | Current run status + phase stats |
| `GET` | `/api/v1/runs/{id}/results` | Serialized atoms + classifications (JSON) |
| `GET` | `/api/v1/runs/{id}/review` | Items flagged for human review |
| `PATCH` | `/api/v1/runs/{id}/review` | Submit consultant overrides, resume pipeline |
| `GET` | `/api/v1/runs/{id}/export` | Download fitment_matrix.xlsx |
| `GET` | `/api/v1/runs/{id}/fdd` | Generate & download FDD document (.docx) |
| `GET` | `/health` | Health check |

---

## 13. External Services

| Service | Phases | Purpose | Failure Mode |
|---------|--------|---------|-------------|
| **Claude API** | 1, 4 | LLM extraction + classification | Hard error |
| **Qdrant** | 2 | D365 KB + MS Learn vector search | Source 1: hard error; Source 2: soft |
| **PostgreSQL** | All | Run tracking, audit trail | Graceful (pipeline continues) |
| **pgvector** | 2, 5 | Historical fitment storage + retrieval | Soft (empty results) |
| **Redis** | 2 | Retrieval context cache (24h TTL) | Soft (cache miss, re-retrieve) |
| **bge-large-en-v1.5** | 2, 3, 5 | Dense text embeddings | Hard error |
| **CrossEncoder** | 2 | Candidate reranking | Hard error |

---

## 14. Data Shape Summary Table

| Phase | Input | Output | LLM Calls | Cost |
|-------|-------|--------|-----------|------|
| **1. Ingestion** | Raw files (xlsx/docx/pdf) | `RequirementAtom[]` | ~n/20 batched | ~$0.05 |
| **2. Retrieval** | `RequirementAtom[]` | `RetrievalContext[]` | 0 | $0.00 |
| **3. Matching** | `RetrievalContext[]` | `MatchResult[]` | 0 | $0.00 |
| **4. Classification** | `MatchResult[]` | `ClassificationResult[]` | ~n×0.6 (40% auto-routed) | ~$0.01/atom |
| **5. Validation** | `ConsultantDecision[]` | `ValidatedFitmentBatch` | 0 | $0.00 |

### Key Data Types (Phase → Phase)

```
Files → [Phase 1] → RequirementAtom[]
                          ↓
                     [Phase 2] → RetrievalContext[]  (top-5 capabilities per atom)
                                      ↓
                                 [Phase 3] → MatchResult[]  (scores + route decisions)
                                                  ↓
                                             [Phase 4] → ClassificationResult[]  (FIT/PARTIAL/GAP)
                                                              ↓
                                                         [INTERRUPT → ConsultantDecision[]]
                                                              ↓
                                                         [Phase 5] → ValidatedFitmentBatch
                                                                          ↓
                                                                    ┌─────┴─────┐
                                                                    │           │
                                                              Excel (.xlsx)  FDD (.docx)
```

---

## Key Files Reference

| Category | File | Purpose |
|----------|------|---------|
| **Frontend** | `ui/app/dashboard/page.tsx` | Main dashboard, SSE wiring |
| | `ui/store/useDynafitStore.ts` | Zustand state management |
| | `ui/lib/api.ts` | API client (DynafitAPI class) |
| | `ui/types/index.ts` | All TypeScript interfaces |
| | `ui/components/phases/Phase{1-5}*.tsx` | Phase UI components |
| | `ui/components/modals/OverrideModal.tsx` | Consultant override dialog |
| **Backend API** | `api/routes.py` | FastAPI endpoints + SSE streaming |
| **Orchestration** | `core/state/graph.py` | LangGraph pipeline definition |
| | `core/state/requirement_state.py` | Pipeline state TypedDict |
| **Agents** | `agents/ingestion/agent.py` | Phase 1 entry point |
| | `agents/ingestion/doc_parser.py` | Document format parsing |
| | `agents/ingestion/req_extractor.py` | LLM atom extraction |
| | `agents/ingestion/normalizer.py` | Term alignment + dedup |
| | `agents/ingestion/validator.py` | Schema validation |
| | `agents/retrieval/agent.py` | Phase 2 — RAG retrieval |
| | `agents/matching/agent.py` | Phase 3 — scoring + routing |
| | `agents/classification/agent.py` | Phase 4 — LLM classification |
| | `agents/validation/agent.py` | Phase 5 — validation entry |
| | `agents/validation/override_handler.py` | Apply consultant overrides |
| | `agents/validation/consistency_checker.py` | Cross-requirement conflicts |
| | `agents/validation/report_generator.py` | Excel generation |
| | `agents/validation/fdd_generator.py` | FDD Word document generation |
| **Schemas** | `core/schemas/enums.py` | All enums (Verdict, D365Module, etc.) |
| | `core/schemas/requirement_atom.py` | RequirementAtom model |
| | `core/schemas/retrieval_context.py` | RetrievalContext model |
| | `core/schemas/match_result.py` | MatchResult + ScoredCandidate |
| | `core/schemas/classification_result.py` | ClassificationResult + ValidatedFitmentBatch |
| **Infrastructure** | `infrastructure/storage/postgres_client.py` | PostgreSQL client |
| | `infrastructure/vector_db/qdrant_client.py` | Qdrant vector DB client |
| | `infrastructure/vector_db/pgvector_client.py` | pgvector historical fitments |
| | `infrastructure/vector_db/embedder.py` | bge-large-en-v1.5 embedder |
| | `infrastructure/cache/redis_client.py` | Redis cache client |
| **Config** | `core/config/settings.py` | Environment-driven settings |
| | `core/config/thresholds.py` | Phase-specific thresholds |
