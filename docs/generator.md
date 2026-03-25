# DYNAFIT — Generator Context
> Antigravity IDE | Project: DYNAFIT Requirement Fitment Engine
> Use this file when generating new code, prompts, schemas, or configs.
> All generated code must conform to the patterns and conventions documented here.

---

## Code Generation Rules

### Non-Negotiables
- All schemas are **Pydantic v2, frozen=True** (immutable). Use `model_copy(update={...})` to produce variants.
- All agent logic is **async**. Use `asyncio.gather` for parallelism.
- **Never** call `anthropic` directly. All LLM calls go through `llm_call()` in `infrastructure/llm/client.py`.
- **Never** hardcode threshold values. Import from `core.config.thresholds.THRESHOLDS`.
- **Never** read `os.environ` directly. Use `from core.config.settings import settings`.
- Use `structlog.get_logger()` for all logging. Use structured key=value format.
- All agent nodes return **partial state dicts** — only the keys they own.

### Python Version & Style
- Python 3.11+. Use `X | Y` union syntax, not `Optional[X]`.
- Type hints everywhere. No bare `dict` or `list` without type params in function signatures.
- Docstrings on all classes and public methods.

---

## Agent Node Template

Every LangGraph node follows this exact pattern:

```python
"""
agents/{phase}/{role}.py
Phase N — {Name} LangGraph node.
"""
from typing import Any
import structlog

log = structlog.get_logger()
PHASE = "{phase_name}"

async def run(state: dict[str, Any]) -> dict[str, Any]:
    run_id = state["run_id"]
    # Read inputs from state
    items = state.get("{input_key}", [])
    
    log.info(f"{PHASE}.start", run_id=run_id, count=len(items))
    
    results = []
    errors: list[dict] = []
    
    # ... processing ...
    
    log.info(f"{PHASE}.complete", run_id=run_id, results=len(results), errors=len(errors))
    
    return {
        "{output_key}": results,
        "{error_key}": errors,
        "pipeline_errors": state.get("pipeline_errors", []) + errors,
    }
```

---

## Missing File: `agents/retrieval/agent.py`

Phase 2 orchestrator. Reads `atoms`, writes `retrieval_contexts` and `retrieval_errors`.

```python
"""
agents/retrieval/agent.py
Phase 2 — Knowledge Retrieval Agent (RAG) LangGraph node.
"""
import asyncio
from typing import Any
import structlog

from agents.retrieval.query_builder import QueryBuilder
from agents.retrieval.parallel_retriever import ParallelRetriever
from agents.retrieval.rrf_fusion import RRFFusion
from agents.retrieval.reranker import CrossEncoderReranker
from agents.retrieval.context_assembler import ContextAssembler
from core.config.settings import settings
from core.schemas.requirement_atom import RequirementAtom
from core.schemas.retrieval_context import RetrievalContext

log = structlog.get_logger()
PHASE = "retrieval"

async def run(state: dict[str, Any]) -> dict[str, Any]:
    run_id = state["run_id"]
    atoms: list[RequirementAtom] = state.get("atoms", [])
    kb_version = state.get("kb_version", settings.KB_VERSION)

    log.info(f"{PHASE}.start", run_id=run_id, atom_count=len(atoms))

    query_builder = QueryBuilder()
    retriever = ParallelRetriever()
    fuser = RRFFusion()
    reranker = CrossEncoderReranker()
    assembler = ContextAssembler()

    contexts: list[RetrievalContext] = []
    errors: list[dict] = []

    tasks = [
        _retrieve_single(atom, kb_version, query_builder, retriever, fuser, reranker, assembler, run_id)
        for atom in atoms
    ]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    for atom, outcome in zip(atoms, outcomes):
        if isinstance(outcome, Exception):
            log.error(f"{PHASE}.atom_failed", run_id=run_id, atom_id=str(atom.id), error=str(outcome))
            errors.append({"phase": PHASE, "atom_id": str(atom.id), "error": str(outcome)})
        else:
            contexts.append(outcome)

    log.info(f"{PHASE}.complete", run_id=run_id, contexts=len(contexts), errors=len(errors))

    return {
        "retrieval_contexts": contexts,
        "retrieval_errors": errors,
        "pipeline_errors": state.get("pipeline_errors", []) + errors,
    }

async def _retrieve_single(atom, kb_version, query_builder, retriever, fuser, reranker, assembler, run_id):
    # Check cache first
    cached = await assembler.get_cached(atom, kb_version)
    if cached:
        log.debug(f"{PHASE}.cache_hit", atom_id=str(atom.id))
        return cached

    query = await query_builder.build(atom)
    raw = await retriever.retrieve_all(query, module=atom.module.value)

    fused = fuser.fuse(
        capability_results=raw["capabilities"],
        ms_learn_results=raw["ms_learn"],
        sources_available=raw["sources_available"],
    )

    reranked = await reranker.rerank(atom.text, fused["capabilities"])

    context = assembler.assemble(
        atom=atom,
        top_capabilities=reranked[:settings.RERANKER_TOP_K],
        ms_learn_refs=fused["ms_learn"],
        prior_fitments=raw["historical"],
        sources_available=raw["sources_available"],
    )

    await assembler.cache(context, kb_version)
    return context
```

