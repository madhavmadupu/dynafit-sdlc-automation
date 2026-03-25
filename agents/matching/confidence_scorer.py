"""
agents/matching/confidence_scorer.py
Composite confidence scoring and Phase 3 → Phase 4 routing decision.
Loads module-specific weights from YAML; falls back to global defaults.
"""
from __future__ import annotations

from pathlib import Path

import structlog
import yaml

from core.config.thresholds import THRESHOLDS
from core.schemas.enums import ConfidenceBand, D365Module, RouteDecision
from core.schemas.retrieval_context import HistoricalFitmentMatch

log = structlog.get_logger()

# Default signal weights (overridable per module via YAML)
DEFAULT_WEIGHTS = {
    "cosine": 0.50,
    "overlap": 0.30,
    "history": 0.20,
}

# Module config cache
_module_configs: dict[str, dict] = {}


def _load_module_thresholds(module: str) -> dict[str, float]:
    """Load threshold adjustments from module YAML config."""
    if module not in _module_configs:
        config_dir = Path(__file__).parents[2] / "core" / "config" / "module_config"
        yaml_path = config_dir / f"{module.lower()}.yaml"
        if yaml_path.exists():
            with open(yaml_path) as f:
                _module_configs[module] = yaml.safe_load(f) or {}
        else:
            _module_configs[module] = {}
    return _module_configs[module].get("threshold_adjustments", {})


def _load_module_weights(module: str) -> dict[str, float]:
    """Load signal weights from module YAML config."""
    if module not in _module_configs:
        _load_module_thresholds(module)  # This populates the cache
    return _module_configs.get(module, {}).get("signal_weights", DEFAULT_WEIGHTS)


def compute_historical_weight(
    prior_fitments: list[HistoricalFitmentMatch],
) -> float:
    """
    Compute the historical weight signal from prior fitment decisions.

    Returns:
    - 1.0 if exact atom_hash match found
    - best_similarity × 0.8 if similar (not exact) history found
    - 0.0 if no history
    """
    if not prior_fitments:
        return 0.0

    # Check for exact match first
    for fitment in prior_fitments:
        if fitment.is_exact_match:
            return 1.0

    # Use best similarity × 0.8 for fuzzy matches
    best_sim = max(f.similarity_to_current for f in prior_fitments)
    return best_sim * 0.8


def compute_composite_score(
    *,
    max_cosine: float,
    max_overlap: float,
    historical_weight: float,
    module: str,
) -> float:
    """
    Compute weighted composite confidence score.

    Formula (default weights):
        composite = 0.50 × max_cosine + 0.30 × max_overlap + 0.20 × historical_weight

    Module YAML can override weights (must sum to 1.0).

    Args:
        max_cosine: Max cosine similarity score across top candidates
        max_overlap: Max entity overlap score
        historical_weight: Historical precedent weight (0.0-1.0)
        module: D365 module code for weight lookup

    Returns:
        Composite score clamped to [0.0, 1.0]
    """
    weights = _load_module_weights(module)
    cosine_w = weights.get("cosine", DEFAULT_WEIGHTS["cosine"])
    overlap_w = weights.get("overlap", DEFAULT_WEIGHTS["overlap"])
    history_w = weights.get("history", DEFAULT_WEIGHTS["history"])

    composite = (
        cosine_w * max_cosine
        + overlap_w * max_overlap
        + history_w * historical_weight
    )
    return max(0.0, min(1.0, composite))


def assign_confidence_band(composite: float) -> ConfidenceBand:
    """Assign confidence band (HIGH/MED/LOW) based on composite score."""
    if composite >= THRESHOLDS["confidence_high_lower"]:
        return ConfidenceBand.HIGH
    elif composite >= THRESHOLDS["confidence_med_lower"]:
        return ConfidenceBand.MED
    else:
        return ConfidenceBand.LOW


def decide_route(
    *,
    composite_score: float,
    has_exact_history: bool,
    has_any_candidates: bool,
    has_any_history: bool,
    module: str,
) -> RouteDecision:
    """
    Determine Phase 3 → Phase 4 routing decision.

    Rules:
    - FAST_TRACK: composite ≥ fast_track_fit threshold AND exact history match
    - SOFT_GAP: composite < soft_gap threshold AND no candidates AND no history
    - LLM: everything else

    Module YAML can override fast_track_fit threshold.

    Args:
        composite_score: Weighted composite score [0.0, 1.0]
        has_exact_history: True if atom_hash matched exactly in history
        has_any_candidates: True if any D365 capabilities were retrieved
        has_any_history: True if any historical fitment exists
        module: D365 module code for threshold lookup

    Returns:
        RouteDecision enum value
    """
    # Get module-specific thresholds
    module_thresholds = _load_module_thresholds(module)
    fast_track_threshold = module_thresholds.get(
        "fast_track_fit", THRESHOLDS["fast_track_fit"]
    )
    soft_gap_threshold = module_thresholds.get("soft_gap", THRESHOLDS["soft_gap"])

    # FAST_TRACK: high confidence + exact historical match
    if composite_score >= fast_track_threshold and has_exact_history:
        return RouteDecision.FAST_TRACK

    # SOFT_GAP: very low confidence, no candidates, no history
    if composite_score < soft_gap_threshold and not has_any_candidates and not has_any_history:
        return RouteDecision.SOFT_GAP

    # Default: full LLM chain-of-thought
    return RouteDecision.LLM
