# DYNAFIT — Agent Architecture Reference

This document describes the 5 backend agents that the UI must represent.
Each phase has a specific set of **states**, **inputs**, **outputs**, and **UI requirements**.

---

## Phase 1 — Ingestion Agent

### What it does
Receives raw business requirement documents and transforms them into structured, machine-readable "requirement atoms".

### Input Sources
- Excel sheets (.xlsx / .xls)
- Word FRDs (.docx / .doc)
- Workshop transcripts (.txt)
- User stories
- Emails

### Internal Steps
1. **Document Parser** — Format detector (MIME + heuristic), table extractor, prose splitter, header map
2. **Requirement Extractor (LLM)** — Atomizer (1 need = 1 record), intent classifier (Functional vs NFR), module tagger (AP, AR, GL, SCM…)
3. **Normalizer** — Deduplicator (fuzzy match merge), term aligner (synonym → canonical), priority enricher (MoSCoW tagging)
4. **Validator** — Schema validator, ambiguity detector (vague → flag), completeness score (0–100 per req)

### Output
`RequirementAtom[]` — structured requirement atoms ready for Phase 2.

### UI States to Handle
- `idle` — show file upload drop zone + accepted formats
- `uploading` — per-file upload progress bars
- `processing` — animated pipeline steps (parser → extractor → normalizer → validator)
- `completed` — stats: total atoms, modules, ambiguous count, duplicates
- `warning` — completed but with flagged ambiguous requirements
- `error` — failed parse, show error + retry button

### Key Stats to Display
- Total requirement atoms extracted
- Number of modules detected (AP, AR, GL, etc.)
- Ambiguous requirements flagged
- Duplicate requirements found
- Completeness score distribution

---

## Phase 2 — Knowledge Retrieval Agent (RAG)

### What it does
For each normalized requirement atom, performs retrieval-augmented search across 3 knowledge sources to find the most relevant D365 F&O capabilities.

### 3 Knowledge Sources (parallel retrieval)
1. **D365 Capability KB** — Qdrant vector store (HNSW) + BM25 keyword matching → top-20 capabilities
2. **MS Learn Corpus** — Module documentation index → top-10 doc chunks
3. **Historical Fitments** — pgvector, prior wave decisions → matching prior decisions

### Internal Steps
1. **Query Builder** — Atom → dense embedding + sparse tokens + SQL filter
2. **Parallel Retrieval** — Hit all 3 sources simultaneously
3. **RRF Fusion** — Reciprocal rank fusion → unified top-20
4. **Cross-Encoder Rerank** — ms-marco-MiniLM → top-5
5. **Context Assembly** — Merge capabilities + docs + history → RetrievalContext

### Output
`RetrievalContext[]` — top-5 capabilities + MS Learn refs + prior fitments + confidence signals per atom.

### UI States to Handle
- `idle` — show 3 knowledge source cards, locked/waiting
- `processing` — animated retrieval from each source with live counters
- `completed` — stats: capabilities retrieved, MS Learn refs, historical matches, avg top-K
- `error` — KB connection failure, show which source failed

### Key Stats to Display
- Total capabilities retrieved (atoms × avg 5)
- MS Learn reference chunks
- Historical fitment matches found
- Average retrieval confidence

---

## Phase 3 — Semantic Matching Agent

### What it does
Takes each requirement + its retrieved D365 capabilities and computes a semantic match score — determining whether the D365 feature actually satisfies the business intent.

### Confidence Thresholds (critical routing logic)
- **Score > 0.85 + historical precedent** → `FAST_TRACK` to FIT
- **Score 0.60–0.85** → `LLM_REASON` (needs Phase 4 reasoning)
- **Score < 0.60** → `LIKELY_GAP`

### Internal Steps
1. **Embedding Match (cosine similarity)** — Pairwise cosine (req ↔ each top-5 cap), entity extraction (spaCy D365 NER), overlap ratio
2. **Confidence Scorer (threshold engine)** — Signal aggregation (4 inputs normalize), weighted composite (module-specific YAML), threshold classify (HIGH / MED / LOW)
3. **Candidate Ranker (top-K D365 features)** — Multi-factor rank, dedup + subsume, historical boost

### Output
`MatchResult[]` — composite score + confidence band + route decision per atom.

### UI States to Handle
- `idle` — show threshold configuration (0.85 / 0.60 boundaries), locked
- `analyzing` — live score computation, updating distribution chart
- `completed` — distribution chart (FIT / PARTIAL / GAP buckets), routing breakdown
- `error` — embedding service failure

### Key Stats to Display
- Fast-track count (score > 0.85)
- Needs LLM reasoning count (0.60–0.85)
- Likely GAP count (< 0.60)
- Average composite confidence score
- Score distribution histogram

---

## Phase 4 — Classification Agent (LLM Reasoning)

### What it does
The **core decision-making agent**. Receives requirement + capabilities + scores + historical precedent, then reasons through a structured chain-of-thought prompt to classify and generate rationale.

