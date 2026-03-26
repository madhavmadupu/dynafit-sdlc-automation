"""
agents/validation/agent.py
Phase 5 — Validation & Output Generation LangGraph node.
Processes overrides, detects conflicts, and generates the final Excel report.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from agents.validation.consistency_checker import detect_conflicts
from agents.validation.override_handler import apply_overrides
from agents.validation.report_generator import generate_excel_report
from core.schemas.classification_result import (
    AuditEntry,
    ClassificationResult,
    ValidatedFitmentBatch,
)
from core.schemas.enums import RunStatus
from core.schemas.requirement_atom import RequirementAtom
from core.schemas.retrieval_context import RetrievalContext
from infrastructure.storage.postgres_client import postgres_client

log = structlog.get_logger()
PHASE = "validation"


async def run(state: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 5 LangGraph node: Validation Agent.

    Reads: state["classification_results"], state["matches_results"], state["atoms"],
           state["run_id"], state["consultant_decisions"], state["llm_cost_usd"]
    Writes: state["validated_batch"], state["output_path"]

    Executes after the human-in-the-loop interrupt.
    """
    run_id: str = state["run_id"]
    atoms: list[RequirementAtom] = state.get("atoms", [])
    results: list[ClassificationResult] = state.get("classification_results", [])
    contexts: list[RetrievalContext] = state.get("retrieval_contexts", [])
    decisions = state.get("consultant_decisions", [])
    llm_cost_usd = state.get("llm_cost_usd", 0.0)

    log.info(f"{PHASE}.start", run_id=run_id, decisions=len(decisions))

    # 1. Apply overrides
    updated_results, overrides_applied = await apply_overrides(
        results=results,
        decisions=decisions,
        atoms=atoms,
        contexts=contexts,
        run_id=run_id,
    )

    # 2. Check for cross-requirement consistency
    conflict_report = detect_conflicts(
        results=updated_results,
        run_id=run_id,
    )

    # 3. Create Audit Trail snapshot (in DB and returned)
    audit_trail: list[AuditEntry] = []
    for result in updated_results:
        entry = AuditEntry(
            run_id=run_id,
            atom_id=result.atom_id,
            phase=PHASE,
            action="validated",
            verdict=result.verdict,
            actor="system",
            metadata={
                "route": result.route_taken.value,
                "confidence": result.confidence,
                "overridden": any(str(o.atom_id) == str(result.atom_id) for o in overrides_applied),
            },
        )
        audit_trail.append(entry)
        await postgres_client.write_audit_entry(
            run_id=run_id,
            atom_id=str(result.atom_id),
            phase=PHASE,
            action="validated",
            verdict=result.verdict.value,
            actor="system",
            metadata=entry.metadata,
        )

    # 4. Construct Final Batch
    batch = ValidatedFitmentBatch(
        run_id=run_id,
        run_status=RunStatus.COMPLETED,
        results=updated_results,
        overrides=overrides_applied,
        conflict_report=conflict_report,
        audit_trail=audit_trail,
        total_atoms=len(atoms),
        total_llm_cost_usd=llm_cost_usd,
        completed_at=datetime.utcnow(),
    )

    # 5. Generate Excel
    try:
        output_path = generate_excel_report(batch, atoms)
    except Exception as e:
        log.error("validation.excel_generation_failed", error=str(e), exc_info=True)
        # Even if Excel fails, we save the ValidatedBatch
        output_path = None

    # Update total run status
    await postgres_client.update_run_status(run_id, RunStatus.COMPLETED)

    log.info(
        f"{PHASE}.complete",
        run_id=run_id,
        overrides=len(overrides_applied),
        conflicts=len(conflict_report.conflicts),
        output=output_path,
    )

    return {
        "validated_batch": batch,
        "output_path": output_path,
    }
