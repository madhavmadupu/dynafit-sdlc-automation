"""
agents/matching/agent.py
Phase 3 — Semantic Matching Agent LangGraph node.
Scores candidates, computes composite confidence, and makes routing decisions.
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import structlog

from agents.matching.confidence_scorer import (
    assign_confidence_band,
    compute_composite_score,
    compute_historical_weight,
    decide_route,
)
from agents.matching.embedding_match import score_capabilities
from core.schemas.enums import ConfidenceBand, RouteDecision, Verdict
from core.schemas.match_result import MatchResult, ScoredCandidate
from core.schemas.requirement_atom import RequirementAtom
from core.schemas.retrieval_context import D365CapabilityMatch, RetrievalContext

log = structlog.get_logger()
PHASE = "matching"


async def run(state: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 3 LangGraph node: Semantic Matching Agent.

    Reads: state["atoms"], state["retrieval_contexts"]
    Writes: state["match_results"], state["matching_errors"]

    All atoms processed in parallel via asyncio.gather().
    """
    run_id: str = state["run_id"]
    atoms: list[RequirementAtom] = state.get("atoms", [])
    contexts: list[RetrievalContext] = state.get("retrieval_contexts", [])

    log.info(f"{PHASE}.start", run_id=run_id, atom_count=len(atoms))

    # Build lookup: atom_id → RetrievalContext
    context_by_atom: dict[str, RetrievalContext] = {
        str(ctx.atom_id): ctx for ctx in contexts
    }

    tasks = [
        _match_single(
            atom=atom,
            context=context_by_atom.get(str(atom.id)),
            run_id=run_id,
        )
        for atom in atoms
    ]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[MatchResult] = []
    errors: list[dict] = []

    for atom, outcome in zip(atoms, outcomes):
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
            results.append(outcome)

    log.info(
        f"{PHASE}.complete",
        run_id=run_id,
        results=len(results),
        errors=len(errors),
        fast_track=sum(1 for r in results if r.route_decision == RouteDecision.FAST_TRACK),
        soft_gap=sum(1 for r in results if r.route_decision == RouteDecision.SOFT_GAP),
        llm=sum(1 for r in results if r.route_decision == RouteDecision.LLM),
    )

    return {
        "match_results": results,
        "matching_errors": errors,
        "pipeline_errors": state.get("pipeline_errors", []) + errors,
    }


async def _match_single(
    *,
    atom: RequirementAtom,
    context: RetrievalContext | None,
    run_id: str,
) -> MatchResult:
    """Compute semantic match scores for a single atom."""
    if context is None:
        # No retrieval context — create a minimal SOFT_GAP result
        log.warning(
            f"{PHASE}.no_context",
            run_id=run_id,
            atom_id=str(atom.id),
        )
        return MatchResult(
            atom_id=atom.id,
            candidates=[],
            composite_score=0.0,
            max_cosine=0.0,
            max_overlap=0.0,
            historical_weight=0.0,
            confidence_band=ConfidenceBand.LOW,
            route_decision=RouteDecision.SOFT_GAP,
            has_exact_history=False,
            has_historical_precedent=False,
            similarity_vectors={},
        )

    # Score capabilities
    scored_caps = score_capabilities(
        context=context,
        requirement_text=atom.text,
    )

    # Build ScoredCandidate objects
    scored_candidates: list[ScoredCandidate] = []
    for scored in scored_caps:
        cap: D365CapabilityMatch = scored["capability"]
        # Historical boost from prior fitments
        historical_boost = _compute_historical_boost(
            cap.capability_id, context.prior_fitments
        )

        # Composite final score for ranking within candidates
        final_score = (
            0.50 * max(scored["rerank_score"] / max(abs(scored["rerank_score"]), 1), 0)
            + 0.25 * scored["cosine_score"]
            + 0.15 * scored["overlap_score"]
            + 0.10 * historical_boost
        )
        final_score = max(0.0, min(1.0, final_score))

        scored_candidates.append(
            ScoredCandidate(
                capability_id=cap.capability_id,
                name=cap.name,
                description=cap.description,
                module=cap.module.value,
                sub_module=cap.sub_module,
                license_requirement=cap.license_requirement,
                configuration_notes=cap.configuration_notes,
                localization_gaps=cap.localization_gaps,
                cosine_score=scored["cosine_score"],
                overlap_score=scored["overlap_score"],
                rerank_score=scored["rerank_score"],
                historical_boost=historical_boost,
                specificity_score=1.0 / (1 + len(cap.description) / 200),  # Shorter = more specific
                final_score=final_score,
            )
        )

    # Compute aggregate scores for composite
    max_cosine = max((c.cosine_score for c in scored_candidates), default=0.0)
    max_overlap = max((c.overlap_score for c in scored_candidates), default=0.0)
    historical_weight = compute_historical_weight(context.prior_fitments)

    composite = compute_composite_score(
        max_cosine=max_cosine,
        max_overlap=max_overlap,
        historical_weight=historical_weight,
        module=atom.module.value,
    )
    confidence_band = assign_confidence_band(composite)

    has_exact_history = context.has_exact_history
    has_any_history = context.has_historical_precedent

    route = decide_route(
        composite_score=composite,
        has_exact_history=has_exact_history,
        has_any_candidates=len(scored_candidates) > 0,
        has_any_history=has_any_history,
        module=atom.module.value,
    )

    # Diagnostic vectors for scoring transparency
    similarity_vectors = {
        f"cap_{i}_{c.capability_id}_cosine": c.cosine_score
        for i, c in enumerate(scored_candidates[:5])
    }

    return MatchResult(
        atom_id=atom.id,
        candidates=scored_candidates[:5],  # Top-5 for final output
        composite_score=composite,
        max_cosine=max_cosine,
        max_overlap=max_overlap,
        historical_weight=historical_weight,
        confidence_band=confidence_band,
        route_decision=route,
        has_exact_history=has_exact_history,
        has_historical_precedent=has_any_history,
        similarity_vectors=similarity_vectors,
    )


def _compute_historical_boost(
    capability_id: str, prior_fitments: list
) -> float:
    """Boost score if this capability was used in a prior fitment decision."""
    for fitment in prior_fitments:
        matched = getattr(fitment, "matched_capability", None)
        if matched and capability_id.lower() in str(matched).lower():
            return fitment.similarity_to_current * 0.5  # Partial boost based on similarity
    return 0.0
