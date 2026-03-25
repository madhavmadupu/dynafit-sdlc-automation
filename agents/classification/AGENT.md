# agents/classification/ — AGENT.md
## Phase 4: Classification Agent (LLM Reasoning) — Deep Dive

---

## MISSION

This is the core decision-making phase. For each requirement, combine the match scores from Phase 3 with LLM chain-of-thought reasoning to produce a final FIT / PARTIAL FIT / GAP verdict with a human-readable rationale and confidence score.

**Input**: `List[MatchResult]` — ranked candidates with confidence bands + route decisions
**Output**: `List[ClassificationResult]` — one verdict per atom with rationale

---

## ROUTING DECISIONS (from Phase 3)

Phase 3 sets `route_decision` which determines what this agent does:

| Route | Condition | Action |
|-------|-----------|--------|
| `FAST_TRACK` | `composite_score >= 0.85` AND `has_history=True` | Skip LLM. Emit FIT directly. |
| `LLM` | `0.60 <= composite_score < 0.85` | Full LLM chain-of-thought |
| `SOFT_GAP` | `composite_score < 0.40` AND `has_history=False` | Skip LLM. Emit GAP with `confidence=0.6`. |
| `LLM` (override) | Any score, but Phase 3 flags `needs_llm=True` | Always run LLM regardless |

**Important**: Even for `FAST_TRACK`, check `sanity_checker.py` — if the fast-track result looks implausible, downgrade to `LLM` route.

---

## MODULE RESPONSIBILITIES

### `prompt_builder.py` — Jinja2 Prompt Assembly
**What it does**: Builds the system + user prompts from templates, injecting all relevant context.

**Template**: `core/prompts/classification_system.j2` + `core/prompts/classification_user.j2`

**User prompt context** (all fields MUST be populated):
```python
@dataclass
class ClassificationPromptContext:
    requirement_id: str
    requirement_text: str
    module: str
    priority: str
    top_candidates: List[dict]      # [{name, description, score}] — max 5
    composite_score: float
    confidence_band: str            # HIGH / MED / LOW
    has_historical_precedent: bool
    prior_decisions: List[dict]     # [{verdict, rationale, wave}] — max 3
    country: str | None
    module_specific_notes: str      # from module_config YAML
```

**Token budget management**:
```python
MAX_PROMPT_TOKENS = 3500  # Leave room for completion in context window
current_tokens = count_tokens(system_prompt + user_prompt)
if current_tokens > MAX_PROMPT_TOKENS:
    # Truncate: reduce candidate descriptions to 100 chars each
    # Then reduce rationale history
    # Never truncate requirement_text or top candidate names
    raise PromptTooLargeError(f"Prompt is {current_tokens} tokens, max {MAX_PROMPT_TOKENS}")
```

**Never inject raw user content** (from BRD) directly into the system prompt. It always goes in the user prompt inside a clearly delimited block:
```
<requirement>
{requirement_text}
</requirement>
```
This prevents prompt injection from malicious BRD content.

### `llm_classifier.py` — LLM Call + Structured Parse
**What it does**: Makes the LLM call and extracts structured output.

**LLM call via `infrastructure/llm/client.py`**:
```python
response = await llm_call(
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    model=settings.CLASSIFICATION_MODEL,
    temperature=0.1,       # Low temp for consistency
    max_tokens=800,        # Enough for verdict + rationale
    trace_name=f"classify_{atom_id}",
)
```

**Model selection** (from settings):
- Default: `claude-3-5-sonnet-20241022` (best reasoning/cost tradeoff)
- For HIGH confidence fast-track verification: `claude-3-haiku-20240307` (speed)
- Never use model < claude-3-sonnet for classification — quality unacceptable

**Expected output format** (LLM is instructed to emit this):
```xml
<classification>
  <verdict>FIT</verdict>
  <confidence>0.92</confidence>
  <matched_capability>Vendor invoice approval workflow</matched_capability>
  <gap_description></gap_description>
  <config_needed></config_needed>
  <rationale>D365 F&O provides a standard three-way matching process...</rationale>
  <caveats>Requires AP module license</caveats>
</classification>
```

### `response_parser.py` — Structured Output Extraction
**What it does**: Parses LLM output into a `ClassificationResult` Pydantic model.

