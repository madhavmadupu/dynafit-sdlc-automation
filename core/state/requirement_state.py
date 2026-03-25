"""
core/state/requirement_state.py
The single RequirementState TypedDict that flows through the entire LangGraph pipeline.
Every agent node reads from and writes partial updates to this state.
"""
from __future__ import annotations

from datetime import datetime
from typing import TypedDict
from uuid import uuid4

from core.schemas.classification_result import (
    ClassificationResult,
    ConflictReport,
    ConsultantDecision,
    ValidatedFitmentBatch,
)
from core.schemas.match_result import MatchResult
from core.schemas.requirement_atom import RejectedAtom, RequirementAtom
from core.schemas.retrieval_context import RetrievalContext


class RequirementState(TypedDict, total=False):
    """
    Pipeline state dict flowing through LangGraph nodes.

    Rules:
    - Agents return ONLY the keys they update (partial dict)
    - Never mutate the state dict in-place — LangGraph handles merging
    - `pipeline_errors` and `human_review_required` are APPEND-ONLY
    - All fields are optional (total=False) to allow partial updates
    """

    # ── Run metadata ─────────────────────────────────────────────────────────
    run_id: str                        # UUID string — thread_id for LangGraph checkpoint
    created_at: str                    # ISO datetime when run was created
    source_files: list[str]            # Original file paths / uploaded filenames
    kb_version: str                    # Knowledge base version used (for cache invalidation)

    # ── Phase 1: Ingestion ───────────────────────────────────────────────────
    atoms: list[RequirementAtom]       # Validated, normalized RequirementAtoms
    rejected_atoms: list[RejectedAtom] # Atoms hard-rejected during validation
    ingestion_errors: list[dict]       # File-level parse errors

    # ── Phase 2: Retrieval ───────────────────────────────────────────────────
    retrieval_contexts: list[RetrievalContext]  # One per atom
    retrieval_errors: list[dict]

    # ── Phase 3: Matching ────────────────────────────────────────────────────
    match_results: list[MatchResult]  # One per atom
    matching_errors: list[dict]

    # ── Phase 4: Classification ──────────────────────────────────────────────
    classification_results: list[ClassificationResult]
    classification_errors: list[dict]
    llm_cost_usd: float               # Running LLM cost total for this run

    # ── Phase 5: Validation & Output ─────────────────────────────────────────
    validated_batch: ValidatedFitmentBatch | None
    output_path: str | None           # Absolute path to fitment_matrix.xlsx

    # ── Human-in-the-Loop ────────────────────────────────────────────────────
    human_review_required: list[str]   # atom_ids (strings) needing consultant review
    consultant_decisions: list[ConsultantDecision]  # Decisions submitted via PATCH /review

    # ── Cross-phase ───────────────────────────────────────────────────────────
    pipeline_errors: list[dict]        # All errors across all phases (append-only)


def make_initial_state(
    run_id: str | None = None,
    source_files: list[str] | None = None,
    kb_version: str = "v1.0.0",
) -> RequirementState:
    """
    Factory function for creating a valid initial RequirementState.
    Always use this to start a pipeline run.

    Args:
        run_id: UUID string. Auto-generated if not provided.
        source_files: List of file paths to process.
        kb_version: Knowledge base version (for cache key generation).

    Returns:
        Populated initial state ready for LangGraph ainvoke.
    """
    return RequirementState(
        run_id=run_id or str(uuid4()),
        created_at=datetime.utcnow().isoformat(),
        source_files=source_files or [],
        kb_version=kb_version,
        atoms=[],
        rejected_atoms=[],
        ingestion_errors=[],
        retrieval_contexts=[],
        retrieval_errors=[],
        match_results=[],
        matching_errors=[],
        classification_results=[],
        classification_errors=[],
        llm_cost_usd=0.0,
        validated_batch=None,
        output_path=None,
        human_review_required=[],
        consultant_decisions=[],
        pipeline_errors=[],
    )