### Classification Output
| Class | Meaning | D365 Action |
|---|---|---|
| `FIT` | Standard D365 covers it | No dev needed |
| `PARTIAL_FIT` | D365 partially covers it | Configuration needed |
| `GAP` | D365 doesn't cover it | Custom X++ dev needed |

### Chain-of-Thought Reasoning Steps
1. Does a matching D365 feature exist?
2. Does it fully cover the requirement or only partially?
3. What is the gap between what D365 offers and what the requirement asks?
4. Does historical evidence support or contradict this classification?

### Output Schema (JSON per requirement)
```json
{
  "requirementId": "req-0001",
  "classification": "PARTIAL_FIT",
  "confidence": 0.78,
  "rationale": "D365 AP module supports three-way matching natively, but the custom tolerance thresholds requested require parameter configuration beyond default setup.",
  "d365Feature": "AP > Vendor invoices > Invoice matching",
  "d365Module": "AP",
  "configNotes": "Configure matching policy in AP parameters.",
  "gapDescription": null,
  "caveats": ["Tolerance percentages must be set per vendor group"]
}
```

### UI States to Handle
- `idle` — show chain-of-thought reasoning steps, locked
- `processing` — batch progress (batch 1/5, batch 2/5…), running LLM count
- `completed` — full results table with FIT/PARTIAL/GAP breakdown, searchable, filterable
- `error` — LLM timeout or parse failure, show which batch failed

### Key Stats to Display
- FIT count + percentage
- PARTIAL FIT count + percentage
- GAP count + percentage
- Average confidence score
- Low-confidence items flagged for human review

### Results Table Columns
- Req ID
- Requirement text (truncated)
- Module (AP, AR, GL…)
- Priority (MUST/SHOULD/COULD)
- Classification badge (FIT / PARTIAL FIT / GAP)
- Confidence % (colored bar)
- D365 Feature mapped
- Rationale (expandable)

---

## Phase 5 — Validation & Output Agent

### What it does
Takes all classified requirements, runs consistency checks, flags conflicts, enables human consultant review with override capability, and generates the final fitment matrix.

### Internal Steps
1. **Consistency Check** — Dependency graph (NetworkX DiGraph), country overrides (YAML rule engine), confidence filter (threshold flagging)
2. **Human Review (LangGraph interrupt)** — Review queue, override capture (reason + new verdict), feedback writer (→ PostgreSQL history)
3. **Report Generator** — Excel builder (openpyxl styled), audit trail (provenance sheet), metrics emitter (Prometheus counters)

### Output
- `fitment_matrix.xlsx` — final fitment matrix
- Feeds into **FDD FOR FITS** (Module 2) and **FDD FOR GAPS** (Module 3)

### Human-in-the-Loop
A functional consultant can:
- Review each AI classification
- Override the verdict (FIT → GAP, etc.) with a reason
- The override reason feeds back into historical fitments for future waves

### UI States to Handle
- `idle` — show consistency check pipeline, locked
- `processing` — running conflict detection, country override application
- `reviewing` — human review queue, override modal
- `completed` — final matrix preview, export button, full audit trail
- `error` — conflict resolution failure

### Key Stats to Display
- Total verified fitments
- Human overrides made
- Conflicts resolved
- Countries with overrides
- Export ready status

### Override Flow
1. Consultant clicks a row in the results table
2. Override modal opens with current classification + rationale
3. Consultant selects new verdict (FIT / PARTIAL_FIT / GAP)
4. Enters a reason (required)
5. Confirms — row updates, reason stored in audit trail

---

## Cross-Cutting UI Requirements

### Phase Status States (all phases)
Every phase must handle ALL of these states gracefully:

```typescript
type PhaseStatus =
  | "idle"          // Not yet started — show preview/description
  | "pending"       // Queued, waiting for previous phase
  | "uploading"     // File transfer in progress (Phase 1 only)
  | "processing"    // Agent is actively working
  | "analyzing"     // Deep computation (Phase 3 specific)
  | "completed"     // Successfully finished
  | "warning"       // Finished with non-blocking issues
  | "error"         // Failed — show error + retry
  | "skipped"       // Bypassed (future feature)
```

### Error Handling Requirements
- Every error must show: error message, which step failed, retry button
- Network errors: "Connection lost — check your backend server"
- Timeout errors: "Processing timeout — the agent took too long"
- Validation errors: show specific field/requirement that caused failure
- Partial errors: some requirements failed, rest succeeded — show breakdown

### Loading States
- Never show blank content — always show skeleton loaders or spinners
- Progress bars must animate smoothly (CSS transition, not jumpy)
- Show estimated time remaining when possible
- Show current step label ("Normalizing language..." / "Running RRF fusion...")

### Navigation Rules
- Users can freely navigate BACK to completed phases
- Users CANNOT skip ahead to a phase whose prerequisite hasn't completed
- The stepper at the top always shows all 5 phases with status
- Clicking a completed phase chip navigates to that phase's results