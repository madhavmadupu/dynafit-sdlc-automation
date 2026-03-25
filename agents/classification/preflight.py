"""
agents/classification/preflight.py
Cost guard for Phase 4. Must run before processing any atoms through the LLM.
Aborts with an exception if projected cost would exceed MAX_LLM_COST_USD_PER_RUN.
"""
from __future__ import annotations

import structlog

from core.config.settings import settings
from core.schemas.match_result import MatchResult
from core.schemas.enums import RouteDecision
from infrastructure.llm.client import estimate_cost_for_batch

log = structlog.get_logger()


async def run_preflight_cost_check(
    match_results: list[MatchResult],
    current_spend_usd: float,
    run_id: str,
) -> None:
    """
    Estimate and validate LLM cost before beginning classification.

    Only LLM-routed atoms (RouteDecision.LLM) incur actual LLM costs.
    FAST_TRACK and SOFT_GAP routes are free.

    Args:
        match_results: All match results from Phase 3
        current_spend_usd: LLM spend already accumulated in this run (from prior calls)
        run_id: Pipeline run ID for logging

    Raises:
        RuntimeError: If projected total spend would exceed MAX_LLM_COST_USD_PER_RUN
    """
    llm_atoms = [m for m in match_results if m.route_decision == RouteDecision.LLM]
    fast_track_count = sum(1 for m in match_results if m.route_decision == RouteDecision.FAST_TRACK)
    soft_gap_count = sum(1 for m in match_results if m.route_decision == RouteDecision.SOFT_GAP)

    log.info(
        "preflight.routing_summary",
        run_id=run_id,
        total=len(match_results),
        llm_route=len(llm_atoms),
        fast_track=fast_track_count,
        soft_gap=soft_gap_count,
    )

    if not llm_atoms:
        log.info("preflight.all_fast_track_or_soft_gap", run_id=run_id)
        return  # No LLM calls needed

    # Build sample prompts for cost estimation
    # We estimate based on a rough per-atom token count (~800 input tokens avg for classification)
    avg_tokens_per_classification = 800
    estimated_prompt_tokens = avg_tokens_per_classification * len(llm_atoms)
    estimated_completion_tokens = 400 * len(llm_atoms)

    # Use Anthropic pricing for the classification model
    from infrastructure.llm.client import _calculate_cost
    estimated_additional_cost = _calculate_cost(
        model=settings.CLASSIFICATION_MODEL,
        prompt_tokens=estimated_prompt_tokens,
        completion_tokens=estimated_completion_tokens,
    )

    projected_total = current_spend_usd + estimated_additional_cost
    budget = settings.MAX_LLM_COST_USD_PER_RUN

    log.info(
        "preflight.cost_estimate",
        run_id=run_id,
        llm_atoms=len(llm_atoms),
        estimated_additional_usd=round(estimated_additional_cost, 4),
        current_spend_usd=round(current_spend_usd, 4),
        projected_total_usd=round(projected_total, 4),
        budget_usd=budget,
    )

    if projected_total > budget:
        msg = (
            f"COST GUARD TRIGGERED: Projected LLM cost ${projected_total:.2f} "
            f"exceeds budget ${budget:.2f} for run {run_id}. "
            f"LLM atoms: {len(llm_atoms)}, estimated: ${estimated_additional_cost:.4f}. "
            f"Increase MAX_LLM_COST_USD_PER_RUN or reduce batch size."
        )
        log.error(
            "preflight.budget_exceeded",
            run_id=run_id,
            projected_total=projected_total,
            budget=budget,
        )
        raise RuntimeError(msg)

    log.info(
        "preflight.passed",
        run_id=run_id,
        projected_total_usd=round(projected_total, 4),
        budget_remaining_usd=round(budget - projected_total, 4),
    )
