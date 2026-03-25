# core/ — AGENT.md
## Core Layer: Shared Contracts, Configuration & Orchestration

---

## PURPOSE OF THIS LAYER

`core/` contains everything that is **shared across all agents** and has **no external service dependencies**. It is the foundation every other layer builds on.

**Layers and their dependencies:**
```
agents/         → depends on core/ + infrastructure/
infrastructure/ → depends on core/ (schemas, config) only
core/           → depends on nothing (pure Python + Pydantic)
```

**This is strictly enforced.** Any import of `agents/` or `infrastructure/` from within `core/` is a hard violation. `core/` must remain independently testable with zero mocking.

---

## SUB-MODULES

### `core/state/` — LangGraph State Management

#### `requirement_state.py`
Defines the single `RequirementState` typed dict that flows through the entire LangGraph pipeline.

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class RequirementState(TypedDict):
    # Run metadata
    run_id: str                                    # UUID string
    created_at: str                                # ISO datetime
    source_files: list[str]                        # Original file paths/names
    
    # Phase 1 outputs
    atoms: list[RequirementAtom]                   # After ingestion
    ingestion_errors: list[dict]                   # Atoms that failed ingestion
    
    # Phase 2 outputs
    retrieval_contexts: list[RetrievalContext]     # One per atom
    retrieval_errors: list[dict]
    
    # Phase 3 outputs
    match_results: list[MatchResult]               # One per atom
    matching_errors: list[dict]
    
    # Phase 4 outputs
    classification_results: list[ClassificationResult]
    classification_errors: list[dict]
    llm_cost_usd: float                            # Running total
    
    # Phase 5 outputs
    validated_batch: ValidatedFitmentBatch | None
    output_path: str | None
    
    # Cross-phase
    pipeline_errors: list[dict]                    # All errors across phases
    human_review_required: list[str]               # atom_ids needing review
    kb_version: str                                # Knowledge base version used
```

**Rules for state usage:**
- Agents return ONLY the keys they update (partial dict)
- Never mutate the state dict — LangGraph handles merging
- `pipeline_errors` is append-only — agents append, never overwrite
- `human_review_required` is append-only — agents append atom_ids

#### `graph.py`
Defines and compiles the LangGraph `StateGraph`.

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

def build_graph(checkpointer: PostgresSaver) -> CompiledGraph:
    graph = StateGraph(RequirementState)
    
    # Add nodes (one per phase)
    graph.add_node("ingestion", ingestion_agent.run)
    graph.add_node("retrieval", retrieval_agent.run)
    graph.add_node("matching", matching_agent.run)
    graph.add_node("classification", classification_agent.run)
    graph.add_node("validation", validation_agent.run)
    
    # Linear flow with conditional routing
    graph.set_entry_point("ingestion")
    graph.add_edge("ingestion", "retrieval")
    graph.add_edge("retrieval", "matching")
    graph.add_edge("matching", "classification")
    
    # Conditional: if human review needed, interrupt before validation
    graph.add_conditional_edges(
        "classification",
        route_after_classification,
        {
            "validation": "validation",
            "human_review": "validation",  # interrupt() handles the pause
        }
    )
    graph.add_edge("validation", END)
    
    return graph.compile(checkpointer=checkpointer, interrupt_before=["validation"])
```

**Checkpoint config:**
- Use `PostgresSaver` for production (persistent across restarts)
- Use `MemorySaver` for testing only
- Thread ID = `run_id` — always pass `config={"configurable": {"thread_id": run_id}}`

---

### `core/schemas/` — Pydantic Data Contracts

All inter-agent data structures live here. **This is the contract layer** — changing a schema is a breaking change and requires a `schema_changelog.md` entry.

#### Schema design rules:
1. **All schemas use Pydantic v2** (`from pydantic import BaseModel, Field`)
2. **Strict mode** on all models: `model_config = ConfigDict(strict=True, frozen=True)`
3. **Frozen models**: All inter-agent schemas are immutable after creation
4. **UUIDs** for all entity IDs: `id: UUID = Field(default_factory=uuid4)`
5. **No Optional without a default**: Either `Optional[X] = None` or provide a default
6. **All fields documented**: Every field has a `Field(description="...")` 
7. **Validators for constraints**: Use `@field_validator` for business rule validation

#### Key schema summaries:

**`RequirementAtom`**:
```python
class RequirementAtom(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    
    id: UUID = Field(default_factory=uuid4)
    text: str = Field(min_length=10, description="Normalized requirement text")
    module: D365Module = Field(description="D365 module this requirement belongs to")
    priority: MoSCoW = Field(description="MoSCoW priority classification")
    country: str | None = Field(default=None, description="Country-specific requirement")
    intent: IntentType = Field(description="FUNCTIONAL or NFR")
    completeness_score: float = Field(ge=0, le=100)
    source_ref: str = Field(description="Source document + location (e.g. 'brd.xlsx:row_42')")
    atom_hash: str = Field(description="SHA256 of normalized text for dedup/cache")
    needs_review: bool = Field(default=False)
    status: AtomStatus = Field(default=AtomStatus.ACTIVE)
```

**`ClassificationResult`**:
```python
class ClassificationResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    
    atom_id: UUID
    verdict: Verdict                          # FIT | PARTIAL_FIT | GAP
    confidence: float = Field(ge=0.0, le=1.0)
    matched_capability: str | None = None
    gap_description: str | None = None
    config_needed: str | None = None
    rationale: str = Field(min_length=20, description="Human-readable explanation")
    caveats: list[str] = Field(default_factory=list)
    route_taken: RouteDecision               # FAST_TRACK | LLM | SOFT_GAP
    llm_model: str | None = None
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    needs_review: bool = Field(default=False)
    sanity_flags: list[str] = Field(default_factory=list)
    classified_at: datetime = Field(default_factory=datetime.utcnow)
    
    @field_validator("gap_description")
    def gap_needs_description(cls, v, values):
        if values.data.get("verdict") == Verdict.GAP and not v:
            raise ValueError("GAP verdict requires gap_description")
        return v
```

