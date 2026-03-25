# knowledge_base/ — AGENT.md
## Knowledge Base: D365 Capabilities, MS Learn & Historical Fitments

---

## PURPOSE

The knowledge base is the **static truth** that DYNAFIT retrieves against. It is maintained separately from the pipeline and must be versioned, reproducible, and auditable. The KB is ingested once (or on update) and serves all pipeline runs.

**KB Version** is tracked in `settings.KB_VERSION`. Bumping this version invalidates all Redis retrieval caches, forcing fresh retrieval on next run.

---

## THREE KNOWLEDGE SOURCES

### Source 1: D365 Capability KB (`d365_capabilities/`)

**What it contains**: A curated catalog of D365 F&O standard capabilities, organized by module. Each entry is a discrete, assessable capability.

**Capability schema**:
```python
class D365Capability(BaseModel):
    capability_id: str                # e.g. "AP-001", "GL-042"
    name: str                         # Short name: "Three-way matching"
    description: str                  # 2-5 sentences describing what D365 does
    module: D365Module
    sub_module: str | None            # e.g. "Vendor invoicing", "Payment proposals"
    license_requirement: str | None   # e.g. "Finance license required"
    localization_gaps: dict[str, str] # {"IN": "TDS not fully covered", "DE": "DATEV gap"}
    configuration_notes: str | None   # What config is needed for this cap to work
    ms_learn_url: str | None          # Reference documentation link
    version_introduced: str | None    # e.g. "10.0.20"
    tags: List[str]                   # Searchable keywords
    embedding: List[float] | None     # Set by ingest script, not manually
```

**Maintenance rules:**
- Capabilities are managed as YAML files in `knowledge_base/d365_capabilities/catalog/`
- One YAML file per D365 module (e.g., `ap_capabilities.yaml`, `gl_capabilities.yaml`)
- New capabilities require PR review from a D365 SME
- Deprecating a capability: mark `deprecated: true` in YAML, never delete (historical fitments may reference it)
- After any YAML update: run `scripts/ingest_knowledge_base.py --source d365_capabilities` and bump `KB_VERSION`

**Capability writing guidelines** (for SMEs maintaining the YAML):
- `description` must be in plain English, 2-5 sentences
- Describe what D365 DOES, not what the requirement asks
- Include key terms users might search for (e.g., both "three-way match" and "PO matching")
- `localization_gaps` is critical — incorrect gaps lead to wrong classifications
- `configuration_notes` = what a consultant needs to set up for this cap to work (helps PARTIAL_FIT rationale)

**Ingestion script** (`ingest_capabilities.py`):
```python
# Reads YAML catalog → validates Pydantic → embeds descriptions → upserts to Qdrant
# Idempotent: uses capability_id as upsert key
# Reports: N capabilities ingested, N updated, N deprecated
```

### Source 2: MS Learn Corpus (`ms_learn/`)

**What it contains**: Chunked documentation from Microsoft Learn (learn.microsoft.com/en-us/dynamics365/finance/). Provides detailed technical context for the LLM.

**Chunking strategy** (`chunker.py`):
- Chunk size: 400 tokens (not characters) using tiktoken
- Overlap: 50 tokens between chunks
- Chunking unit: Section (split at H2/H3 headings)
- Preserve: source URL, page title, section heading in each chunk's metadata

**Ingestion process** (`ingest_ms_learn.py`):
1. Crawl MS Learn sitemap for D365 Finance module pages
2. Fetch HTML → extract main content (strip nav, footer, ads)
3. Chunk with overlap → embed each chunk
4. Upsert to Qdrant `ms_learn_docs` collection with metadata

**Re-ingestion trigger**: When Microsoft releases a new D365 version. Check learn.microsoft.com changelog quarterly.

**Rate limiting**: Respect MS Learn robots.txt. Max 1 request/second. Add `User-Agent: DYNAFIT-KB-Ingestion/1.0`.

### Source 3: Historical Fitments (`historical_fitments/`)

**What it contains**: Every fitment decision ever made using DYNAFIT (or manually imported from prior projects). This is the system's memory and gets richer with every wave.

**Schema** (`history_schema.py`):
```python
class HistoricalFitment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    atom_hash: str                    # SHA256 of normalized requirement text
    original_text: str                # For human reference
    module: D365Module
    country: str | None
    verdict: Verdict                  # FIT | PARTIAL_FIT | GAP
    confidence: float
    rationale: str
    matched_capability: str | None
    wave_id: str                      # Which project/wave this came from
    overridden_by_consultant: bool    # True if human changed the AI decision
    override_reason: str | None
    created_at: datetime
    embedding: List[float]            # For semantic similarity search
```

**Priming the history** (new deployments): Import historical data from prior manual fitment exercises:
```python
# scripts/ingest_knowledge_base.py --source historical --input prior_fitments.xlsx
# Maps Excel columns to HistoricalFitment schema
# Embeds requirement texts
# Bulk inserts to pgvector table
```

**Feedback loop** (automatic, via Phase 5):
- Every approved ClassificationResult → written to `historical_fitments` via `override_handler.py`
- Consultant overrides → written with `overridden_by_consultant=True` + reason
- These become training signal for future runs

---

## KB VERSIONING

```
KB Version format: v{MAJOR}.{MINOR}.{PATCH}
- MAJOR: Full re-ingestion (new D365 release, structural change to capability schema)
- MINOR: New capabilities added or significant updates
- PATCH: Typo fixes, minor description improvements

Current version tracked in: core/config/settings.py → KB_VERSION
```

**When to bump:**
- Any change to d365_capabilities YAML → MINOR bump minimum
- Any change to Capability Pydantic schema → MAJOR bump
- Re-crawl of MS Learn → MINOR bump
- Typo fix in a description → PATCH bump

**Effect of bumping**: All Redis cache entries are invalidated (cache key includes KB version). Next pipeline run fetches fresh from vector DB.

---

## DOCS TO MAINTAIN

- `docs/architecture/overview.md` — KB architecture section
- Run `scripts/ingest_knowledge_base.py --dry-run` after any YAML change to verify
- Update `KB_VERSION` in settings after any ingestion