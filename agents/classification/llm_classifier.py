"""
agents/classification/llm_classifier.py
LLM chain-of-thought classification for Phase 4.
Renders Jinja2 prompts, calls LLM, parses XML response.
Output: ClassificationResult per atom.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from uuid import UUID

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.config.settings import settings
from core.schemas.classification_result import ClassificationResult
from core.schemas.enums import RouteDecision, Verdict
from core.schemas.match_result import MatchResult, ScoredCandidate
from core.schemas.requirement_atom import RequirementAtom
from core.schemas.retrieval_context import RetrievalContext
from infrastructure.llm.client import LLMResponse, llm_call

log = structlog.get_logger()

# Module-specific guidance lookup
_MODULE_NOTES: dict[str, str] = {
    "AP": "AP has strong vendor invoicing, three-way matching, and payment features. Localization gaps exist for India TDS/GST and Germany DATEV.",
    "AR": "AR supports customer invoicing, collections, and revenue recognition (ASC 606 via separate module). E-invoicing support varies by country.",
    "GL": "GL covers COA, journal management, financial reporting, and consolidation. DATEV and ELSTER are gaps for Germany.",
    "SCM": "SCM covers procurement, trade agreements, and master planning. US customs CBP filing requires ISV.",
    "WMS": "WMS (Warehouse Management) supports advanced warehousing, directed put-away, and wave picking. Some automated sorting systems need ISV.",
    "MFG": "Manufacturing covers discrete, lean, and process manufacturing. MES integration gaps exist for real-time shop floor control.",
    "PM": "Project Management covers fixed-price, T&M, and investment projects. Earned value management is configurable but complex.",
    "HR": "HR covers basic personnel management. Payroll is a separate module. Advanced position budgeting may need ISV.",
    "PAYROLL": "Payroll has localizations for many countries but India labor law compliance (PF, ESI, gratuity) typically requires ISV.",
    "FA": "Fixed Assets covers acquisition, depreciation, disposal, and leasing (ASC 842 via Asset Leasing module).",
}


def _get_jinja_env() -> Environment:
    prompts_dir = str(Path(__file__).parents[2] / "core" / "prompts")
    return Environment(
        loader=FileSystemLoader(prompts_dir),
        autoescape=select_autoescape([]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


async def classify_with_llm(
    *,
    atom: RequirementAtom,
    match_result: MatchResult,
    context: RetrievalContext | None,
    run_id: str,
) -> ClassificationResult:
    """
    Run LLM chain-of-thought classification for a single atom.

    Args:
        atom: The RequirementAtom to classify
        match_result: Phase 3 scoring result with candidates
        context: Phase 2 retrieval context (optional — may be None)
        run_id: Pipeline run ID

    Returns:
        ClassificationResult with verdict, confidence, rationale, and cost tracking.

    Raises:
        Any LLM client exception if retries exhausted.
    """
    env = _get_jinja_env()

    # Build system message from classification_system.j2
    system_template = env.get_template("classification_system.j2")
    system_prompt = system_template.render(
        module=atom.module.value,
        module_specific_notes=_MODULE_NOTES.get(atom.module.value, ""),
    )

    # Build user message from classification_user.j2
    user_template = env.get_template("classification_user.j2")
    user_prompt = user_template.render(
        requirement_text=atom.text,
        module=atom.module.value,
        country=atom.country,
        priority=atom.priority.value,
        intent=atom.intent.value,
        composite_score=match_result.composite_score,
        confidence_band=match_result.confidence_band.value,
        top_candidates=match_result.candidates,
        prior_decisions=context.prior_fitments if context else [],
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response: LLMResponse = await llm_call(
        messages=messages,
        model=settings.CLASSIFICATION_MODEL,
        max_tokens=settings.CLASSIFICATION_MAX_TOKENS,
        trace_name="phase4_classification",
        run_id=run_id,
    )

    # Parse XML response
    parsed = _parse_classification_xml(response.content, atom.id)
    parsed_with_meta = parsed.model_copy(
        update={
            "llm_model": settings.CLASSIFICATION_MODEL,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "route_taken": RouteDecision.LLM,
        }
    )
    return parsed_with_meta


def _parse_classification_xml(content: str, atom_id: UUID) -> ClassificationResult:
    """Parse LLM XML response into a ClassificationResult."""
    # Extract the <classification> block
    xml_match = re.search(r"<classification>(.*?)</classification>", content, re.DOTALL)
    if not xml_match:
        raise ValueError(f"No <classification> block found in LLM response: {content[:200]}")

    xml_str = f"<classification>{xml_match.group(1)}</classification>"

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        raise ValueError(f"Invalid XML in LLM response: {e}\nContent: {xml_str[:300]}") from e

    def get_text(tag: str, default: str = "") -> str:
        el = root.find(tag)
        return (el.text or "").strip() if el is not None else default

    verdict_str = get_text("verdict", "GAP").upper()
    try:
        verdict = Verdict(verdict_str)
    except ValueError:
        log.warning("invalid_verdict_in_llm_response", raw=verdict_str)
        verdict = Verdict.GAP

    try:
        confidence = float(get_text("confidence", "0.5"))
        confidence = max(0.0, min(1.0, confidence))
    except ValueError:
        confidence = 0.5

    matched_capability = get_text("matched_capability") or None
    gap_description = get_text("gap_description") or None
    config_needed = get_text("config_needed") or None
    rationale = get_text("rationale", "No rationale provided.")

    caveats_raw = get_text("caveats")
    caveats = [c.strip() for c in caveats_raw.split(";") if c.strip()] if caveats_raw else []

    return ClassificationResult(
        atom_id=atom_id,
        verdict=verdict,
        confidence=confidence,
        matched_capability=matched_capability,
        gap_description=gap_description,
        config_needed=config_needed,
        rationale=rationale,
        caveats=caveats,
        route_taken=RouteDecision.LLM,  # Will be overridden for FAST_TRACK/SOFT_GAP
    )


def make_fast_track_result(
    atom: RequirementAtom,
    match_result: MatchResult,
) -> ClassificationResult:
    """
    Create a ClassificationResult for FAST_TRACK routed atoms.
    Uses best historical fitment as the classification.
    No LLM call — zero cost.
    """
    # Find the exact history match
    best_candidate = match_result.candidates[0] if match_result.candidates else None

    return ClassificationResult(
        atom_id=atom.id,
        verdict=Verdict.FIT,  # FAST_TRACK always → FIT (based on exact history)
        confidence=0.95,   # High confidence from exact historical precedent
        matched_capability=best_candidate.name if best_candidate else None,
        gap_description=None,
        config_needed=None,
        rationale=(
            f"FAST_TRACK: Exact match found in historical fitment database. "
            f"Prior wave classified this as FIT with high confidence. "
            f"Composite score: {match_result.composite_score:.2f}."
        ),
        caveats=[],
        route_taken=RouteDecision.FAST_TRACK,
        llm_model=None,
        prompt_tokens=0,
        completion_tokens=0,
    )


def make_soft_gap_result(atom: RequirementAtom) -> ClassificationResult:
    """
    Create a ClassificationResult for SOFT_GAP routed atoms.
    Low confidence + no retrieval evidence → auto-GAP.
    No LLM call — zero cost.
    """
    return ClassificationResult(
        atom_id=atom.id,
        verdict=Verdict.GAP,
        confidence=0.50,
        matched_capability=None,
        gap_description=(
            "No matching D365 capabilities were retrieved from the knowledge base, "
            "and no historical precedent exists for this requirement. "
            "This is a likely gap requiring custom development or ISV solution."
        ),
        config_needed=None,
        rationale=(
            f"SOFT_GAP: Composite retrieval score below threshold with no D365 capabilities "
            f"found and no historical precedent. Auto-classified as GAP pending consultant review."
        ),
        caveats=["Confidence is low — recommend consultant manual review"],
        route_taken=RouteDecision.SOFT_GAP,
        llm_model=None,
        prompt_tokens=0,
        completion_tokens=0,
        needs_review=True,
        sanity_flags=["soft_gap_auto_classified"],
    )