---

### `core/config/` — All Configuration

#### `settings.py` — Environment-Driven Settings
```python
from pydantic_settings import BaseSettings

class DynafitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    
    # LLM
    CLASSIFICATION_MODEL: str = "claude-3-5-sonnet-20241022"
    INGESTION_MODEL: str = "claude-3-haiku-20240307"
    LLM_MAX_RETRIES: int = 3
    MAX_LLM_COST_USD_PER_RUN: float = 5.00
    
    # Infrastructure
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    POSTGRES_URL: str
    REDIS_URL: str = "redis://localhost:6379"
    
    # Pipeline
    BATCH_SIZE: int = 50
    KB_VERSION: str = "v1.0.0"
    
    # Anthropic API key (NEVER log this)
    ANTHROPIC_API_KEY: str
    LANGCHAIN_API_KEY: str | None = None
    
settings = DynafitSettings()  # Singleton — import this everywhere
```

#### `thresholds.py` — Confidence Thresholds
```python
# These are the CANONICAL thresholds. Never hardcode these values in agent code.
# Always import from here: from core.config.thresholds import THRESHOLDS

THRESHOLDS = {
    "fast_track_fit": 0.85,
    "llm_routing_upper": 0.85,
    "llm_routing_lower": 0.60,
    "soft_gap": 0.40,
    "human_review_sanity_gap": 0.80,   # score > this but verdict=GAP → review
    "human_review_sanity_fit": 0.35,   # score < this but verdict=FIT → review
    "confidence_divergence": 0.40,     # |llm_conf - score| > this → review
}
```

#### `module_config/*.yaml` — Per-Module D365 Config
Each file configures module-specific behavior. Example `ap.yaml`:
```yaml
module: AP
display_name: Accounts Payable
threshold_adjustments:
  fast_track_fit: 0.82     # Slightly lower for AP (well-documented module)
  soft_gap: 0.38

d365_localization_gaps:
  IN:  # India-specific gaps
    - TDS withholding (standard D365 has basic TDS; advanced requires ISV)
  DE:  # Germany-specific
    - DATEV integration (always GAP)

canonical_terms:
  "invoice matching": "three-way matching"
  "payment run": "vendor payment proposal"
  "GR/IR": "product receipt accrual"
```

---

### `core/prompts/` — All LLM Prompt Templates

#### Rules for prompt templates:
1. **All prompts are Jinja2 templates** (`.j2` extension)
2. **System prompts** define the agent role and output format spec
3. **User prompts** inject the requirement-specific data
4. **Output format is always specified** in the system prompt with an exact XML schema
5. **Delimiters** around user-provided content: `<requirement>...</requirement>`, `<capability>...</capability>`
6. **Chain-of-thought instruction** is in the system prompt: "Think step by step. First assess whether a matching capability exists. Then assess coverage. Then determine the verdict."

#### `classification_system.j2` skeleton:
```jinja2
You are a Microsoft Dynamics 365 F&O fitment analyst with deep knowledge of D365 standard capabilities across all modules.

Your task: Classify a business requirement as FIT, PARTIAL_FIT, or GAP against D365 F&O standard capabilities.

Definitions:
- FIT: D365 standard functionality fully satisfies the requirement with minimal or no configuration
- PARTIAL_FIT: D365 partially satisfies the requirement but requires configuration, parameter setup, or minor extension
- GAP: D365 does not satisfy the requirement; custom development (X++ extension) is required

Think step by step:
1. Does a matching D365 feature exist among the candidates?
2. Does it fully cover the requirement or only partially?
3. What is the gap between what D365 offers and what the requirement asks?
4. Does historical evidence support or contradict this classification?

Output your answer ONLY in this XML format, nothing else:
<classification>
  <verdict>FIT|PARTIAL_FIT|GAP</verdict>
  <confidence>0.0-1.0</confidence>
  <matched_capability>capability name or empty</matched_capability>
  <gap_description>empty if FIT, description if GAP/PARTIAL</gap_description>
  <config_needed>empty if FIT/GAP, config steps if PARTIAL</config_needed>
  <rationale>2-4 sentences explaining your decision</rationale>
  <caveats>any important caveats, or empty</caveats>
</classification>

{% if module_specific_notes %}
Module-specific notes for {{ module }}:
{{ module_specific_notes }}
{% endif %}
```

---

## TESTING REQUIREMENTS FOR CORE/

`core/` should have the highest test coverage in the project (target: 95%+).

1. **Schema tests** (`tests/unit/core/test_schemas_*.py`):
   - Test all Pydantic validators with valid and invalid inputs
   - Test frozen models raise `ValidationError` on modification attempt
   - Test `field_validator` business rules (e.g., GAP needs description)

2. **Config tests** (`tests/unit/core/test_config.py`):
   - Test settings load from `.env.test`
   - Test thresholds are consistent (fast_track > llm_lower > soft_gap)
   - Test all module YAML files parse without errors

3. **State tests** (`tests/unit/core/test_state.py`):
   - Test partial state updates merge correctly
   - Test `pipeline_errors` append behavior

4. **Prompt tests** (`tests/unit/core/test_prompts.py`):
   - Render all templates with fixture context
   - Assert required fields present in rendered output
   - Assert no raw Python expressions in output (Jinja2 escaping)