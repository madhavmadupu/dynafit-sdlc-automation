"""
core/config/thresholds.py
Single source of truth for all confidence thresholds and routing cut-offs.
NEVER hardcode these values in agent logic — always import from here.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Routing thresholds (Phase 3 → Phase 4)
# ─────────────────────────────────────────────────────────────────────────────
THRESHOLDS: dict[str, float] = {
    # FAST_TRACK: composite >= this AND exact history match → skip LLM, auto-FIT
    "fast_track_fit": 0.85,
    # SOFT_GAP: composite < this AND no history AND no candidates → skip LLM, auto-GAP
    "soft_gap": 0.40,
    # Confidence band boundaries
    "confidence_high_lower": 0.70,  # composite >= 0.70 → HIGH band
    "confidence_med_lower": 0.40,  # composite 0.40-0.69 → MED band
    # composite < 0.40 → LOW band
    # ─────────────────────────────────────────────────────────────────────────
    # Sanity check thresholds (Phase 4 post-classification)
    # ─────────────────────────────────────────────────────────────────────────
    # Flag for human review if composite score high but LLM said GAP
    "sanity_high_score_gap": 0.80,
    # Flag for human review if composite score low but LLM said FIT
    "sanity_low_score_fit": 0.35,
    # Flag if |llm_confidence - composite_score| > this → divergence flag
    "sanity_confidence_divergence": 0.40,
    # ─────────────────────────────────────────────────────────────────────────
    # Ingestion quality thresholds (Phase 1)
    # ─────────────────────────────────────────────────────────────────────────
    # Hard reject atoms below this completeness score
    "completeness_reject": 20.0,
    # Soft flag (needs_review) for atoms in this range
    "completeness_flag": 40.0,
    # ─────────────────────────────────────────────────────────────────────────
    # Historical fitment thresholds (Phase 2)
    # ─────────────────────────────────────────────────────────────────────────
    # Minimum pgvector similarity to count as historical precedent
    "history_similarity_min": 0.75,
}

# ─────────────────────────────────────────────────────────────────────────────
# Auto-approval rule
# Phase 5: auto-approve (skip interrupt) only when BOTH conditions met
# ─────────────────────────────────────────────────────────────────────────────
AUTO_APPROVE_MIN_CONFIDENCE: float = 0.85
AUTO_APPROVE_REQUIRES_HISTORY: bool = True

# ─────────────────────────────────────────────────────────────────────────────
# RRF constant (ADR-001 locked — do not change without ADR + eval)
# ─────────────────────────────────────────────────────────────────────────────
RRF_K: int = 60

# ─────────────────────────────────────────────────────────────────────────────
# Deduplication thresholds
# ─────────────────────────────────────────────────────────────────────────────
# RapidFuzz token_sort_ratio above this = duplicate
DEDUP_SIMILARITY_THRESHOLD: float = 90.0

# Candidate dedup: drop candidate if >85% word overlap with higher-ranked
CANDIDATE_DEDUP_THRESHOLD: float = 0.85
