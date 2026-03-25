# infrastructure/ — AGENT.md
## Infrastructure Layer: External Service Clients & Adapters

---

## PURPOSE OF THIS LAYER

`infrastructure/` contains all code that talks to external services: vector databases, LLM APIs, relational databases, caches. Each module is a **thin, tested adapter** — it translates between the domain types in `core/schemas/` and the external service's API.

**Core principle: Infrastructure modules are wrappers, not logic.**
- ✅ infrastructure: "call Qdrant with these params and return `List[D365Capability]`"
- ❌ infrastructure: any business logic, thresholds, routing decisions
- ❌ infrastructure: Pydantic model definitions (those live in `core/schemas/`)

**Every infrastructure client must:**
1. Be independently testable with mocks (no live service calls in unit tests)
2. Implement a health check method used at application startup
3. Use connection pooling (never create a new connection per call)
4. Log all errors with structlog (never swallow)
5. Expose async interface (all methods are `async def`)

---

## SUB-MODULES

### `infrastructure/vector_db/`

#### `embedder.py` — Embedding Generation
```python
class BgeEmbedder:
    """
    Wraps BAAI/bge-large-en-v1.5 for generating 1024-dim embeddings.
    
    IMPORTANT: Always use the D365-specific instruction prefix for requirements.
    Omitting the prefix degrades retrieval quality significantly.
    """
    
    INSTRUCTION_PREFIX = "Represent this D365 business requirement for retrieval: "
    MODEL_NAME = "BAAI/bge-large-en-v1.5"
    EMBEDDING_DIM = 1024
    
    async def embed_requirement(self, text: str) -> List[float]:
        """Embed a single requirement text with instruction prefix."""
        
    async def embed_requirements_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch embed. Max 256 items per batch. Uses thread pool executor."""
        
    async def embed_capability(self, text: str) -> List[float]:
        """Embed a capability description. No instruction prefix needed."""
    
    async def health_check(self) -> bool:
        """Verify model loaded and can produce 1024-dim output."""
```

**Model loading**: Load once at startup into module-level singleton. Do not reload per request.

#### `qdrant_client.py` — Qdrant Vector Store Operations
```python
class DynafitQdrantClient:
    """
    Manages all Qdrant operations for DYNAFIT.
    
    Collections managed:
    - d365_capabilities: D365 F&O capability KB
    - ms_learn_docs: Microsoft Learn documentation chunks
    
    Never create or drop collections outside of setup scripts.
    """
    
    async def search_capabilities(
        self, 
        vector: List[float], 
        module_filter: str,
        limit: int = 20,
    ) -> List[D365CapabilityMatch]:
        """Vector search in d365_capabilities collection."""
    
    async def keyword_search_capabilities(
        self,
        tokens: List[str],
        module_filter: str, 
        limit: int = 20,
    ) -> List[D365CapabilityMatch]:
        """BM25 keyword search — runs via Qdrant's sparse vector support."""
    
    async def search_ms_learn(
        self,
        vector: List[float],
        limit: int = 10,
    ) -> List[DocChunkMatch]:
        """Semantic search in ms_learn_docs collection."""
    
    async def upsert_capability(self, capability: D365Capability) -> None:
        """Upsert a single capability. Used by knowledge base ingestion scripts."""
    
    async def health_check(self) -> bool:
        """Ping Qdrant and verify both collections exist and are non-empty."""
```

**Collection config** (set during `scripts/setup_vector_db.py`):
```python
d365_capabilities_config = VectorParams(
    size=1024,
    distance=Distance.COSINE,
    on_disk=True,           # For large KBs
    hnsw_config=HnswConfigDiff(m=16, ef_construct=200),
)
```

#### `pgvector_client.py` — Historical Fitments Store
```python
class HistoricalFitmentsClient:
    """
    PostgreSQL + pgvector store for historical fitment decisions.
    
    Table: historical_fitments
    Columns: id, atom_hash, module, country, text, verdict, rationale, 
             confidence, wave_id, overridden_by, embedding, created_at
    
    Used for:
    1. Exact lookup by atom_hash + module (O(1))
    2. Semantic similarity search via pgvector <=> operator
    3. Writing new decisions (feedback loop from Phase 5)
    """
    
    async def find_by_hash(self, atom_hash: str, module: str) -> List[HistoricalFitment]:
        """Exact match on atom_hash + module. Fastest path."""
    
    async def find_similar(
        self, 
        embedding: List[float], 
        module: str, 
        limit: int = 5,
    ) -> List[HistoricalFitment]:
        """Semantic similarity search."""
    
    async def write_fitment(self, result: ClassificationResult, atom: RequirementAtom, wave_id: str) -> None:
        """Write a new fitment decision. Called from Phase 5 feedback writer."""
    
    async def health_check(self) -> bool:
        """Verify pg connection and pgvector extension installed."""
```

---

### `infrastructure/llm/`

