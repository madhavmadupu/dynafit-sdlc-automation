"""
agents/matching/embedding_match.py
Cosine similarity and entity overlap scoring between requirement and capabilities.
Uses embeddings stored on D365CapabilityMatch from Phase 2.
"""
from __future__ import annotations

import math
import re

import structlog

from core.schemas.retrieval_context import D365CapabilityMatch, RetrievalContext

log = structlog.get_logger()


def compute_cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Compute cosine similarity between two vectors.
    Returns 0.0 if either vector is all zeros or different lengths.
    """
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


def compute_entity_overlap(requirement_text: str, capability_description: str) -> float:
    """
    Compute word/entity overlap ratio between requirement and capability description.
    Normalized by the length of the shorter text (Jaccard-like).

    Returns:
        Float in [0.0, 1.0] — proportion of requirement tokens found in capability.
    """
    def tokenize(text: str) -> set[str]:
        tokens = re.split(r"[^a-zA-Z0-9]+", text.lower())
        # Remove very short/common tokens
        return {t for t in tokens if len(t) > 2}

    req_tokens = tokenize(requirement_text)
    cap_tokens = tokenize(capability_description)

    if not req_tokens:
        return 0.0

    overlap = req_tokens & cap_tokens
    return len(overlap) / len(req_tokens)


def score_capabilities(
    context: RetrievalContext,
    requirement_text: str,
) -> list[dict]:
    """
    Score each capability in the context against the requirement.

    Produces per-capability scores:
    - cosine_score: rerank_score normalized (proxy for embedding similarity)
    - overlap_score: entity overlap ratio
    - vector_score: raw vector similarity from retrieval

    Args:
        context: RetrievalContext with top_capabilities from Phase 2
        requirement_text: Normalized requirement text

    Returns:
        List of dicts with capability and scores, sorted by vector_score desc.
    """
    scored = []
    for cap in context.top_capabilities:
        cosine = cap.vector_score if cap.vector_score > 0 else 0.0
        overlap = compute_entity_overlap(requirement_text, cap.description)

        scored.append({
            "capability": cap,
            "cosine_score": cosine,
            "overlap_score": overlap,
            "rerank_score": cap.rerank_score,
            "rrf_score": cap.rrf_score,
        })

    # Sort by rerank_score (most informative signal after CrossEncoder)
    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    return scored