---

## Missing File: `infrastructure/storage/redis_client.py`

```python
"""
infrastructure/storage/redis_client.py
Redis client for RetrievalContext caching.
"""
import json
import structlog
import redis.asyncio as aioredis
from core.config.settings import settings
from core.schemas.retrieval_context import RetrievalContext

log = structlog.get_logger()

class DynafitRedisClient:
    def __init__(self):
        self._client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    async def get_retrieval_context(self, key: str) -> RetrievalContext | None:
        try:
            data = await self._client.get(key)
            if data:
                return RetrievalContext.model_validate_json(data)
        except Exception as e:
            log.warning("redis_get_failed", key=key, error=str(e))
        return None

    async def set_retrieval_context(self, key: str, context: RetrievalContext, ttl: int = 86400) -> None:
        try:
            await self._client.setex(key, ttl, context.model_dump_json())
        except Exception as e:
            log.warning("redis_set_failed", key=key, error=str(e))

    async def health_check(self) -> bool:
        try:
            await self._client.ping()
            return True
        except Exception as e:
            log.error("redis_health_check_failed", error=str(e))
            return False

redis_client = DynafitRedisClient()
```

---

## Missing File: `infrastructure/vector_db/pgvector_client.py`

```python
"""
infrastructure/vector_db/pgvector_client.py
PostgreSQL + pgvector for historical fitment lookup.
"""
import structlog
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from core.config.settings import settings
from core.schemas.retrieval_context import HistoricalFitmentMatch

log = structlog.get_logger()

class PgVectorClient:
    def __init__(self):
        self._engine = create_async_engine(settings.POSTGRES_URL, pool_size=settings.POSTGRES_POOL_MIN)
        self._session_factory = sessionmaker(self._engine, class_=AsyncSession, expire_on_commit=False)

    async def find_by_hash_or_similar(
        self,
        atom_hash: str,
        embedding: list[float],
        module: str,
        limit: int = 5,
    ) -> list[HistoricalFitmentMatch]:
        async with self._session_factory() as session:
            # First try exact hash match
            result = await session.execute(
                text("""
                    SELECT fitment_id, original_text, verdict, confidence, rationale,
                           wave_id, overridden_by_consultant, matched_capability,
                           1.0 as similarity, true as is_exact
                    FROM historical_fitments
                    WHERE atom_hash = :hash AND module = :module
                    LIMIT 1
                """),
                {"hash": atom_hash, "module": module}
            )
            rows = result.fetchall()

            if not rows:
                # Fall back to embedding similarity
                vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
                result = await session.execute(
                    text("""
                        SELECT fitment_id, original_text, verdict, confidence, rationale,
                               wave_id, overridden_by_consultant, matched_capability,
                               1 - (embedding <=> :vec::vector) as similarity,
                               false as is_exact
                        FROM historical_fitments
                        WHERE module = :module
                          AND 1 - (embedding <=> :vec::vector) > 0.75
                        ORDER BY similarity DESC
                        LIMIT :limit
                    """),
                    {"vec": vec_str, "module": module, "limit": limit}
                )
                rows = result.fetchall()

            return [
                HistoricalFitmentMatch(
                    fitment_id=r.fitment_id,
                    original_text=r.original_text,
                    verdict=r.verdict,
                    confidence=r.confidence,
                    rationale=r.rationale,
                    wave_id=r.wave_id,
                    overridden_by_consultant=r.overridden_by_consultant,
                    similarity_to_current=float(r.similarity),
                    is_exact_match=bool(r.is_exact),
                )
                for r in rows
            ]

pgvector_client = PgVectorClient()
```

---

