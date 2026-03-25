# agents/validation/ — AGENT.md
## Phase 5: Validation & Output Agent — Deep Dive

---

## MISSION

Take all `ClassificationResult` objects from Phase 4, run cross-requirement consistency checks, present to a human consultant for review/override, and generate the final `fitment_matrix.xlsx` with full audit trail.

**This is the last phase. Its output is the product.**

**Input**: `List[ClassificationResult]` — all verdicts from Phase 4
**Output**: `fitment_matrix.xlsx` + `ValidatedFitmentBatch`

---

## CONSISTENCY CHECKER (`consistency_checker.py`)

Uses NetworkX `DiGraph` to detect cross-requirement conflicts before presenting to human.

**Conflict types detected:**

1. **Capability contradiction**: Req A is FIT using Capability X; Req B is GAP claiming Capability X doesn't exist for the same module.

2. **Country inconsistency**: Req A (country=DE) is FIT; Req B (identical text, country=DE) is GAP. Should be same verdict.

3. **Low confidence cluster**: > 40% of requirements in same module have `confidence < 0.5`. Signals KB may be missing this module's capabilities.

4. **Orphan PARTIAL_FIT**: PARTIAL_FIT requirement with `config_needed` that references a capability not in the KB. Possible hallucination.

**Output**: `ConflictReport` with list of conflicts, severity (WARNING / ERROR), and suggested resolution.

**Conflict handling**: All conflicts are flagged for human review. `ERROR` conflicts must be resolved before report generation. `WARNING` conflicts can be acknowledged and overridden.

---

## HUMAN REVIEW (`human_review.py`)

**LangGraph `interrupt()` is called HERE** — this is the human-in-the-loop gate.

```python
from langgraph.types import interrupt

async def run(state: RequirementState) -> dict:
    # Step 1: Run consistency check
    conflict_report = await run_consistency_check(state["classification_results"])
    
    # Step 2: Build review queue
    review_items = build_review_queue(
        results=state["classification_results"],
        conflict_report=conflict_report,
        state=state,
    )
    
    # Step 3: INTERRUPT — pause graph, hand control to human
    # The review UI reads from state["human_review_required"]
    # When consultant submits decisions via PATCH /runs/{id}/review,
    # LangGraph resumes from here with updated state
    if review_items:
        interrupt({"review_items": review_items, "conflict_report": conflict_report.model_dump()})
    
    # Step 4: After resume, apply overrides
    updated_results = apply_overrides(state["classification_results"], state["consultant_decisions"])
    
    return {"final_results": updated_results}
```

**Review queue priority order:**
1. All `ConflictReport.ERROR` items
2. All items with `needs_review=True` (sanity flags from Phase 4)
3. All `PARTIAL_FIT` items with `confidence < 0.70`
4. All `GAP` items with `confidence < 0.65`
5. Random sample of 10% of FIT items (quality check)

---

## OVERRIDE HANDLER (`override_handler.py`)

```python
async def apply_overrides(
    results: List[ClassificationResult],
    decisions: List[ConsultantDecision],
) -> List[ClassificationResult]:
    """
    Apply consultant decisions to classification results.
    
    Rules:
    - If decision.verdict == result.verdict: no change, just mark as consultant-confirmed
    - If decision.verdict != result.verdict: override, require non-empty reason
    - Write ALL decisions (confirm or override) to historical_fitments via pgvector_client
    - Emit metric dynafit_human_overrides_total for overrides
    """
```

**Feedback writer**: Every decision is written to `historical_fitments` so future pipeline runs benefit from this consultant's judgment. This is how DYNAFIT learns.

---

## REPORT GENERATOR (`report_generator.py`)

**Output**: `fitment_matrix_{run_id}.xlsx`

**Sheet specifications:**

### Sheet 1: Fitment Matrix
Columns: `Req_ID | Requirement_Text | Module | Priority | Country | Verdict | Confidence | Matched_Capability | Rationale | Review_Status | Consultant_Override`

Color coding (applied via `openpyxl` named styles):
- FIT rows: `#C6EFCE` (light green) header + data cells
- PARTIAL FIT rows: `#FFEB9C` (amber)
- GAP rows: `#FFC7CE` (light red)
- Overridden rows: bold font + italic text

### Sheet 2: GAP Summary
Only GAP items. Columns: `Req_ID | Requirement_Text | Module | Gap_Description | Estimated_Dev_Effort | Priority`
Note: `Estimated_Dev_Effort` is initially blank — filled manually by dev team.

### Sheet 3: PARTIAL FIT Config Guide
Only PARTIAL FIT items. Columns: `Req_ID | Requirement_Text | Module | Matched_Capability | Configuration_Steps | License_Requirement`

### Sheet 4: Audit Trail
Every decision with full provenance. Columns: `Req_ID | Phase | Action | Actor | Timestamp | Old_Value | New_Value | Reason`

### Sheet 5: Run Metrics
Summary statistics: total requirements, FIT/PARTIAL/GAP counts and percentages, avg confidence, override count, override rate, LLM cost, processing time.

**File naming**: `fitment_matrix_{run_id[:8]}.xlsx` — short UUID prefix for readability.

---

## TESTING REQUIREMENTS

1. **Unit tests**:
   - `test_consistency_checker_capability_contradiction` — verify detection of FIT+GAP on same capability
   - `test_consistency_checker_country_inconsistency` — verify detection of same req, different country verdicts
   - `test_review_queue_priority_ordering` — assert ERROR conflicts appear before sanity flags
   - `test_override_requires_reason_when_changing_verdict` — assert ValidationError without reason
   - `test_report_generator_sheets_present` — assert all 5 sheets in output
   - `test_report_fit_rows_are_green` — assert correct cell colors
   - `test_feedback_writer_called_for_all_decisions` — assert every decision reaches pgvector

2. **Integration test** (`tests/integration/test_validation_agent.py`):
   - Full Phase 5 run with mock human decisions
   - Assert output Excel file exists and has correct structure
   - Assert `ValidatedFitmentBatch` schema validates

---

## DOCS TO MAINTAIN

- `docs/agents/validation.md` — consistency check rules, review queue logic, output format
- `docs/runbooks/human_review.md` — guide for consultants using the review interface