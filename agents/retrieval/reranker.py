"""
agents/retrieval/reranker.py
CrossEncoder reranking of top-20 RRF candidates to top-5.
Model: cross-encoder/ms-marco-MiniLM-L-6-v2
CPU-bound inference runs in thread pool executor (non-blocking).
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

import structlog

from core.config.settings import settings
from core.schemas.retrieval_context import D365CapabilityMatch

log = structlog.get_logger()


@lru_cache(maxsize=1)
def _load_cross_encoder() -> object:
    """Load CrossEncoder model once. Cached via lru_cache (singleton)."""
    from sentence_transformers import CrossEncoder

    model_name = settings.RERANKER_MODEL
    log.info("reranker.loading_model", model=model_name)
    model = CrossEncoder(model_name)
    log.info("reranker.model_loaded", model=model_name)
    return model


class CrossEncoderReranker:
    """
    Reranks top-20 fused candidates to top-5 using pairwise cross-encoder scoring.

    Input: (requirement_text, capability_description) pairs
    Output: Top-5 capabilities sorted by cross-encoder relevance score

    Model is loaded once at first use via @lru_cache (singleton pattern).
    Inference runs in thread pool to avoid blocking the async event loop.
    """

    @property
    def model(self) -> object:
        return _load_cross_encoder()

    async def rerank(
        self,
        requirement_text: str,
        candidates: list[D365CapabilityMatch],
        top_k: int | None = None,
    ) -> list[D365CapabilityMatch]:
        """
        Rerank candidates by pairwise relevance to the requirement.

        Args:
            requirement_text: Normalized requirement text from RequirementAtom.
            candidates: Up to 20 candidate capabilities after RRF fusion.
            top_k: How many to return (defaults to settings.RERANKER_TOP_K = 5).

        Returns:
            Reranked candidates, trimmed to top_k, with rerank_score populated.
        """
        if top_k is None:
            top_k = settings.RERANKER_TOP_K

        if not candidates:
            return []

        if len(candidates) == 1:
            # No reranking needed for single candidate
            return [candidates[0].model_copy(update={"rerank_score": 5.0})]

        # Build (query, passage) pairs for CrossEncoder
        pairs = [(requirement_text, cap.description) for cap in candidates]

        # Run CPU-bound inference in thread pool — non-blocking
        loop = asyncio.get_event_loop()
        scores: list[float] = await loop.run_in_executor(
            None,
            lambda: self.model.predict(pairs).tolist(),  # type: ignore[attr-defined]
        )

        # Attach scores and sort
        scored: list[tuple[float, D365CapabilityMatch]] = [
            (score, cap.model_copy(update={"rerank_score": score}))
            for score, cap in zip(scores, candidates)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        result = [cap for _, cap in scored[:top_k]]

        log.debug(
            "reranker_complete",
            input_count=len(candidates),
            top_k=top_k,
            top_score=round(scored[0][0], 3) if scored else 0,
            top_cap=result[0].name if result else "none",
        )
        return result

    async def health_check(self) -> bool:
        """Verify CrossEncoder model is loaded."""
        try:
            _ = self.model
            return True
        except Exception as e:
            log.error("reranker.health_check_failed", error=str(e))
            return False
