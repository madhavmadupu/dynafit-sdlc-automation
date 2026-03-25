"""
core/schemas/retrieval_context.py
Phase 2 output schema — grounded evidence assembled for each RequirementAtom.
Flows into Phase 3 (Semantic Matching Agent).
"""
from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.enums import D365Module, Verdict


class D365CapabilityMatch(BaseModel):
    """A D365 capability returned from the knowledge base, with retrieval scores."""

    model_config = ConfigDict(frozen=True)

    capability_id: str = Field(description="Unique capability identifier (e.g. 'AP-001')")
    name: str = Field(description="Capability name")
    description: str = Field(description="Full capability description")
    module: D365Module = Field(description="D365 module this capability belongs to")
    sub_module: str | None = Field(default=None)
    license_requirement: str | None = Field(
        default=None, description="License tier required (e.g. 'Finance', 'Finance + Ops')"
    )
    configuration_notes: str | None = Field(
        default=None, description="How to configure this capability"
    )
    localization_gaps: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Country-specific gaps: {'IN': ['TDS not supported'], 'DE': ['DATEV needed']}",
    )
    # Retrieval scores
    vector_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Cosine similarity score")
    bm25_score: float = Field(default=0.0, ge=0.0, description="BM25 keyword relevance score")
    rrf_score: float = Field(default=0.0, ge=0.0, description="Reciprocal Rank Fusion score")
    rerank_score: float = Field(
        default=0.0, description="CrossEncoder reranking score (higher = more relevant)"
    )


class DocChunkMatch(BaseModel):
    """A chunk from the Microsoft Learn documentation corpus."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(description="Unique chunk identifier")
    source_url: str = Field(description="URL of the MS Learn page")
    page_title: str = Field(description="Title of the MS Learn page")
    section_heading: str | None = Field(default=None)
    text: str = Field(description="Chunk text content")
    vector_score: float = Field(default=0.0, ge=0.0, le=1.0)


class HistoricalFitmentMatch(BaseModel):
    """A prior fitment decision for the same or similar requirement."""

    model_config = ConfigDict(frozen=True)

    fitment_id: str = Field(description="UUID of the historical fitment record")
    original_text: str = Field(description="Original requirement text from prior wave")
    verdict: Verdict = Field(description="Prior classification verdict")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(description="Prior LLM reasoning")
    wave_id: str = Field(description="Identifier of the prior implementation wave")
    overridden_by_consultant: bool = Field(
        default=False, description="True if a consultant overrode the AI verdict"
    )
    matched_capability: str | None = Field(default=None)
    similarity_to_current: float = Field(
        ge=0.0,
        le=1.0,
        description="Embedding similarity to current atom (1.0 = exact hash match)",
    )
    is_exact_match: bool = Field(
        default=False, description="True if atom_hash matched exactly"
    )


class RetrievalContext(BaseModel):
    """
    Phase 2 output — assembled evidence context for a single RequirementAtom.
    Contains top-5 D365 capabilities + MS Learn refs + historical decisions.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4, description="Unique context ID")
    atom_id: UUID = Field(description="ID of the RequirementAtom this context was built for")
    atom_hash: str = Field(description="SHA256 hash — for cache key generation")

    # Top 5 matched D365 capabilities (after RRF + CrossEncoder reranking)
    top_capabilities: list[D365CapabilityMatch] = Field(
        default_factory=list,
        description="Top-5 D365 capabilities ranked by relevance (post-rerank)",
    )

    # MS Learn documentation references
    ms_learn_refs: list[DocChunkMatch] = Field(
        default_factory=list,
        description="Top-3 MS Learn documentation chunks most relevant to the requirement",
    )

    # Historical fitment decisions
    prior_fitments: list[HistoricalFitmentMatch] = Field(
        default_factory=list,
        description="Prior wave decisions for same or similar requirements",
    )

    # Diagnostic signals
    confidence_signals: dict[str, float | bool | int | str] = Field(
        default_factory=dict,
        description="Raw retrieval diagnostics: {'max_rerank_score': 0.92, 'has_history': True}",
    )

    # Cache + provenance metadata
    cache_hit: bool = Field(
        default=False, description="True if this context was served from Redis cache"
    )
    kb_version: str = Field(
        description="Knowledge base version used for retrieval (for cache invalidation)"
    )
    sources_available: list[str] = Field(
        default_factory=list,
        description="Which knowledge sources responded: ['d365_kb', 'ms_learn', 'history']",
    )

    @property
    def has_historical_precedent(self) -> bool:
        """True if any historical fitment was found."""
        return len(self.prior_fitments) > 0

    @property
    def has_exact_history(self) -> bool:
        """True if an exact atom_hash match was found in history."""
        return any(f.is_exact_match for f in self.prior_fitments)
