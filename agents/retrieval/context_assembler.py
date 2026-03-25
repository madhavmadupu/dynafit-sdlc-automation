"""
agents/retrieval/context_assembler.py
Assembles top-5 capabilities + MS Learn refs + historical fitments into RetrievalContext.
Also manages Redis cache for retrieval results.
"""
from __future__ import annotations

import structlog

from core.config.settings import settings
from core.schemas.requirement_atom import RequirementAtom
from core.schemas.retrieval_context import (
    D365CapabilityMatch,
    DocChunkMatch,
    HistoricalFitmentMatch,
    RetrievalContext,
)
from infrastructure.storage.redis_client import redis_client

log = structlog.get_logger()


class ContextAssembler:
    """
    Assembles RetrievalContext from retrieved knowledge sources.
    Manages Redis read-through cache with 24h TTL.

    Cache key: "retrieval:{atom_hash}:{kb_version}"
    Cache invalidation: Automatic when KB_VERSION changes.
    """

    async def get_cached(
        self, atom: RequirementAtom, kb_version: str
    ) -> RetrievalContext | None:
        """
        Check Redis cache before performing retrieval.

        Args:
            atom: The RequirementAtom being processed
            kb_version: Current KB version for cache key

        Returns:
            Cached RetrievalContext if found, None otherwise.
        """
        context = await redis_client.get_retrieval_context(
            atom_hash=atom.atom_hash,
            kb_version=kb_version,
        )
        if context:
            log.debug(f"{settings.RETRIEVAL_CACHE_TTL_SEC}.cache_hit", atom_id=str(atom.id))
        return context

    async def cache(self, context: RetrievalContext, kb_version: str) -> None:
        """
        Write a RetrievalContext to Redis cache.

        Args:
            context: The assembled context to cache
            kb_version: Current KB version for cache key
        """
        await redis_client.set_retrieval_context(
            context=context,
            kb_version=kb_version,
        )

    def assemble(
        self,
        *,
        atom: RequirementAtom,
        top_capabilities: list[D365CapabilityMatch],
        ms_learn_refs: list[DocChunkMatch],
        prior_fitments: list[HistoricalFitmentMatch],
        sources_available: list[str],
        cache_hit: bool = False,
    ) -> RetrievalContext:
        """
        Assemble a RetrievalContext from all retrieved evidence.

        Args:
            atom: Source RequirementAtom
            top_capabilities: Top-5 D365 capabilities (after reranking)
            ms_learn_refs: Up to 3 MS Learn documentation chunks
            prior_fitments: Historical fitment decisions for this atom
            sources_available: Which knowledge sources responded
            cache_hit: True if served from cache (not fresh retrieval)

        Returns:
            Immutable RetrievalContext ready for Phase 3.
        """
        # Confidence diagnostic signals
        confidence_signals: dict = {
            "max_rerank_score": max(
                (c.rerank_score for c in top_capabilities), default=0.0
            ),
            "max_vector_score": max(
                (c.vector_score for c in top_capabilities), default=0.0
            ),
            "has_history": len(prior_fitments) > 0,
            "has_exact_history": any(p.is_exact_match for p in prior_fitments),
            "n_capabilities": len(top_capabilities),
            "n_sources": len(sources_available),
        }

        context = RetrievalContext(
            atom_id=atom.id,
            atom_hash=atom.atom_hash,
            top_capabilities=top_capabilities[:settings.RERANKER_TOP_K],
            ms_learn_refs=ms_learn_refs[:3],  # Top-3 MS Learn chunks
            prior_fitments=prior_fitments,
            confidence_signals=confidence_signals,
            cache_hit=cache_hit,
            kb_version=settings.KB_VERSION,
            sources_available=sources_available,
        )

        log.debug(
            "context_assembled",
            atom_id=str(atom.id),
            capabilities=len(context.top_capabilities),
            ms_learn=len(context.ms_learn_refs),
            history=len(context.prior_fitments),
            sources=sources_available,
        )
        return context
