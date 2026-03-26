"""
core/schemas/requirement_atom.py
Primary unit of work flowing through the DYNAFIT pipeline.
RequirementAtom is immutable (frozen=True) — never mutate after creation.
"""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.schemas.enums import AtomStatus, D365Module, IntentType, MoSCoW


class RequirementAtom(BaseModel):
    """
    A single, atomic, independently assessable business requirement.

    Created by Phase 1 (Ingestion Agent). Immutable after creation.
    SHA256 hash of normalized text used for deduplication and cache keys.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for this atom")
    atom_hash: str = Field(
        description="SHA256 of normalized text — used for dedup and Redis cache key",
        min_length=64,
        max_length=64,
    )
    text: str = Field(
        min_length=10,
        description="Normalized, unambiguous requirement text in D365 canonical terminology",
    )
    raw_text: str = Field(
        description="Original requirement text as extracted from source document",
        default="",
    )
    module: D365Module = Field(description="D365 module this requirement belongs to")
    sub_module: str | None = Field(
        default=None, description="D365 sub-module (e.g. 'Vendor invoicing')"
    )
    priority: MoSCoW = Field(description="MoSCoW priority classification")
    intent: IntentType = Field(
        description=(
            "Nature of the requirement (FUNCTIONAL, NFR, INTEGRATION, REPORTING, DATA_MIGRATION)"
        )
    )
    country: str | None = Field(
        default=None,
        description=(
            "2-letter ISO country code if requirement is country-specific (e.g. 'IN', 'DE')"
        ),
    )
    completeness_score: float = Field(
        ge=0.0,
        le=100.0,
        description="Quality score 0-100. <20=hard rejected, 20-40=soft flag, ≥40=acceptable",
    )
    source_ref: str = Field(
        description=(
            "Origin document + location (e.g. 'brd.xlsx:row_42', 'requirements.docx:para_7')"
        )
    )
    source_file: str = Field(description="Source filename (basename only)", default="")
    needs_review: bool = Field(
        default=False,
        description="True if flagged by ingestion validator for human attention",
    )
    status: AtomStatus = Field(
        default=AtomStatus.ACTIVE,
        description="Processing status (ACTIVE, ERROR, DUPLICATE, OUT_OF_SCOPE)",
    )

    @field_validator("atom_hash")
    @classmethod
    def validate_hash_format(cls, v: str) -> str:
        """Ensure atom_hash is a valid 64-char hex string."""
        if not all(c in "0123456789abcdef" for c in v.lower()):
            raise ValueError("atom_hash must be a lowercase hex string")
        return v.lower()

    @field_validator("country")
    @classmethod
    def validate_country_code(cls, v: str | None) -> str | None:
        """Ensure country is a 2-letter ISO code if provided."""
        if v is not None and (len(v) != 2 or not v.isalpha()):
            raise ValueError("country must be a 2-letter ISO code (e.g. 'IN', 'DE')")
        return v.upper() if v else None

    @classmethod
    def compute_hash(cls, normalized_text: str) -> str:
        """Compute SHA256 hash of normalized text. Use this to set atom_hash."""
        return hashlib.sha256(normalized_text.strip().lower().encode()).hexdigest()


class RejectedAtom(BaseModel):
    """
    An atom that was hard-rejected during Phase 1 validation.
    Preserved for audit trail and debugging.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    raw_text: str = Field(description="Original text that was rejected")
    source_ref: str = Field(description="Source document + location")
    source_file: str = Field(default="")
    rejection_reason: str = Field(description="Why this atom was rejected")
    completeness_score: float = Field(default=0.0, ge=0.0, le=100.0)
    retry_count: int = Field(default=0, description="Number of re-extraction attempts made")
