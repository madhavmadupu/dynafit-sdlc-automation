"""
agents/validation/override_handler.py
Phase 5 override processor.
Applies consultant decisions sent via Human-in-the-Loop interrupt, writes to PostgreSQL audit trail, and pgvector history.
"""
from __future__ import annotations

import structlog

from core.schemas.classification_result import (
    AuditEntry,
    ClassificationResult,
    ConsultantDecision,
    ConsultantOverride,
    ValidatedFitmentBatch,
)
from core.schemas.requirement_atom import RequirementAtom
from core.schemas.retrieval_context import RetrievalContext
from infrastructure.storage.postgres_client import postgres_client
from infrastructure.vector_db.pgvector_client import pgvector_client
from infrastructure.vector_db.embedder import embedder

log = structlog.get_logger()


async def apply_overrides(
    *,
    results: list[ClassificationResult],
    decisions: list[ConsultantDecision],
    atoms: list[RequirementAtom],
    contexts: list[RetrievalContext],
    run_id: str,
) -> tuple[list[ClassificationResult], list[ConsultantOverride]]:
    """
    Apply consultant overrides to classification results.
    Modifies the results list, logs the audit trail, and updates the historical fitment database.

    Args:
        results: Original LLM/auto classification results
        decisions: Consultant decisions from Human-in-the-Loop PATCH
        atoms: The original RequirementAtoms
        contexts: Retrieval profiles for embedding matching
        run_id: Pipeline Run ID

    Returns:
        Tuple:
        1. Updated list of ClassificationResult (overridden)
        2. List of ConsultantOverride objects applied
    """
    result_by_id = {str(r.atom_id): r for r in results}
    atom_by_id = {str(a.id): a for a in atoms}
    context_by_id = {str(c.atom_id): c for c in contexts}

    updated_results: list[ClassificationResult] = []
    overrides_applied: list[ConsultantOverride] = []

    for d in decisions:
        atom_id = str(d.atom_id)
        if atom_id not in result_by_id:
            log.warning("override_handler.atom_not_found", atom_id=atom_id)
            continue

        original_result = result_by_id[atom_id]
        atom = atom_by_id[atom_id]
        context = context_by_id.get(atom_id)

        # Generate override record
        override = ConsultantOverride(
            atom_id=d.atom_id,
            original_verdict=original_result.verdict,
            override_verdict=d.verdict,
            reason=d.reason,
            reviewed_by=d.reviewed_by,
            reviewed_at=d.reviewed_at,
        )

        overrides_applied.append(override)

        # Apply override if it differs (otherwise, it was just human approval)
        if d.is_override:
            # Overwrite the original
            new_result = original_result.model_copy(
                update={
                    "verdict": d.verdict,
                    "rationale": f"CONSULTANT OVERRIDE: {d.reason}\n\nORIGINAL AI RATIONALE: {original_result.rationale}",
                    "needs_review": False,
                }
            )
            result_by_id[atom_id] = new_result
        else:
            # Clear flag, outcome accepted
            result_by_id[atom_id] = original_result.model_copy(update={"needs_review": False})

        # --- Persist the override/decision to Db ---

        # 1. Pipeline Audit DB
        await postgres_client.write_override(
            run_id=run_id,
            atom_id=atom_id,
            original_verdict=original_result.verdict.value,
            override_verdict=d.verdict.value,
            reason=d.reason,
            reviewed_by=d.reviewed_by,
        )

        # 2. Add to Historical Fitment DB (pgvector)
        # Needs dense vector from retrieval context query phase, but those aren't directly saved on the context.
        # We'll re-embed the atom text on the fly.
        embedding = await embedder.embed_requirement(atom.text)

        await pgvector_client.write_fitment(
            atom_hash=atom.atom_hash,
            original_text=atom.text,  # Normalized text
            module=atom.module.value,
            verdict=d.verdict.value,
            confidence=1.0,  # Human confidence is absolute
            rationale=d.reason,
            matched_capability=result_by_id[atom_id].matched_capability,
            wave_id=run_id,
            embedding=embedding,
            overridden_by_consultant=d.is_override,
        )

        log.info(
            "override_applied_and_recorded",
            run_id=run_id,
            atom_id=atom_id,
            verdict=d.verdict.value,
            consultant=d.reviewed_by,
        )

    # Return the assembled updated list
    updated_results = list(result_by_id.values())

    return updated_results, overrides_applied
