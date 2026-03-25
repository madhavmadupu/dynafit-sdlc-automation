# agents/retrieval/ — AGENT.md
## Phase 2: Knowledge Retrieval Agent (RAG) — Deep Dive

---

## MISSION

For each `RequirementAtom`, retrieve the most semantically relevant D365 capabilities from 3 knowledge sources using hybrid search (dense + sparse), fuse and rerank the results, and assemble a `RetrievalContext` that gives Phase 3 grounded evidence to work with.

**Input**: `List[RequirementAtom]` (265 typical)
**Output**: `List[RetrievalContext]` — one per atom, each with top-5 capabilities + MS Learn refs + prior decisions

---

## RETRIEVAL PIPELINE (MUST NOT BE SHORTCUT)

```
RequirementAtom
      │
      ▼
query_builder.py          → dense embedding + sparse BM25 tokens + SQL module filter
      │
      ▼ asyncio.gather() — ALL 3 in parallel
┌─────────────────────────────────────────────────────────┐
│  D365 Capability KB    │  MS Learn corpus  │  Historical │
│  Qdrant HNSW + BM25    │  Qdrant + docs    │  pgvector   │
│  → top-20 caps         │  → top-10 chunks  │  → prior    │
└─────────────────────────────────────────────────────────┘
      │
      ▼
rrf_fusion.py             → Reciprocal Rank Fusion → unified top-20
      │
      ▼
reranker.py               → ms-marco-MiniLM-L-6-v2 CrossEncoder → top-5
      │
      ▼
context_assembler.py      → merge capabilities + docs + history → RetrievalContext
```

---

## MODULE RESPONSIBILITIES

### `query_builder.py` — Multi-Modal Query Construction
**What it does**: Transforms a `RequirementAtom` into the query formats needed for each retrieval path.

```python
@dataclass
class RetrievalQuery:
    dense_vector: List[float]    # bge-large-en-v1.5 embedding of atom.text
    sparse_tokens: List[str]     # BM25 tokenization (lowercased, no stopwords)
    sql_filter: dict             # {"module": atom.module, "country": atom.country}
    atom_hash: str               # SHA256 of normalized text (for cache key)
```

**Embedding model**: `BAAI/bge-large-en-v1.5` (1024-dim). Always use instruction prefix: `"Represent this D365 business requirement for retrieval: {text}"`.

**BM25 tokenization**: Use `rank_bm25` tokenizer. Remove D365-specific stopwords defined in `core/config/retrieval_config.yaml` (e.g., "system", "the", "user", "must").

**SQL filter**: Always filter by `module`. Optionally filter by `country` if `atom.country is not None`. Never retrieve capabilities from unrelated modules.

### `parallel_retriever.py` — Fan-Out to 3 Sources
**What it does**: Fans out the query to all 3 knowledge sources simultaneously.

**Source 1 — D365 Capability KB** (Qdrant, collection: `d365_capabilities`):
```python
# Always use hybrid search — both vector and BM25
results = await qdrant.search(
    collection_name="d365_capabilities",
    query_vector=query.dense_vector,
    query_filter=Filter(must=[FieldCondition(key="module", match=MatchValue(value=query.sql_filter["module"]))]),
    with_payload=True,
    limit=20,
    search_params=SearchParams(hnsw_ef=128),
)
# Separately run BM25 keyword search and merge before RRF
```

**Source 2 — MS Learn Corpus** (Qdrant, collection: `ms_learn_docs`):
```python
# Semantic search only — BM25 less effective on documentation prose
results = await qdrant.search(
    collection_name="ms_learn_docs",
    query_vector=query.dense_vector,
    limit=10,
)
```

**Source 3 — Historical Fitments** (pgvector, table: `historical_fitments`):
```python
# Try exact hash match first
SELECT * FROM historical_fitments 
WHERE atom_hash = %(hash)s AND module = %(module)s
LIMIT 5;

# Fall back to semantic similarity
SELECT *, embedding <=> %(vec)s AS dist 
FROM historical_fitments 
WHERE module = %(module)s
ORDER BY dist LIMIT 5;
```

