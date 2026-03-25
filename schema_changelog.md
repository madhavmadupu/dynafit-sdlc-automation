# Schema Changelog

All changes to inter-agent data schemas (`core/schemas/`) must be recorded here.
Format: `## vX.Y — YYYY-MM-DD — Author`

---

## v1.0 — Initial Schema Definition

### RequirementAtom
- Initial definition with all fields as documented in `core/schemas/requirement_atom.py`
- Key fields: id, text, module, priority, country, intent, completeness_score, source_ref, atom_hash

### RetrievalContext
- Initial definition
- Key fields: atom, top_capabilities, ms_learn_refs, prior_fitments, confidence_signals

### MatchResult
- Initial definition  
- Key fields: atom_id, candidates, composite_score, confidence_band, route_decision

### ClassificationResult
- Initial definition
- Key fields: atom_id, verdict, confidence, matched_capability, gap_description, config_needed, rationale, caveats, route_taken

### ValidatedFitmentBatch
- Initial definition
- Key fields: run_id, results, overrides, conflict_report, audit_trail, output_path

---

## HOW TO ADD A CHANGELOG ENTRY

When modifying any schema:
1. Add an entry below with the format shown above
2. Document: what changed, why it changed, migration notes
3. Bump `KB_VERSION` in settings if the change affects how KB data is stored
4. Update all fixture files in `tests/fixtures/` that reference the changed schema
5. Search codebase for usages and update all call sites

Example entry format:
```
## v1.1 — 2024-XX-XX — [Author]

### ClassificationResult — BREAKING
- Added field: `processing_ms: int` (default=0 for backward compat)
- Reason: Need latency tracking per atom for performance monitoring
- Migration: All existing ClassificationResult objects will deserialize with processing_ms=0
- Fixtures updated: tests/fixtures/golden_fitments.json, tests/fixtures/mock_retrieval_contexts.json
```