**Parse strategy** (try in order, stop at first success):
1. **XML parse**: `lxml.etree` parse of `<classification>` block
2. **Regex fallback**: Extract fields with named capture groups
3. **JSON fallback**: Some models may emit JSON despite XML instruction
4. **Re-generation**: Ask LLM to "Please reformat your previous answer as XML" (max 2 retries)
5. **Failure mode**: Return `ClassificationResult(verdict=GAP, confidence=0.0, rationale="Parse failed - requires human review", needs_review=True)`

**Post-parse validation**:
- `verdict` must be one of: `FIT`, `PARTIAL_FIT`, `GAP`
- `confidence` must be float between 0.0 and 1.0
- If `verdict=FIT` but `matched_capability` is empty → set `needs_review=True`
- If `verdict=GAP` but `gap_description` is empty → set `needs_review=True`
- If `verdict=PARTIAL_FIT` but `config_needed` is empty → set `needs_review=True`

### `sanity_checker.py` — Score-vs-Classification Consistency
**What it does**: Catches obvious LLM reasoning errors by comparing the classification against the numeric match score.

**Sanity rules** (all trigger `needs_review=True`, never auto-reject):

| Rule | Condition | Action |
|------|-----------|--------|
| High score / GAP | `composite_score >= 0.80` AND `verdict == GAP` | Flag: "High similarity but classified GAP" |
| Low score / FIT | `composite_score <= 0.35` AND `verdict == FIT` | Flag: "Low similarity but classified FIT" |
| Confidence mismatch | `\|llm_confidence - composite_score\| > 0.4` | Flag: "LLM confidence diverges from match score" |
| No candidate / FIT | `len(candidates) == 0` AND `verdict == FIT` | Hard fail: re-route to `SOFT_GAP` |

**Escalation rule**: If > 30% of requirements in a batch trigger sanity flags, emit a batch-level warning and notify via Prometheus metric `dynafit_sanity_flag_rate`.

---

## COST MANAGEMENT

Before any LLM batch, calculate projected cost:
```python
estimated_tokens = sum(count_tokens(build_prompt(atom)) for atom in llm_routed_atoms)
estimated_cost = (estimated_tokens / 1000) * COST_PER_1K_TOKENS[settings.CLASSIFICATION_MODEL]

if estimated_cost > settings.MAX_LLM_COST_USD_PER_RUN:
    raise CostLimitError(
        f"Projected cost ${estimated_cost:.2f} exceeds limit ${settings.MAX_LLM_COST_USD_PER_RUN:.2f}. "
        f"Reduce batch size or increase limit."
    )
```

Track actual cost per run in `infrastructure/llm/cost_tracker.py` and emit `dynafit_llm_cost_usd_total` metric.

---

## TESTING REQUIREMENTS

1. **Unit tests** (`tests/unit/agents/test_classification_*.py`):
   - `test_prompt_builder_no_injection` — assert `<requirement>` delimiters present
   - `test_prompt_builder_token_budget` — assert truncation kicks in at 3500 tokens
   - `test_response_parser_xml_happy_path` — valid XML → correct ClassificationResult
   - `test_response_parser_xml_fallback_regex` — malformed XML → regex extraction
   - `test_response_parser_total_failure` → verify GAP with needs_review=True
   - `test_sanity_checker_high_score_gap` — verify flag on high-score GAP
   - `test_fast_track_skips_llm` — mock LLM, assert it's never called for FAST_TRACK
   - `test_soft_gap_skips_llm` — same for SOFT_GAP route

2. **Eval test** (`tests/e2e/test_classification_eval.py`):
   - Run against `tests/fixtures/golden_fitments.json` (ground truth)
   - Assert: overall accuracy >= 85%
   - Assert: FIT precision >= 88% (false FITs are expensive in projects)
   - Assert: GAP recall >= 90% (missing a GAP is dangerous)
   - Assert: no regression from previous eval run (stored in `tests/fixtures/eval_baseline.json`)

3. **Integration test** (`tests/integration/test_classification_agent.py`):
   - Use mock LLM returning fixture responses
   - Assert: FAST_TRACK atoms never reach LLM mock
   - Assert: SOFT_GAP atoms never reach LLM mock
   - Assert: All ClassificationResult objects pass Pydantic validation

---

## DOCS TO MAINTAIN

- `docs/agents/classification.md` — prompt strategy, model choice rationale, accuracy metrics
- `docs/architecture/schema_changelog.md` — on ClassificationResult changes
- Update `tests/fixtures/eval_baseline.json` after any intentional accuracy improvement