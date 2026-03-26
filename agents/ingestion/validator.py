"""
agents/ingestion/validator.py
Quality gate for PartialAtom objects.
Hard-rejects low-quality atoms; soft-flags borderline ones.
"""

from __future__ import annotations

import structlog

from agents.ingestion.req_extractor import PartialAtom
from core.config.thresholds import THRESHOLDS
from core.schemas.enums import AtomStatus, D365Module, IntentType, MoSCoW
from core.schemas.requirement_atom import RejectedAtom, RequirementAtom

log = structlog.get_logger()


def validate_atoms(
    atoms: list[PartialAtom],
) -> tuple[list[RequirementAtom], list[RejectedAtom]]:
    """
    Validate normalized PartialAtoms against schema and quality rules.

    Hard failures (→ RejectedAtom):
    - text < 10 chars
    - completeness_score < 20 (THRESHOLDS["completeness_reject"])
    - module not a valid D365Module value

    Soft failures (→ RequirementAtom with needs_review=True):
    - completeness_score between 20-40 (THRESHOLDS["completeness_flag"])
    - module == UNKNOWN

    Args:
        atoms: Normalized PartialAtom list from normalizer

    Returns:
        Tuple of (valid RequirementAtoms, rejected RejectedAtoms)
    """
    valid: list[RequirementAtom] = []
    rejected: list[RejectedAtom] = []

    reject_threshold = THRESHOLDS["completeness_reject"]
    flag_threshold = THRESHOLDS["completeness_flag"]

    for atom in atoms:
        rejection_reason = _get_hard_rejection_reason(atom, reject_threshold)

        if rejection_reason:
            rejected.append(
                RejectedAtom(
                    raw_text=atom.raw_text or atom.text,
                    source_ref=atom.source_ref,
                    source_file=atom.source_file,
                    rejection_reason=rejection_reason,
                    completeness_score=atom.completeness_score,
                )
            )
            log.info(
                "atom_rejected",
                source_ref=atom.source_ref,
                reason=rejection_reason,
                completeness=atom.completeness_score,
            )
            continue

        # Soft flags
        needs_review = False
        if atom.completeness_score < flag_threshold:
            needs_review = True
        if atom.module == D365Module.UNKNOWN.value:
            needs_review = True

        # Compute atom hash from normalized text
        atom_hash = RequirementAtom.compute_hash(atom.text)

        try:
            req_atom = RequirementAtom(
                atom_hash=atom_hash,
                text=atom.text,
                raw_text=atom.raw_text,
                module=D365Module(atom.module),
                sub_module=atom.sub_module,
                priority=MoSCoW(atom.priority),
                intent=IntentType(atom.intent),
                country=atom.country,
                completeness_score=atom.completeness_score,
                source_ref=atom.source_ref,
                source_file=atom.source_file,
                needs_review=needs_review,
                status=AtomStatus.ACTIVE,
            )
            valid.append(req_atom)
        except Exception as e:
            reason = f"Schema validation failed: {e}"
            rejected.append(
                RejectedAtom(
                    raw_text=atom.raw_text or atom.text,
                    source_ref=atom.source_ref,
                    source_file=atom.source_file,
                    rejection_reason=reason,
                    completeness_score=atom.completeness_score,
                )
            )
            log.warning("atom_schema_validation_failed", source_ref=atom.source_ref, error=str(e))

    log.info(
        "validation_complete",
        total_input=len(atoms),
        valid=len(valid),
        rejected=len(rejected),
        needs_review=sum(1 for a in valid if a.needs_review),
    )
    return valid, rejected


def _get_hard_rejection_reason(atom: PartialAtom, reject_threshold: float) -> str | None:
    """
    Check if atom should be hard-rejected. Returns rejection reason or None.
    """
    if not atom.text or len(atom.text.strip()) < 10:
        return f"Text too short ({len(atom.text)} chars, minimum 10)"

    if atom.completeness_score < reject_threshold:
        return (
            f"Completeness score {atom.completeness_score:.1f} below "
            f"rejection threshold {reject_threshold}"
        )

    valid_modules = {m.value for m in D365Module}
    if atom.module not in valid_modules:
        return f"Invalid module '{atom.module}'. Must be one of: {', '.join(sorted(valid_modules))}"

    return None
