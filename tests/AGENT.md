# tests/ — AGENT.md
## Testing Strategy, Rules & Patterns

---

## TESTING PHILOSOPHY

DYNAFIT is an AI-powered system where bugs can propagate silently (a misclassification doesn't crash the app — it produces a wrong Excel row). This makes testing **critical infrastructure**, not an afterthought.

**Testing priorities (highest to lowest impact):**
1. **Schema contracts** — if a schema breaks, the entire pipeline breaks
2. **Classification accuracy** — the core product value
3. **Agent routing logic** — wrong routing = wrong classification path
4. **Infrastructure error handling** — bad error handling = silent failures
5. **Output format** — wrong Excel = rejected deliverable

---

## COVERAGE REQUIREMENTS

| Layer | Minimum Coverage |
|-------|-----------------|
| `core/schemas/` | 95% |
| `core/config/` | 90% |
| `core/prompts/` | 85% |
| `core/state/` | 90% |
| `agents/` | 85% |
| `infrastructure/` | 80% |
| Overall | 85% |

Coverage is enforced in CI via `pytest --cov --cov-fail-under=85`.

**Coverage is not the goal — meaningful tests are.** A 100% coverage test that only asserts `result is not None` is worthless. Every test must assert specific behavior.

---

## TEST CATEGORIES

### Unit Tests (`tests/unit/`)
**What**: Test a single function or class in isolation. All external dependencies mocked.
**When**: For every new function with logic (not trivial getters/setters).
**Speed**: Must complete in < 100ms per test. No I/O, no LLM calls, no DB calls.

```python
# ✅ Good unit test
def test_rrf_score_formula():
    """RRF score with rank=1, k=60 should be 1/61."""
    score = rrf_score(rank=1, k=60)
    assert abs(score - (1/61)) < 1e-9

# ✅ Good unit test with mocking
def test_confidence_scorer_high_confidence_routes_fast_track(mocker):
    mocker.patch("core.config.thresholds.THRESHOLDS", {"fast_track_fit": 0.85})
    result = assign_confidence_band(composite_score=0.90, has_history=True)
    assert result.route_decision == RouteDecision.FAST_TRACK

# ❌ Bad unit test
def test_agent_runs():  # Too broad, doesn't test specific behavior
    result = run_ingestion_agent(state)
    assert result is not None
```

### Integration Tests (`tests/integration/`)
**What**: Test a complete agent phase in isolation, with fixture data and mocked external services (Qdrant, LLM, Postgres).
**When**: After implementing a new agent phase or significant agent change.
**Speed**: < 5 seconds per test. No live service calls.

```python
# Pattern for integration tests
@pytest.fixture
def sample_atoms():
    with open("tests/fixtures/sample_requirement_atoms.json") as f:
        return [RequirementAtom(**a) for a in json.load(f)]

@pytest.mark.asyncio
async def test_retrieval_agent_returns_context_for_all_atoms(
    sample_atoms, mock_qdrant_client, mock_pgvector_client, mock_redis
):
    state = build_test_state(atoms=sample_atoms)
    result = await retrieval_agent.run(state)
    
    assert "retrieval_contexts" in result
    assert len(result["retrieval_contexts"]) == len(sample_atoms)
    for ctx in result["retrieval_contexts"]:
        assert RetrievalContext.model_validate(ctx)  # Validates schema
        assert len(ctx.top_capabilities) > 0
```

### End-to-End Tests (`tests/e2e/`)
**What**: Full pipeline run from raw document to fitment matrix.
**When**: Before any release. Run nightly in CI.
**Speed**: < 60 seconds (uses small fixture with 10-20 requirements).

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_pipeline_produces_fitment_matrix(tmp_path):
    """Run the full DYNAFIT pipeline on a 15-requirement fixture BRD."""
    output_path = tmp_path / "fitment_matrix.xlsx"
    
    result = await run_pipeline(
        input_file="tests/fixtures/sample_brd.xlsx",
        output_path=output_path,
        skip_human_review=True,  # E2E only — never in production
    )
    
    assert output_path.exists()
    wb = openpyxl.load_workbook(output_path)
    
    assert "Fitment Matrix" in wb.sheetnames
    assert "GAP Summary" in wb.sheetnames
    assert "Audit Trail" in wb.sheetnames
    
    matrix_sheet = wb["Fitment Matrix"]
    rows = list(matrix_sheet.iter_rows(min_row=2, values_only=True))
    assert len(rows) >= 10  # At least 10 of 15 requirements processed
    
    verdicts = [row[3] for row in rows if row[3]]  # Verdict column
    assert all(v in ["FIT", "PARTIAL FIT", "GAP"] for v in verdicts)
```

### Eval Tests (`tests/e2e/test_classification_eval.py`)
**What**: Accuracy evaluation against golden ground truth.
**When**: Before any prompt change, model change, or threshold change. Run in CI on PR.
**Golden set**: `tests/fixtures/golden_fitments.json` — 50 requirements with verified correct verdicts.

```python
@pytest.mark.eval
@pytest.mark.asyncio
async def test_classification_accuracy_meets_baseline():
    """
    Run Phase 4 against golden set and assert accuracy meets baseline.
    Fails the PR if accuracy regresses.
    """
    with open("tests/fixtures/golden_fitments.json") as f:
        golden = json.load(f)
    
    with open("tests/fixtures/eval_baseline.json") as f:
        baseline = json.load(f)
    
    results = await classify_golden_set(golden)
    metrics = compute_metrics(results, golden)
    
    assert metrics["accuracy"] >= 0.85, f"Accuracy {metrics['accuracy']:.2%} < 85%"
    assert metrics["fit_precision"] >= 0.88, f"FIT precision {metrics['fit_precision']:.2%} < 88%"
    assert metrics["gap_recall"] >= 0.90, f"GAP recall {metrics['gap_recall']:.2%} < 90%"
    
    # Regression guard: must not drop > 2% from baseline
    assert metrics["accuracy"] >= baseline["accuracy"] - 0.02, (
        f"Accuracy regressed: {metrics['accuracy']:.2%} vs baseline {baseline['accuracy']:.2%}"
    )
```

---

## FIXTURES

All test fixtures live in `tests/fixtures/`. Never commit real client data.

| File | Description | Format |
|------|-------------|--------|
| `sample_brd.xlsx` | 15 synthetic AP/AR requirements | Excel |
| `sample_requirement_atoms.json` | Pre-parsed atoms from sample_brd | JSON |
| `golden_fitments.json` | 50 requirements with verified verdicts | JSON |
| `eval_baseline.json` | Latest accepted eval metrics | JSON |
| `mock_d365_capabilities.json` | 30 synthetic D365 capabilities | JSON |
| `mock_llm_responses.json` | Canned LLM responses for unit tests | JSON |
| `mock_retrieval_contexts.json` | Pre-built contexts for Phase 3/4 tests | JSON |

**Golden set rules:**
- Every entry has: `requirement_text`, `module`, `expected_verdict`, `rationale`, `verified_by`, `verified_date`
- Verified by a real D365 functional consultant (not LLM-generated ground truth)
- New entries must be added with human verification, not automated
- Never modify existing entries without consultant sign-off

**Mock LLM response rules (`mock_llm_responses.json`):**
```json
{
  "classification_fit_example": "<classification><verdict>FIT</verdict>...",
  "classification_gap_example": "<classification><verdict>GAP</verdict>...",
  "classification_malformed": "Sorry I cannot classify this requirement",
  "classification_json_instead_of_xml": "{\"verdict\": \"FIT\", ...}"
}
```
Cover happy path AND all failure modes.

---

## MOCKING STRATEGY

**Infrastructure mocks** (use `pytest-mock`):
```python
@pytest.fixture
def mock_qdrant_client(mocker):
    mock = mocker.MagicMock(spec=DynafitQdrantClient)
    mock.search_capabilities = AsyncMock(
        return_value=load_fixture("mock_d365_capabilities.json")[:5]
    )
    mock.health_check = AsyncMock(return_value=True)
    return mock

@pytest.fixture  
def mock_llm(mocker):
    mock = mocker.patch("infrastructure.llm.client.llm_call")
    mock.return_value = LLMResponse(
        content=load_fixture("mock_llm_responses.json")["classification_fit_example"],
        model="claude-3-5-sonnet-20241022",
        prompt_tokens=800,
        completion_tokens=200,
        total_cost_usd=0.0063,
        latency_ms=1200,
    )
    return mock
```

**Never mock `core/` modules.** They are pure Python with no side effects — test them directly.

---

## CI/CD INTEGRATION

### Test commands:
```bash
# Unit tests only (fast — run before every commit)
pytest tests/unit/ -v --cov=. --cov-report=term-missing

# Integration tests (medium — run on PR)
pytest tests/integration/ -v -m "not slow"

# Full test suite including E2E (slow — run on merge to main)
pytest tests/ -v --cov=. --cov-fail-under=85

# Eval only (run when changing prompts or thresholds)
pytest tests/e2e/test_classification_eval.py -v -m eval

# E2E only  
pytest tests/e2e/ -v -m e2e
```

### Pytest markers (defined in `pyproject.toml`):
```toml
[tool.pytest.ini_options]
markers = [
    "unit: fast unit tests",
    "integration: integration tests with mocked services",
    "e2e: full end-to-end pipeline tests",
    "eval: accuracy evaluation tests",
    "slow: tests taking > 10 seconds",
]
```

---

## TEST MAINTENANCE RULES

1. **When you add a function, add its test in the same PR.** No deferred tests.
2. **When you fix a bug, add a regression test first.** Then fix the bug.
3. **When you change a prompt, run eval before merging.** Update baseline if improved.
4. **When you change a schema, update all fixture files.** Stale fixtures = broken tests.
5. **Flaky tests are P1 bugs.** A test that passes 90% of the time is worse than no test.
6. **Test names must describe behavior**, not implementation: `test_gap_verdict_requires_gap_description` not `test_validator_v2`.