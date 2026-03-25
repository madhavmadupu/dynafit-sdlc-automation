"""
agents/classification/agent.py
Phase 4 — Classification Agent LangGraph node.
Classifies each atom as FIT | PARTIAL_FIT | GAP using route-aware processing.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from agents.classification.llm_classifier import (
    classify_with_llm,
    make_fast_track_result,
    make_soft_gap_result,
)
from agents.classification.preflight import run_preflight_cost_check
from agents.classification.sanity_checker import check_result
from core.schemas.classification_result import ClassificationResult
from core.schemas.enums import RouteDecision
from core.schemas.match_result import MatchResult
from core.schemas.requirement_atom import RequirementAtom
from core.schemas.retrieval_context import RetrievalContext

log = structlog.get_logger()
PHASE = "classification"


async def run(state: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 4 LangGraph node: Classification Agent.

    Reads: state["atoms"], state["match_results"], state["retrieval_contexts"],
           state["llm_cost_usd"], state["run_id"]
    Writes: state["classification_results"], state["classification_errors"],
            state["llm_cost_usd"], state["human_review_required"]

    Routing:
    - FAST_TRACK → auto-FIT (no LLM, zero cost)
    - SOFT_GAP → auto-GAP (no LLM, zero cost)
    - LLM → full chain-of-thought classification
    """
    run_id: str = state["run_id"]
    atoms: list[RequirementAtom] = state.get("atoms", [])
    match_results: list[MatchResult] = state.get("match_results", [])
    contexts: list[RetrievalContext] = state.get("retrieval_contexts", [])
    current_spend = float(state.get("llm_cost_usd", 0.0))

    log.info(f"{PHASE}.start", run_id=run_id, atom_count=len(atoms))

    # Build lookup maps
    match_by_atom: dict[str, MatchResult] = {str(m.atom_id): m for m in match_results}
    context_by_atom: dict[str, RetrievalContext] = {str(c.atom_id): c for c in contexts}
    atom_by_id: dict[str, RequirementAtom] = {str(a.id): a for a in atoms}

    # ── Cost pre-flight check ─────────────────────────────────────────────────
    await run_preflight_cost_check(
        match_results=match_results,
        current_spend_usd=current_spend,
        run_id=run_id,
    )

    # ── Classify each atom ────────────────────────────────────────────────────
    # Process in parallel batches of settings.BATCH_SIZE
    from core.config.settings import settings
    batch_size = settings.BATCH_SIZE

    results: list[ClassificationResult] = []
    errors: list[dict] = []
    total_new_cost = 0.0
    human_review_required: list[str] = list(state.get("human_review_required", []))

    for i in range(0, len(atoms), batch_size):
        batch = atoms[i : i + batch_size]
        batch_tasks = [
            _classify_single(
                atom=atom,
                match_result=match_by_atom.get(str(atom.id)),
                context=context_by_atom.get(str(atom.id)),
                run_id=run_id,
            )
            for atom in batch
        ]
        outcomes = await asyncio.gather(*batch_tasks, return_exceptions=True)

        for atom, outcome in zip(batch, outcomes):
            if isinstance(outcome, Exception):
                log.error(
                    f"{PHASE}.atom_failed",
                    run_id=run_id,
                    atom_id=str(atom.id),
                    error=str(outcome),
                )
                errors.append({
                    "phase": PHASE,
                    "atom_id": str(atom.id),
                    "error": str(outcome),
                })
            else:
                classified_result, atom_cost = outcome
                results.append(classified_result)
                total_new_cost += atom_cost

                if classified_result.needs_review:
                    human_review_required.append(str(classified_result.atom_id))

    # Deduplicate human review list
    human_review_required = list(dict.fromkeys(human_review_required))

    log.info(
        f"{PHASE}.complete",
        run_id=run_id,
        classified=len(results),
        errors=len(errors),
        new_cost_usd=round(total_new_cost, 4),
        total_cost_usd=round(current_spend + total_new_cost, 4),
        human_review_count=len(human_review_required),
    )

    return {
        "classification_results": results,
        "classification_errors": errors,
        "llm_cost_usd": current_spend + total_new_cost,
        "human_review_required": human_review_required,
        "pipeline_errors": state.get("pipeline_errors", []) + errors,
    }


async def _classify_single(
    *,
    atom: RequirementAtom,
    match_result: MatchResult | None,
    context: RetrievalContext | None,
    run_id: str,
) -> tuple[ClassificationResult, float]:
    """
    Classify a single atom, returning (result, cost_incurred).

    Routes:
    - FAST_TRACK → make_fast_track_result (cost=0)
    - SOFT_GAP → make_soft_gap_result (cost=0)
    - LLM → classify_with_llm (cost > 0)
    """
    if match_result is None:
        # No match result — treat as SOFT_GAP
        result = make_soft_gap_result(atom)
        return _sanity_check(result, match_result), 0.0

    route = match_result.route_decision

    if route == RouteDecision.FAST_TRACK:
        result = make_fast_track_result(atom, match_result)
        return _sanity_check(result, match_result), 0.0

    if route == RouteDecision.SOFT_GAP:
        result = make_soft_gap_result(atom)
        return _sanity_check(result, match_result), 0.0

    # LLM route
    result = await classify_with_llm(
        atom=atom,
        match_result=match_result,
        context=context,
        run_id=run_id,
    )
    from infrastructure.llm.client import _calculate_cost
    from core.config.settings import settings
    atom_cost = _calculate_cost(
        model=settings.CLASSIFICATION_MODEL,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
    result_with_sanity = _sanity_check(result, match_result)
    return result_with_sanity, atom_cost


def _sanity_check(
    result: ClassificationResult, match_result: MatchResult | None
) -> ClassificationResult:
    """Apply sanity checker if match_result is available."""
    if match_result is None:
        return result
    return check_result(result, match_result)
