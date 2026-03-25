# DYNAFIT — Architecture Overview

## System Purpose

DYNAFIT automates D365 F&O requirement fitment analysis. In a typical D365 implementation project, a team of functional consultants manually reviews 200-800 business requirements and classifies each as FIT (standard), PARTIAL FIT (configuration needed), or GAP (custom development). This process takes 2-4 weeks, is inconsistent across consultants, and produces hard-to-audit decisions.

DYNAFIT reduces this to 2-4 hours with auditable, LLM-grounded decisions and a mandatory human review step.

---

## Design Decisions

### Why LangGraph?
LangGraph provides three critical features: (1) **checkpointing** — runs can resume after failure without reprocessing completed phases; (2) **`interrupt()`** — built-in human-in-the-loop that pauses the graph and waits for consultant review; (3) **conditional routing** — different atoms can take different paths (FAST_TRACK vs LLM vs SOFT_GAP) within the same graph run. See `docs/architecture/adr/ADR-001-langgraph.md`.

### Why Hybrid Search (dense + BM25)?
Pure semantic search misses exact matches (e.g., "DATEV integration" is a specific German requirement that BM25 catches better than cosine similarity). Pure BM25 misses semantic equivalents (e.g., "auto-payment" and "vendor payment proposal"). Hybrid with RRF fusion consistently outperforms either alone. Our eval on the golden set showed +8% recall vs pure semantic.

### Why Pydantic v2 for all inter-agent data?
Phase boundaries in an agent system are the highest-risk points for data corruption. Pydantic v2 strict mode + frozen models make it impossible for an agent to accidentally pass malformed data to the next phase. The performance cost (vs plain dicts) is negligible compared to LLM call latency.

### Why PostgreSQL for historical fitments (not just Qdrant)?
Historical fitments need two access patterns: (1) exact hash lookup (`O(1)` in Postgres) and (2) semantic similarity search (pgvector). Storing in both Qdrant and Postgres would create sync issues. pgvector handles both patterns in a single service.

### Why CrossEncoder reranking after RRF fusion?
Bi-encoder embeddings (Phase 2) are fast but imprecise — they independently embed query and documents. CrossEncoder models (Phase 2 reranker) jointly encode (query, document) pairs for much higher relevance accuracy, at the cost of speed. We use CrossEncoder only on the top-20 already-retrieved candidates (not the full KB), making it computationally feasible.

---

## Data Flow Diagram

See `docs/architecture/data_flow.md` for the detailed per-field data lineage.

---

## Schema Changelog

See `docs/architecture/schema_changelog.md` for all schema versions.

---

## Architecture Decision Records

| ADR | Decision | Date |
|-----|----------|------|
| ADR-001 | Use LangGraph as orchestration framework | TBD |
| ADR-002 | Use bge-large-en-v1.5 as embedding model | TBD |
| ADR-003 | Confidence thresholds (0.85 / 0.60 / 0.40) | TBD |
| ADR-004 | PostgreSQL + pgvector for historical fitments | TBD |