**Error handling**: If ANY source fails, log the error and continue with partial results. Do NOT abort the full retrieval. Track `sources_available` in the `RetrievalContext` for downstream diagnostics.

### `rrf_fusion.py` — Reciprocal Rank Fusion
**What it does**: Merges ranked lists from multiple sources into a single unified ranking.

**Algorithm**:
```python
def rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)

def fuse(ranked_lists: List[List[ScoredItem]]) -> List[ScoredItem]:
    scores = defaultdict(float)
    for ranked_list in ranked_lists:
        for rank, item in enumerate(ranked_list, start=1):
            scores[item.id] += rrf_score(rank)
    return sorted(all_items, key=lambda x: scores[x.id], reverse=True)[:20]
```

**k=60** is fixed. Any change to k requires an ADR and eval regression test.

### `reranker.py` — Cross-Encoder Reranking
**What it does**: Takes the top-20 fused results and reranks to top-5 using a cross-encoder (more accurate, pairwise relevance scoring).

**Model**: `cross-encoder/ms-marco-MiniLM-L-6-v2`
**Input format**: `(requirement_text, capability_description)` pairs
**Output**: Top-5 capabilities sorted by cross-encoder score

**Performance note**: Cross-encoder is synchronous and CPU-bound. Run in a thread pool executor:
```python
loop = asyncio.get_event_loop()
scores = await loop.run_in_executor(None, model.predict, pairs)
```

### `context_assembler.py` — Context Assembly
**What it does**: Merges top-5 capabilities + MS Learn refs + historical fitments into a `RetrievalContext`.

**Assembly rules**:
- `top_capabilities`: top-5 from reranker, each with `name`, `description`, `module`, `capability_id`, `rerank_score`
- `ms_learn_refs`: top-3 MS Learn chunks most relevant to the requirement text
- `prior_fitments`: all historical decisions for same/similar atoms (usually 0-3)
- `confidence_signals`: raw scores for diagnostics (`{"max_rerank_score": float, "has_history": bool, "n_sources": int}`)

---

## CACHING STRATEGY

**Cache key**: `f"retrieval:{atom.atom_hash}:{settings.KB_VERSION}"`
**TTL**: 24 hours
**Cache store**: Redis (via `infrastructure/storage/redis_client.py`)
**Cache on write**: Always after successful context assembly
**Cache invalidation**: On KB version bump (bump `KB_VERSION` in settings when KB is re-ingested)

```python
cached = await redis.get(cache_key)
if cached:
    return RetrievalContext.model_validate_json(cached)
# ... do retrieval ...
await redis.setex(cache_key, 86400, context.model_dump_json())
return context
```

---

## TESTING REQUIREMENTS

1. **Unit tests** (`tests/unit/agents/test_retrieval_*.py`):
   - `test_query_builder_dense_vector_shape` — assert embedding is 1024-dim
   - `test_query_builder_module_filter` — assert SQL filter matches atom module
   - `test_rrf_fusion_deduplication` — same item in 2 lists gets merged, not doubled
   - `test_rrf_fusion_score_order` — verify higher-ranked items score higher
   - `test_reranker_returns_top_5` — assert exactly 5 results returned
   - `test_context_assembler_missing_source` — assert partial results if one source fails

2. **Integration test** (`tests/integration/test_retrieval_agent.py`):
   - Use `tests/fixtures/mock_d365_capabilities.json` as Qdrant mock
   - Assert: every atom gets a non-empty `top_capabilities` list
   - Assert: `RetrievalContext` schema validates for every result
   - Assert: Redis cache is populated after first run
   - Assert: Second run with same atoms returns from cache (mock Redis hit)

---

## DOCS TO MAINTAIN

- `docs/agents/retrieval.md` — retrieval strategy, KB structure, cache policy
- `docs/architecture/data_flow.md` — if RetrievalContext schema changes