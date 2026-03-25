"""
agents/validation/consistency_checker.py
Phase 5 cross-requirement conflict detection.
Identifies logical contradictions (e.g., Atom A is FIT with AP-01, Atom B is GAP but needs AP-01).
"""
from __future__ import annotations

import structlog

from core.schemas.classification_result import ClassificationResult, ConflictEntry, ConflictReport
from core.schemas.enums import Verdict

log = structlog.get_logger()


def detect_conflicts(
    results: list[ClassificationResult],
    run_id: str,
) -> ConflictReport:
    """
    Scan all classification results in a run for cross-requirement conflicts.

    Rules:
    1. Capability Contradiction: Two atoms matched to the same capability, but one is GAP.
    2. Dependency Conflict: PARTIAL_FIT requires config X, but another atom explicitly excludes it. (Future enhancement)

    Args:
        results: Full list of post-classification results
        run_id: Pipeline run ID

    Returns:
        ConflictReport detailing all detected inconsistencies.
    """
    conflicts: list[ConflictEntry] = []

    # Rule 1: Capability Contradiction
    # Group results by matched_capability
    cap_groups: dict[str, list[ClassificationResult]] = {}
    for res in results:
        cap = res.matched_capability
        if cap:
            cap_groups.setdefault(cap, []).append(res)

    for cap, cap_results in cap_groups.items():
        if len(cap_results) < 2:
            continue

        verdicts = {r.verdict for r in cap_results}
        if Verdict.FIT in verdicts and Verdict.GAP in verdicts:
            fit_atoms = [r.atom_id for r in cap_results if r.verdict == Verdict.FIT]
            gap_atoms = [r.atom_id for r in cap_results if r.verdict == Verdict.GAP]

            conflicts.append(
                ConflictEntry(
                    conflict_type="capability_contradiction",
                    severity="WARNING",  # Advisory for consultant
                    atom_ids=fit_atoms + gap_atoms,
                    description=(
                        f"Contradictory verdicts for capability '{cap}'. "
                        f"Some requirements were marked FIT, while others mapped to "
                        f"the same capability were marked GAP."
                    ),
                    suggested_resolution="Review the GAP classification — if the capability handles the FIT requirement, why does it fail the GAP one?",
                )
            )

    log.info(
        "consistency.checked",
        run_id=run_id,
        total_atoms=len(results),
        conflicts_found=len(conflicts),
    )

    return ConflictReport(
        run_id=run_id,
        conflicts=conflicts,
    )
