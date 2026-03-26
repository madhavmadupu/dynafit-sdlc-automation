"""
agents/classification/sanity_checker.py
Post-classification sanity rules. Flags results for human review.
Applied after LLM classification — never changes the verdict, only sets needs_review.
"""

from __future__ import annotations

import structlog

from core.config.thresholds import THRESHOLDS
from core.schemas.classification_result import ClassificationResult
from core.schemas.enums import RouteDecision, Verdict
from core.schemas.match_result import MatchResult

log = structlog.get_logger()


def check_result(
    result: ClassificationResult,
    match_result: MatchResult,
) -> ClassificationResult:
    """
    Apply sanity rules to a ClassificationResult.

    Rules:
    1. High composite score + GAP verdict → flag (unexpected divergence)
    2. Low composite score + FIT verdict → flag (model likely hallucinating)
    3. SOFT_GAP auto-classification → always flag for review
    4. Large LLM confidence vs composite score divergence → flag

    The result is returned as a copy with updated needs_review and sanity_flags.
    Original verdict is NEVER changed by this function.

    Args:
        result: ClassificationResult from LLM or auto-route
        match_result: Phase 3 scoring result for comparison

    Returns:
        Updated ClassificationResult (frozen copy via model_copy).
    """
    flags: list[str] = list(result.sanity_flags)  # Start with any existing flags
    needs_review = result.needs_review

    composite = match_result.composite_score

    # Rule 1: High confidence retrieval but classified as GAP
    if composite >= THRESHOLDS["sanity_high_score_gap"] and result.verdict == Verdict.GAP:
        flags.append("high_composite_score_with_gap_verdict")
        needs_review = True
        log.info(
            "sanity.flag_high_score_gap",
            atom_id=str(result.atom_id),
            composite=composite,
            verdict=result.verdict.value,
        )

    # Rule 2: Very low retrieval confidence but FIT verdict
    if composite < THRESHOLDS["sanity_low_score_fit"] and result.verdict == Verdict.FIT:
        flags.append("low_composite_score_with_fit_verdict")
        needs_review = True
        log.info(
            "sanity.flag_low_score_fit",
            atom_id=str(result.atom_id),
            composite=composite,
            verdict=result.verdict.value,
        )

    # Rule 3: Large confidence divergence (LLM self-reported vs composite)
    if result.route_taken == RouteDecision.LLM:
        divergence = abs(result.confidence - composite)
        if divergence > THRESHOLDS["sanity_confidence_divergence"]:
            flags.append(f"confidence_divergence_{divergence:.2f}")
            needs_review = True
            log.info(
                "sanity.flag_confidence_divergence",
                atom_id=str(result.atom_id),
                llm_confidence=result.confidence,
                composite=composite,
                divergence=divergence,
            )

    # Rule 4: PARTIAL_FIT with no config_needed (incomplete response)
    if result.verdict == Verdict.PARTIAL_FIT and not result.config_needed:
        flags.append("partial_fit_missing_config_steps")
        needs_review = True
        log.info(
            "sanity.flag_partial_fit_no_config",
            atom_id=str(result.atom_id),
        )

    if flags and flags != list(result.sanity_flags):
        return result.model_copy(update={"needs_review": needs_review, "sanity_flags": flags})

    return result