## Jinja2 Prompt Templates

### `core/prompts/ingestion_extract.j2`

```jinja2
You are a D365 F&O business analyst. Extract atomic business requirements from the source document.

Rules:
- One requirement per business need (atomic — not compound)
- Use D365 canonical terminology (e.g. "vendor payment proposal" not "auto-pay")
- Tag each with the correct D365 module: AP, AR, GL, FA, SCM, WMS, MFG, PM, HR, PAYROLL, BUDGET, CASH, TAX, CONSOLIDATION
- MoSCoW: MUST (mandatory/critical/shall), SHOULD (expected/needs to), COULD (nice to have), WONT (out of scope)
- IntentType: FUNCTIONAL, NFR, INTEGRATION, REPORTING, DATA_MIGRATION
- completeness_score: 0-100 (penalise vague requirements)
- If country-specific, include 2-letter ISO code
{% if rejection_reason %}

PREVIOUS ATTEMPT FAILED: {{ rejection_reason }}
Try harder. Extract every discrete requirement you can identify.
{% endif %}

Return ONLY a JSON array. No preamble, no markdown fences.

[
  {
    "text": "normalized requirement text",
    "raw_text": "original text as-is",
    "module": "AP",
    "sub_module": "Vendor invoicing",
    "priority": "MUST",
    "intent": "FUNCTIONAL",
    "country": null,
    "completeness_score": 75,
    "source_ref": "{{ source_ref }}"
  }
]
```

### `core/prompts/classification_system.j2`

```jinja2
You are a senior D365 F&O functional consultant performing fitment analysis for the {{ module }} module.

Your task: Classify each requirement as FIT, PARTIAL_FIT, or GAP against standard D365 F&O capabilities.

Definitions:
- FIT: Standard D365 covers the requirement fully out-of-the-box or with minimal standard configuration (no custom code)
- PARTIAL_FIT: D365 covers the requirement partially; specific configuration, personalization, or ISV add-on is needed
- GAP: D365 does not cover this requirement; custom X++ development or significant workaround required

Reasoning approach (follow this order):
1. Does a matching D365 {{ module }} capability exist in the candidates provided?
2. Does it fully cover the requirement intent, or only partially?
3. What is the specific gap between what D365 offers and what the requirement demands?
4. Does historical evidence from prior waves support or contradict this classification?

{% if module_specific_notes %}
Module-specific guidance for {{ module }}:
{{ module_specific_notes }}
{% endif %}

Respond ONLY with a <classification> XML block. No preamble or explanation outside the tags.

<classification>
  <verdict>FIT|PARTIAL_FIT|GAP</verdict>
  <confidence>0.0-1.0</confidence>
  <matched_capability>Name of D365 capability (required for FIT/PARTIAL_FIT)</matched_capability>
  <gap_description>What is missing (required for GAP/PARTIAL_FIT)</gap_description>
  <config_needed>Configuration steps required (required for PARTIAL_FIT)</config_needed>
  <rationale>Minimum 30-word explanation of your reasoning</rationale>
  <caveats>License requirement; localization note; etc (semicolon-separated)</caveats>
</classification>
```

### `core/prompts/classification_user.j2`

```jinja2
## Requirement

**Text:** {{ requirement_text }}
**Module:** {{ module }}{% if country %} | **Country:** {{ country }}{% endif %}
**Priority:** {{ priority }}
**Match Score:** {{ "%.2f"|format(composite_score) }} ({{ confidence_band }})

---

## Top D365 {{ module }} Capabilities

{% for cap in top_candidates %}
### {{ loop.index }}. {{ cap.name }} (score: {{ "%.3f"|format(cap.score) }})
**Module:** {{ cap.module }}{% if cap.sub_module %} > {{ cap.sub_module }}{% endif %}
**Description:** {{ cap.description }}
{% if cap.configuration_notes %}**Config Notes:** {{ cap.configuration_notes }}{% endif %}
{% if cap.license_requirement %}**License:** {{ cap.license_requirement }}{% endif %}
{% if cap.localization_gaps %}**Localization Gaps:** {{ cap.localization_gaps }}{% endif %}

{% endfor %}

{% if prior_decisions %}
---

## Historical Precedent (Prior Waves)

{% for prior in prior_decisions %}
- **Wave {{ prior.wave_id }}:** {{ prior.verdict }} (confidence: {{ prior.confidence }})
  Original: "{{ prior.original_text[:100] }}"
  Rationale: {{ prior.rationale[:150] }}
  {% if prior.overridden_by_consultant %}*(Consultant overridden)*{% endif %}
{% endfor %}
{% endif %}

Classify this requirement now.
```

