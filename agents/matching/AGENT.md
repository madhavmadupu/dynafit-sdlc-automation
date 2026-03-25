# agents/matching/ — AGENT.md
## Phase 3: Semantic Matching Agent — Deep Dive

---

## MISSION

For each `RetrievalContext`, compute how well the requirement is covered by the retrieved D365 capabilities. Produce a `MatchResult` with a composite confidence score, confidence band, and routing decision that determines whether Phase 4 needs to run LLM reasoning or can fast-track/short-circuit.

**Input**: `List[RetrievalContext]` — one per atom, each with top-5 candidates
**Output**: `List[MatchResult]` — scored, ranked, with route decision

---

## SCORING PIPELINE

Three signals feed the composite score. All three are computed, then weighted and combined:

### Signal 1 — Cosine Similarity (`embedding_match.py`)
```python
# Pairwise cosine between requirement embedding and each candidate embedding
# These vectors were already computed in Phase 2 — REUSE them, do not re-embed
similarity_scores = cosine_similarity(
    requirement_vector.reshape(1, -1),
    np.array([cap.embedding for cap in candidates])
)  # Shape: (1, n_candidates) → take [0]
```

**Entity overlap ratio** (spaCy D365 NER):
```python
req_entities = set(spacy_ner.extract_d365_entities(atom.text))
for cap in candidates:
    cap_entities = set(spacy_ner.extract_d365_entities(cap.description))
    overlap = len(req_entities & cap_entities) / max(len(req_entities), 1)
    # overlap ratio: 0.0 (no shared entities) to 1.0 (all entities match)
```

Output per candidate: `SimilarityVector(cosine=float, overlap=float, entity_pairs=list)`

### Signal 2 — Confidence Scorer (`confidence_scorer.py`)
Aggregates the 3 signals (cosine, overlap, historical weight) into a composite:

```python
# Module-specific weights from core/config/module_config/{module}.yaml
weights = module_config.signal_weights  # e.g., {"cosine": 0.5, "overlap": 0.3, "history": 0.2}

composite = (
    weights["cosine"] * max_cosine_score +
    weights["overlap"] * max_overlap_score +
    weights["history"] * historical_weight
)

# historical_weight: 1.0 if exact hash match exists, 0.5 if similar match, 0.0 if no history
```

**Band assignment:**
```python
if composite >= THRESHOLDS["fast_track_fit"] and has_exact_history:
    band = ConfidenceBand.HIGH
    route = RouteDecision.FAST_TRACK
elif composite >= THRESHOLDS["llm_routing_lower"]:
    band = ConfidenceBand.MED
    route = RouteDecision.LLM
elif composite < THRESHOLDS["soft_gap"] and not has_history:
    band = ConfidenceBand.LOW
    route = RouteDecision.SOFT_GAP
else:
    band = ConfidenceBand.LOW
    route = RouteDecision.LLM  # Low confidence still gets LLM — don't assume GAP
```

### Signal 3 — Candidate Ranker (`candidate_ranker.py`)
Re-orders the top-5 candidates for optimal LLM context assembly:

1. **Multi-factor rank**: `score = (0.6 * rerank_score) + (0.3 * composite_signal) + (0.1 * specificity)`
   - `specificity` = inverse of capability description length (shorter = more specific)
2. **Dedup + subsume**: Drop candidates with `cosine_similarity > 0.95` to each other (keep higher scorer)
3. **Historical boost**: Bump rank of any candidate that matches a prior POSITIVE fitment decision

Output: Top-5 `ScoredCandidate` objects, ordered best-first.

---

## TESTING REQUIREMENTS

1. **Unit tests**:
   - `test_cosine_similarity_range` — assert all scores in [0, 1]
   - `test_entity_overlap_empty_entities` — assert 0.0 when no entities found
   - `test_confidence_scorer_weight_sum` — assert module weights sum to 1.0
   - `test_fast_track_requires_history` — assert FAST_TRACK only with `has_history=True`
   - `test_candidate_ranker_dedup` — assert candidates > 0.95 similar are deduplicated
   - `test_composite_score_uses_module_config` — assert different modules use different weights

2. **Integration test** (`tests/integration/test_matching_agent.py`):
   - Run Phase 3 on fixture `RetrievalContext` objects
   - Assert all atoms get a route decision
   - Assert no composite score outside [0.0, 1.0]
   - Assert FAST_TRACK atoms have `composite_score >= 0.85`

---

## DOCS TO MAINTAIN

- `docs/agents/matching.md` — scoring formula, weight rationale, threshold tuning guide