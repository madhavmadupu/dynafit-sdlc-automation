# agents/ — AGENT.md
## Agent Layer: Rules, Patterns & Responsibilities

---

## PURPOSE OF THIS LAYER

Every file in `agents/` is a **LangGraph node function** or a **helper module** called exclusively by a node function. Agents are the "doing" layer — they orchestrate calls to `core/` (schemas, config, prompts) and `infrastructure/` (LLM, vector DB, storage) to advance the state of a `RequirementAtom` through the pipeline.

**Golden rule: Agents contain workflow logic, not business logic.**
- ✅ Agent: "retrieve top-K, then rerank, then assemble context"
- ❌ Agent: raw HTTP calls to Qdrant (that's `infrastructure/`)
- ❌ Agent: Pydantic model definitions (that's `core/schemas/`)
- ❌ Agent: hardcoded prompt strings (that's `core/prompts/`)

---

## AGENT NODE CONTRACT

Every `agent.py` file MUST export a function with this exact signature:

```python
async def run(state: RequirementState) -> dict:
    """
    LangGraph node function.
    
    Args:
        state: Current RequirementState from the graph.
    
    Returns:
        Partial dict with ONLY the keys this node updates.
        Never return the full state — LangGraph merges automatically.
    
    Raises:
        AgentError: On unrecoverable failure (triggers LangGraph retry).
    """
```

The returned dict keys must be valid `RequirementState` fields. No extra keys.

---

## ERROR HANDLING PATTERN

All agents follow this exact error handling pattern:

```python
import structlog
from core.state.requirement_state import RequirementState
from core.schemas.requirement_atom import RequirementAtom

log = structlog.get_logger()

async def run(state: RequirementState) -> dict:
    run_id = state["run_id"]
    phase = "phase_name"
    
    results = []
    errors = []
    
    for atom in state["atoms"]:
        try:
            result = await _process_atom(atom, state)
            results.append(result)
            log.info(f"{phase}.success", run_id=run_id, atom_id=str(atom.id))
        except Exception as e:
            log.error(
                f"{phase}.atom_failed",
                run_id=run_id,
                atom_id=str(atom.id),
                error=str(e),
                exc_info=True,
            )
            errors.append({"atom_id": str(atom.id), "error": str(e), "phase": phase})
            # DO NOT re-raise — mark atom as errored and continue
            results.append(_make_error_result(atom))
    
    return {
        f"{phase}_results": results,
        "pipeline_errors": state.get("pipeline_errors", []) + errors,
    }
```

**Key principles:**
- Single atom failure NEVER aborts the batch
- Always log with structured context (run_id, atom_id, phase)
- Append errors to `pipeline_errors` in state for final reporting
- Create an error-marker result so downstream phases know to skip

---

## RETRY POLICY

Each agent module that makes external calls wraps them with:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((TimeoutError, ConnectionError)),
    reraise=True,
)
async def _call_external_service(...):
    ...
```

Do not implement custom retry loops — always use `tenacity`.

---

## PHASE-SPECIFIC AGENT RULES

### Phase 1 — Ingestion Agent
- **Input formats supported**: `.xlsx`, `.xls`, `.docx`, `.doc`, `.pdf`, `.txt`, `.md`
- **Docling** is the primary parser for PDF/DOCX. Fall back to `Unstructured` if Docling fails.
- **Atomization rule**: One `RequirementAtom` per atomic business need. If a source row contains multiple needs (e.g., "The system must support 3-way matching AND automatic payment runs"), split into separate atoms. Each atom must be independently assessable.
- **Completeness score < 40** triggers re-extraction with a more targeted prompt before flagging.
- **Language normalization** is mandatory. Use the `term_aligner` to map business jargon to canonical D365 terminology (e.g., "invoice approval workflow" → "vendor invoice approval journal workflow").
- **The `validator.py` step is non-optional** — every atom must pass schema validation before leaving Phase 1. Malformed atoms are rejected back to the LLM for re-extraction (max 2 retries).

### Phase 2 — Knowledge Retrieval Agent (RAG)
- **Parallel retrieval is mandatory** — all 3 knowledge sources hit simultaneously via `asyncio.gather()`. Sequential retrieval is a performance violation.
- **RRF fusion score formula**: `score(d) = Σ 1/(k + rank(d))` where k=60. Do not change k without updating `docs/architecture/adr/`.
- **CrossEncoder model**: `ms-marco-MiniLM-L-6-v2`. Do not swap models without running eval.
- **If Qdrant is unreachable** at query time: raise `InfrastructureError` immediately. Do not fall back to keyword-only search — the quality degradation is unacceptable.
- **Historical fitments query**: Match on `(module, normalized_text_hash)` first for exact prior decisions. Fall back to semantic similarity if no exact match.
- **Cache policy**: RetrievalContexts are cached in Redis for 24h keyed by `(atom_hash, kb_version)`. Always check cache before hitting vector DB.

### Phase 3 — Semantic Matching Agent
- **Three signals feed the composite score**: (1) cosine similarity, (2) entity overlap ratio (spaCy D365 NER), (3) historical precedent weight.
- **Module-specific YAML configs** in `core/config/module_config/` define per-module threshold adjustments. For example, SCM requirements may need lower thresholds due to higher D365 coverage. Always load the correct module config.
- **Confidence band assignment** is deterministic given the composite score and module config. Never route HIGH confidence (>0.85 with history) to Phase 4 — fast-track it.
- **Dedup + subsume**: If two top-5 candidates are >0.95 similar to each other, drop the lower-scoring one. Never show duplicate capabilities to Phase 4.

### Phase 4 — Classification Agent
- **The chain-of-thought prompt MUST include** (in order): requirement text, top-5 candidate capabilities with descriptions, composite match score, confidence band, and any prior fitment decisions.
- **Structured output schema** (emitted by LLM, parsed by `response_parser.py`):
  ```xml
  <classification>
    <verdict>FIT|PARTIAL_FIT|GAP</verdict>
    <confidence>0.0-1.0</confidence>
    <matched_capability>capability_name_or_null</matched_capability>
    <gap_description>null_or_description</gap_description>
    <config_needed>null_or_config_steps</config_needed>
    <rationale>plain_english_explanation</rationale>
    <caveats>optional_list</caveats>
  </classification>
  ```
- **`response_parser.py` tries XML parse first**, falls back to regex extraction, falls back to requesting a re-generation (max 2 retries). If all fail: classify as `GAP` with `confidence=0.0` and flag for mandatory human review.
- **Sanity checker rule**: If `composite_score > 0.8` but verdict is `GAP`, flag for human review. If `composite_score < 0.4` but verdict is `FIT`, flag for human review. These are not auto-rejections — they are review flags.
- **Short-circuit**: If Phase 3 `route_decision == FAST_TRACK`, skip LLM call and emit `FIT` with the top candidate. If `route_decision == GAP` (score < 0.4 AND no historical precedent), skip LLM and emit `GAP` with `confidence=0.6`.

### Phase 5 — Validation & Output Agent
- **Consistency check uses NetworkX DiGraph** to detect cross-requirement conflicts. E.g., if Req A is classified FIT using Feature X, and Req B is classified GAP claiming Feature X doesn't exist — that's a conflict.
- **Country override YAML files** (in `core/config/module_config/`) define country-specific D365 localization gaps. Always apply before final output.
- **`interrupt()`** is called after consistency check and before report generation. The human review UI reads from LangGraph's interrupt state.
- **Override capture**: Every override MUST include a `reason` string (min 10 chars). Reason-less overrides are rejected. Reason + new_verdict is written to PostgreSQL `historical_fitments` table.
- **Excel output spec**:
  - Sheet 1: Fitment Matrix (all requirements with verdict, confidence, rationale, capability)
  - Sheet 2: GAP Summary (GAP items only with gap descriptions)
  - Sheet 3: PARTIAL FIT Config Guide (PARTIAL items with config steps)
  - Sheet 4: Audit Trail (every decision, timestamp, who approved)
  - Sheet 5: Metrics Summary (counts, override rate, avg confidence)
  - Cells color-coded: FIT=green (#C6EFCE), PARTIAL=amber (#FFEB9C), GAP=red (#FFC7CE)

---

## WHAT AGENTS MUST NEVER DO

1. **Never import from another agent's module** (e.g., `from agents.retrieval import ...` in `agents.matching`). Agents are isolated. Data passes only via `RequirementState`.
2. **Never write directly to database** (use `infrastructure/storage/` clients).
3. **Never define Pydantic models** (define in `core/schemas/`).
4. **Never write prompt strings inline** (use `core/prompts/` templates).
5. **Never call LLM directly** (use `infrastructure/llm/client.py`).
6. **Never access environment variables directly** (use `core/config/settings.py`).
7. **Never `print()`** — always use `structlog`.