#### `client.py` — The ONLY Way to Call LLMs
```python
async def llm_call(
    messages: List[dict],
    model: str,
    temperature: float = 0.1,
    max_tokens: int = 1000,
    trace_name: str | None = None,
    run_id: str | None = None,
) -> LLMResponse:
    """
    Central LLM call function. ALL LLM calls in DYNAFIT go through here.
    
    Features:
    - Automatic retry with exponential backoff (3 attempts)
    - Token counting (pre-call estimate + actual post-call)
    - Cost tracking (writes to cost_tracker.py)
    - LangSmith tracing (if LANGCHAIN_API_KEY is set)
    - Structured error handling with LLMError subtypes
    
    NEVER bypass this function to call Anthropic SDK directly.
    """
    
@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float
    latency_ms: float
```

**Retry policy**: `tenacity` with `stop_after_attempt(3)`, `wait_exponential(min=2, max=30)`. Retry on: `anthropic.RateLimitError`, `anthropic.APIConnectionError`, `anthropic.InternalServerError`. Do NOT retry on: `anthropic.AuthenticationError`, `anthropic.BadRequestError`.

**LangSmith tracing**: Wrap call in `langsmith.trace()` context manager if `settings.LANGCHAIN_API_KEY` is set. Gracefully degrade if LangSmith is unavailable — never let tracing failure break the LLM call.

#### `cost_tracker.py` — Token & Cost Accounting
```python
class CostTracker:
    """
    Tracks LLM token usage and USD cost across a run.
    
    Cost table (update when model pricing changes):
    - claude-3-5-sonnet: $3/1M input, $15/1M output
    - claude-3-haiku: $0.25/1M input, $1.25/1M output
    
    Methods:
    - record_call(model, prompt_tokens, completion_tokens) → None
    - get_total_cost(run_id) → float
    - check_limit(run_id) → bool  # returns False if limit exceeded
    - get_run_summary(run_id) → CostSummary
    """
```

---

### `infrastructure/storage/`

#### `redis_client.py` — Cache & Task Queue
```python
class DynafitRedisClient:
    """
    Redis operations for DYNAFIT.
    
    Uses:
    1. RetrievalContext caching (TTL: 24h)
    2. Celery task queue broker
    3. Rate limit counters
    
    Key naming convention:
    - Cache: "retrieval:{atom_hash}:{kb_version}"
    - Rate limit: "ratelimit:{user_id}:{window}"
    
    Never use Redis for persistent data — PostgreSQL only.
    """
    
    async def get_retrieval_context(self, cache_key: str) -> RetrievalContext | None:
    async def set_retrieval_context(self, cache_key: str, context: RetrievalContext, ttl: int = 86400) -> None:
    async def health_check(self) -> bool:
```

#### `postgres_client.py` — Audit Trail & Run History
```python
class DynafitPostgresClient:
    """
    PostgreSQL client for audit trail, run history, and historical fitments.
    
    Tables:
    - dynafit_runs: run metadata, status, timestamps
    - audit_trail: every classification decision with timestamps
    - consultant_overrides: override history with reasons
    - historical_fitments: (also accessed by pgvector_client)
    
    Uses asyncpg connection pool. Pool size: min=5, max=20.
    All writes are transactional.
    """
    
    async def create_run(self, run_id: str, source_files: List[str]) -> None:
    async def update_run_status(self, run_id: str, status: RunStatus) -> None:
    async def write_audit_entry(self, entry: AuditEntry) -> None:
    async def write_override(self, override: ConsultantOverride) -> None:
    async def get_run_summary(self, run_id: str) -> RunSummary:
    async def health_check(self) -> bool:
```

---

## STARTUP HEALTH CHECKS

On application startup (`api/main.py` lifespan), run health checks for all infrastructure:

```python
async def startup_checks():
    checks = {
        "qdrant": qdrant_client.health_check(),
        "pgvector": pgvector_client.health_check(),
        "redis": redis_client.health_check(),
        "embedder": embedder.health_check(),
        "postgres": postgres_client.health_check(),
    }
    results = await asyncio.gather(*checks.values(), return_exceptions=True)
    
    for name, result in zip(checks.keys(), results):
        if isinstance(result, Exception) or result is False:
            log.critical(f"Infrastructure health check failed: {name}", error=str(result))
            raise StartupError(f"Cannot start: {name} is unavailable")
    
    log.info("All infrastructure health checks passed")
```

**Fail fast on startup.** A misconfigured infrastructure is caught immediately, not mid-pipeline.

---

## TESTING REQUIREMENTS

All infrastructure tests use mocked service clients. No live service calls in CI.

```python
# Pattern for infrastructure unit tests
@pytest.fixture
def mock_qdrant(mocker):
    return mocker.patch("infrastructure.vector_db.qdrant_client.QdrantClient")

def test_search_capabilities_applies_module_filter(mock_qdrant):
    client = DynafitQdrantClient()
    # ... assert mock called with correct filter params
```

**Required tests:**
- `test_embedder_instruction_prefix` — assert prefix is prepended for requirements
- `test_embedder_batch_max_256` — assert batches larger than 256 are split
- `test_qdrant_search_module_filter` — assert module filter always applied
- `test_llm_client_retry_on_rate_limit` — assert 3 retries with backoff
- `test_llm_client_no_retry_on_auth_error` — assert immediate failure
- `test_cost_tracker_limit_check` — assert returns False when over limit
- `test_redis_cache_miss_returns_none` — assert None on cache miss, not error
- `test_postgres_write_audit_entry_transactional` — assert rollback on failure