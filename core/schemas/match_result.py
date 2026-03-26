"""
core/schemas/match_result.py
Phase 3 output schema — semantic matching scores and routing decision.
Flows into Phase 4 (Classification Agent).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.schemas.enums import ConfidenceBand, RouteDecision


class ScoredCandidate(BaseModel):
    """
    A D365 capability candidate scored by the semantic matching agent.
    Multi-factor score combining crossencoder, cosine, overlap, and historical signals.
    """

    model_config = ConfigDict(frozen=True)

    capability_id: str = Field(description="D365 capability identifier")
    name: str = Field(description="Capability name")
    description: str = Field(description="Capability description")
    module: str = Field(description="D365 module code")
    sub_module: str | None = Field(default=None)
    license_requirement: str | None = Field(default=None)
    configuration_notes: str | None = Field(default=None)
    localization_gaps: dict[str, list[str]] = Field(default_factory=dict)

    # Score components
    cosine_score: float = Field(ge=0.0, le=1.0, description="Embedding cosine similarity")
    overlap_score: float = Field(
        ge=0.0, le=1.0, description="Entity/term overlap ratio (spaCy NER)"
    )
    rerank_score: float = Field(description="CrossEncoder pairwise relevance score")
    historical_boost: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Boost from historical use in prior waves",
    )
    specificity_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Shorter, more specific descriptions preferred (1.0 = most specific)",
    )

    # Final composite score
    final_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Multi-factor composite: 0.5*rerank + 0.25*cosine + 0.15*overlap + 0.1*hist",
    )


class MatchResult(BaseModel):
    """
    Phase 3 output — semantic match analysis for a single RequirementAtom.
    Contains routing decision and ranked candidate capabilities.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    atom_id: UUID = Field(description="ID of the RequirementAtom this result is for")

    # Ranked top-5 candidates for Phase 4 context
    candidates: list[ScoredCandidate] = Field(
        default_factory=list,
        description="Ranked top-5 D365 capability candidates (post-dedup)",
    )

    # Composite confidence score
    composite_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Weighted composite: 0.50*max_cosine + 0.30*max_overlap + 0.20*historical_weight. "
            "Module YAML can override weights."
        ),
    )

    # Score components for diagnostics
    max_cosine: float = Field(ge=0.0, le=1.0, default=0.0)
    max_overlap: float = Field(ge=0.0, le=1.0, default=0.0)
    historical_weight: float = Field(ge=0.0, le=1.0, default=0.0)

    # Confidence classification
    confidence_band: ConfidenceBand = Field(
        description="HIGH (≥0.70), MED (0.40-0.69), LOW (<0.40)"
    )

    # Phase 4 routing decision
    route_decision: RouteDecision = Field(
        description="FAST_TRACK (skip LLM), LLM (full reasoning), SOFT_GAP (auto-GAP)"
    )

    # Historical precedent flags
    has_exact_history: bool = Field(
        default=False,
        description="True if atom_hash exactly matched a prior wave decision",
    )
    has_historical_precedent: bool = Field(
        default=False,
        description="True if any similar historical decision exists",
    )

    # Diagnostic vectors for debugging
    similarity_vectors: dict[str, float] = Field(
        default_factory=dict,
        description="Score breakdown per candidate for diagnostic use",
    )

    @model_validator(mode="after")
    def validate_routing_logic(self) -> MatchResult:
        """Ensure FAST_TRACK requires historical precedent."""
        if self.route_decision == RouteDecision.FAST_TRACK and not self.has_exact_history:
            raise ValueError("FAST_TRACK route requires has_exact_history=True")
        return self
