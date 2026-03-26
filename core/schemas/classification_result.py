"""
core/schemas/classification_result.py
Phase 4 and Phase 5 output schemas.
ClassificationResult is the core decision object; ValidatedFitmentBatch is the final output.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.schemas.enums import RouteDecision, RunStatus, Verdict


class ClassificationResult(BaseModel):
    """
    Phase 4 output — LLM-based fitment classification for a single RequirementAtom.
    Immutable after creation. Verdict is FIT | PARTIAL_FIT | GAP.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    atom_id: UUID = Field(description="ID of the RequirementAtom this result classifies")

    # Core verdict
    verdict: Verdict = Field(description="FIT | PARTIAL_FIT | GAP")
    confidence: float = Field(ge=0.0, le=1.0, description="LLM self-reported confidence (0.0-1.0)")

    # Supporting evidence
    matched_capability: str | None = Field(
        default=None,
        description="Name of the matched D365 capability (required for FIT and PARTIAL_FIT)",
    )
    gap_description: str | None = Field(
        default=None,
        description="Description of what D365 cannot cover (required for GAP and PARTIAL_FIT)",
    )
    config_needed: str | None = Field(
        default=None,
        description="Configuration steps required (required for PARTIAL_FIT)",
    )
    rationale: str = Field(
        min_length=20,
        description="LLM chain-of-thought explanation of the classification decision",
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Important caveats: license requirements, localization notes",
    )

    # Routing and processing metadata
    route_taken: RouteDecision = Field(
        description="Which Phase 3 route was used: FAST_TRACK | LLM | SOFT_GAP"
    )
    llm_model: str | None = Field(
        default=None,
        description="LLM model used (None for FAST_TRACK/SOFT_GAP routes)",
    )
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)

    # Review flags (set by sanity checker)
    needs_review: bool = Field(
        default=False,
        description="True if flagged by sanity checker for human consultant review",
    )
    sanity_flags: list[str] = Field(
        default_factory=list,
        description="List of triggered sanity check rule names",
    )

    classified_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("gap_description")
    @classmethod
    def gap_needs_description(cls, v: str | None, info: object) -> str | None:
        """GAP verdict must have gap_description."""
        # Access other fields via info.data
        data = info.data if hasattr(info, "data") else {}
        verdict = data.get("verdict")
        if verdict == Verdict.GAP and not v:
            raise ValueError("GAP verdict requires gap_description to be set")
        return v

    @field_validator("matched_capability")
    @classmethod
    def fit_needs_capability(cls, v: str | None, info: object) -> str | None:
        """FIT and PARTIAL_FIT must have matched_capability."""
        data = info.data if hasattr(info, "data") else {}
        verdict = data.get("verdict")
        if verdict in (Verdict.FIT, Verdict.PARTIAL_FIT) and not v:
            raise ValueError(f"{verdict} verdict requires matched_capability to be set")
        return v


class ConsultantDecision(BaseModel):
    """
    A consultant's override decision submitted during human review (Phase 5 interrupt).
    Frozen — immutable once submitted.
    """

    model_config = ConfigDict(frozen=True)

    atom_id: UUID = Field(description="ID of the RequirementAtom being reviewed")
    verdict: Verdict = Field(description="Override verdict (may equal the AI verdict if approved)")
    reason: str = Field(
        min_length=10,
        description="Reason for the override or approval. Min 10 chars required.",
    )
    reviewed_by: str = Field(description="Consultant identifier (name or employee ID)")
    reviewed_at: datetime = Field(default_factory=datetime.utcnow)
    is_override: bool = Field(
        description="True if this changes the AI verdict; False if approving AI verdict"
    )


class ConsultantOverride(BaseModel):
    """Recorded override with both original and new verdict, for audit trail."""

    model_config = ConfigDict(frozen=True)

    atom_id: UUID
    original_verdict: Verdict
    override_verdict: Verdict
    reason: str
    reviewed_by: str
    reviewed_at: datetime


class ConflictEntry(BaseModel):
    """A detected cross-requirement conflict."""

    model_config = ConfigDict(frozen=True)

    conflict_id: UUID = Field(default_factory=uuid4)
    conflict_type: str = Field(
        description=(
            "One of: 'capability_contradiction', 'country_inconsistency', "
            "'confidence_cluster_warning', 'dependency_conflict'"
        )
    )
    severity: str = Field(description="'ERROR' (blocking) or 'WARNING' (advisory)")
    atom_ids: list[UUID] = Field(description="Atoms involved in this conflict")
    description: str = Field(description="Human-readable conflict description")
    suggested_resolution: str = Field(default="", description="Suggested fix")


class ConflictReport(BaseModel):
    """Summary of all cross-requirement conflicts detected in Phase 5."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description="Pipeline run ID")
    conflicts: list[ConflictEntry] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        """Number of blocking (ERROR severity) conflicts."""
        return sum(1 for c in self.conflicts if c.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        """Number of advisory (WARNING severity) conflicts."""
        return sum(1 for c in self.conflicts if c.severity == "WARNING")


class AuditEntry(BaseModel):
    """Single entry in the audit trail — one per classification decision."""

    model_config = ConfigDict(frozen=True)

    entry_id: UUID = Field(default_factory=uuid4)
    run_id: str
    atom_id: UUID
    phase: str = Field(description="Pipeline phase that generated this entry")
    action: str = Field(description="What happened: 'classified', 'overridden', 'flagged'")
    verdict: Verdict | None = Field(default=None)
    actor: str = Field(
        default="system", description="'system' for AI decisions, consultant ID for overrides"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, str | float | bool | int] = Field(default_factory=dict)


class ValidatedFitmentBatch(BaseModel):
    """
    Phase 5 final output — validated classification results with audit trail.
    This feeds into fitment_matrix.xlsx generation.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description="Pipeline run ID (UUID string)")
    run_status: RunStatus = Field(default=RunStatus.COMPLETED)

    # Final results (post human review)
    results: list[ClassificationResult] = Field(
        description="Final classification results, post-override application"
    )
    overrides: list[ConsultantOverride] = Field(
        default_factory=list, description="All consultant overrides applied"
    )

    # Conflict analysis
    conflict_report: ConflictReport = Field(
        description="Cross-requirement conflict analysis report"
    )

    # Audit trail
    audit_trail: list[AuditEntry] = Field(
        default_factory=list, description="Full audit trail of all decisions"
    )

    # Output
    output_path: str | None = Field(
        default=None, description="Absolute path to generated fitment_matrix.xlsx"
    )

    # Run statistics
    total_atoms: int = Field(default=0, ge=0)
    total_llm_cost_usd: float = Field(default=0.0, ge=0.0)
    completed_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def fit_count(self) -> int:
        return sum(1 for r in self.results if r.verdict == Verdict.FIT)

    @property
    def partial_fit_count(self) -> int:
        return sum(1 for r in self.results if r.verdict == Verdict.PARTIAL_FIT)

    @property
    def gap_count(self) -> int:
        return sum(1 for r in self.results if r.verdict == Verdict.GAP)

    @property
    def fit_rate(self) -> float:
        return self.fit_count / len(self.results) if self.results else 0.0

    @property
    def gap_rate(self) -> float:
        return self.gap_count / len(self.results) if self.results else 0.0

    @property
    def override_count(self) -> int:
        return len(self.overrides)