---

## Module YAML Template

Use this to generate any new module config under `core/config/module_config/{module}.yaml`:

```yaml
module: GL                          # D365Module enum value
display_name: General Ledger

signal_weights:
  cosine: 0.50                      # Must sum to 1.0
  overlap: 0.30
  history: 0.20

threshold_adjustments:
  # fast_track_fit: 0.85            # Uncomment to override global default

d365_localization_gaps:
  IN:
    - "Description of India-specific gap"
  DE:
    - "Description of Germany-specific gap"

canonical_terms:
  "business jargon": "D365 canonical term"
  "another alias": "canonical form"

sub_modules:
  - "Sub-module name 1"
  - "Sub-module name 2"
```

---

## FastAPI Route Patterns

### `api/routes/runs.py` — Pipeline trigger

```python
from fastapi import APIRouter, BackgroundTasks, UploadFile, File
from uuid import uuid4
from core.state.requirement_state import make_initial_state
from core.config.settings import settings

router = APIRouter(prefix="/runs", tags=["runs"])

@router.post("/", status_code=202)
async def create_run(
    files: list[UploadFile] = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    run_id = str(uuid4())
    # Save files, build initial state, enqueue via Celery or ainvoke
    state = make_initial_state(run_id=run_id, source_files=[...], kb_version=settings.KB_VERSION)
    background_tasks.add_task(_run_pipeline, state)
    return {"run_id": run_id, "status": "QUEUED"}

@router.patch("/{run_id}/review")
async def submit_review(run_id: str, decisions: list[ConsultantDecision]):
    # Resume LangGraph after interrupt()
    # graph.ainvoke(None, config={"configurable": {"thread_id": run_id}},
    #               command=Command(resume={"consultant_decisions": decisions}))
    ...
```

---

## Schema Generation Rules

When generating new Pydantic schemas, always:

```python
from pydantic import BaseModel, ConfigDict, Field

class MySchema(BaseModel):
    model_config = ConfigDict(frozen=True)    # Always frozen

    id: UUID = Field(default_factory=uuid4)
    # Use Field() with description for every field
    # Use ge/le for numeric bounds
    # Use | None for optional fields, not Optional[]
```

---

## Enum Usage

Never create new enums. Always use from `core/schemas/enums.py`:
- `D365Module` — module codes (AP, AR, GL, FA, SCM, WMS, MFG, PM, HR, PAYROLL, BUDGET, CASH, TAX, CONSOLIDATION)
- `MoSCoW` — MUST, SHOULD, COULD, WONT
- `IntentType` — FUNCTIONAL, NFR, INTEGRATION, REPORTING, DATA_MIGRATION
- `Verdict` — FIT, PARTIAL_FIT, GAP
- `RouteDecision` — FAST_TRACK, LLM, SOFT_GAP
- `ConfidenceBand` — HIGH, MED, LOW
- `AtomStatus` — ACTIVE, ERROR, DUPLICATE, OUT_OF_SCOPE
- `RunStatus` — QUEUED, RUNNING, AWAITING_REVIEW, COMPLETED, FAILED, CANCELLED

---

## Logging Pattern

```python
import structlog
log = structlog.get_logger()

# Always include run_id and relevant entity ID
log.info("phase.event", run_id=run_id, atom_id=str(atom.id), count=n)
log.warning("sanity_check_name", atom_id=str(atom.id), score=score)
log.error("failure_event", run_id=run_id, error=str(e))
```

---

## Test File Template

```python
# tests/agents/{phase}/test_{component}.py
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

@pytest.fixture
def sample_atom():
    from core.schemas.requirement_atom import RequirementAtom
    from core.schemas.enums import D365Module, MoSCoW, IntentType, AtomStatus
    return RequirementAtom(
        atom_hash="a" * 64,
        text="The system must support three-way matching (purchase order) for all vendor invoices",
        raw_text="3-way match required for all vendor invoices",
        module=D365Module.AP,
        priority=MoSCoW.MUST,
        intent=IntentType.FUNCTIONAL,
        completeness_score=85.0,
        source_ref="test.xlsx:row_1",
        source_file="test.xlsx",
        status=AtomStatus.ACTIVE,
    )

@pytest.mark.asyncio
async def test_component(sample_atom):
    ...
```