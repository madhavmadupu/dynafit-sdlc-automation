# agents/ingestion/ — AGENT.md
## Phase 1: Ingestion Agent — Deep Dive

---

## MISSION

Transform messy, multi-format business requirement documents into a list of clean, normalized, machine-readable `RequirementAtom` objects that downstream agents can process deterministically.

**Input**: Raw files (Excel, Word, PDF, transcript, email)
**Output**: `List[RequirementAtom]` — structured, deduplicated, tagged, normalized

---

## MODULE RESPONSIBILITIES

### `doc_parser.py` — Format Detection & Extraction
**What it does**: Detects file format and extracts raw text/table content.

```
Input:  file bytes + MIME type
Output: List[RawChunk] — unstructured text blocks with source metadata
```

**Format routing:**
- `.pdf` → Docling (primary) → Unstructured (fallback)
- `.docx` / `.doc` → Docling
- `.xlsx` / `.xls` → openpyxl → each row becomes a `RawChunk`
- `.txt` / `.md` → direct read with paragraph splitting
- Email body (`.eml`) → extract text body, strip signatures

**Docling config** (use these settings, do not override without ADR):
```python
DoclingConfig(
    do_ocr=True,               # Handle scanned PDFs
    ocr_engine="tesseract",
    table_mode="accurate",     # Preserve table structure
    image_resolution=300,
)
```

**openpyxl table extraction rules:**
- Detect header row by checking if row 1 contains keywords: "requirement", "description", "ID", "module", "priority"
- If no header detected, treat all rows as requirement text
- Skip rows where all cells are empty
- Merge multi-line cells (ALT+ENTER newlines) into single text blocks

### `req_extractor.py` — LLM-Based Requirement Atomization
**What it does**: Uses LLM to identify discrete requirements in raw chunks and atomize compound requirements.

```
Input:  List[RawChunk]
Output: List[PartialAtom] — unnormalized, unvalidated atoms
```

**Prompt template**: `core/prompts/ingestion_extract.j2`

**Atomization rules** (enforced in prompt + post-processing):
1. One atom = one atomic business need (independently testable)
2. Compound requirements (contains "AND", "also", numbered sub-items) must be split
3. Ambiguous requirements get `completeness_score < 50` — do not try to guess intent
4. Each atom gets: `text`, `module_hint`, `priority_hint`, `source_ref`

**Batch size**: Process `RawChunk` objects in batches of 20 per LLM call to avoid token limit issues.

### `normalizer.py` — Deduplication & Term Alignment
**What it does**: Removes duplicate atoms and normalizes business terminology to D365 canonical terms.

```
Input:  List[PartialAtom]
Output: List[NormalizedAtom] — deduplicated + term-aligned
```

**Deduplication**: RapidFuzz `token_sort_ratio > 90` = duplicate. Keep the one with higher `completeness_score`. Log all deduplication events.

**Term alignment** (`term_aligner`):
- Source: `knowledge_base/d365_capabilities/canonical_terms.json`
- Strategy: spaCy NER to identify D365 entities, then map to canonical names
- Examples:
  - "three-way matching" / "3-way match" / "PO matching" → "three-way matching (purchase order)"
  - "auto-pay" / "automatic payments" / "payment run" → "automatic vendor payment proposal"
  - "intercompany" / "inter-company" / "IC transactions" → "intercompany accounting"
- Unknown terms: preserve as-is, set `term_alignment_confidence = 0.0`, flag for review

**MoSCoW priority tagging**:
- "must", "mandatory", "required", "critical" → `MUST`
- "should", "expected", "needed" → `SHOULD`
- "nice to have", "optional", "if possible" → `COULD`
- "out of scope", "excluded" → `WONT`
- No priority signal → `SHOULD` (default, never leave null)

### `validator.py` — Quality Gate
**What it does**: Validates each normalized atom against the `RequirementAtom` schema and completeness rules.

```
Input:  List[NormalizedAtom]
Output: List[RequirementAtom] (valid) + List[RejectedAtom] (invalid)
```

**Hard failures** (atom rejected, sent back for re-extraction):
- `text` is empty or < 10 chars
- `module` is not a valid `D365Module` enum value
- `completeness_score` < 20 (unintelligibly vague)

**Soft failures** (atom passes but gets `needs_review=True` flag):
- `completeness_score` between 20-40
- `term_alignment_confidence` < 0.5 for key terms
- `priority` defaulted (no explicit signal in source)

**Retry logic**: Rejected atoms are sent back to `req_extractor.py` with the rejection reason injected into the prompt. Max 2 retries. If still failing after 2 retries: emit with `status=ERROR`.

---

## TESTING REQUIREMENTS

Every function in this module requires:

1. **Unit test** in `tests/unit/agents/test_ingestion_*.py`
   - Test each function with: valid input, empty input, malformed input, edge cases
   - Mock all LLM calls using `tests/fixtures/mock_llm_responses.json`

2. **Integration test** in `tests/integration/test_ingestion_agent.py`
   - Full ingestion run on `tests/fixtures/sample_brd.xlsx`
   - Assert: output count within expected range (±10% of known count)
   - Assert: all atoms pass schema validation
   - Assert: no atom has empty `text` or null `module`
   - Assert: dedup reduces count from known duplicate-heavy fixture

3. **Format tests**: Separate test for each supported format (xlsx, docx, pdf, txt)

---

## DOCS TO MAINTAIN

After any change to this agent, update:
- `docs/agents/ingestion.md` — capability description + examples
- `docs/architecture/data_flow.md` — if RawChunk or PartialAtom structure changes
- `docs/architecture/schema_changelog.md` — if RequirementAtom schema changes