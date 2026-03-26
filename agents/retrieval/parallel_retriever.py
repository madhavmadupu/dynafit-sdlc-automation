"""
agents/retrieval/parallel_retriever.py
Fans out retrieval to all 3 knowledge sources simultaneously via asyncio.gather().
Sequential retrieval is a performance violation — always parallel.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from agents.retrieval.query_builder import RetrievalQuery
from core.config.settings import settings
from core.schemas.retrieval_context import (
    D365CapabilityMatch,
    DocChunkMatch,
    HistoricalFitmentMatch,
)
from infrastructure.vector_db.pgvector_client import pgvector_client
from infrastructure.vector_db.qdrant_client import qdrant_client

log = structlog.get_logger()


class ParallelRetriever:
    """
    Fans out to all 3 knowledge sources in parallel:
    1. D365 Capability KB (Qdrant) — hybrid: vector + BM25
    2. MS Learn Corpus (Qdrant) — dense vector only
    3. Historical Fitments (pgvector) — exact hash + similarity fallback

    If D365 KB fails — hard error (raises). Quality of output is unacceptable without it.
    If MS Learn fails — soft warning (empty list returned, pipeline continues).
    If pgvector fails — soft warning (empty list returned, pipeline continues).
    """

    async def retrieve_all(self, query: RetrievalQuery, module: str) -> dict[str, Any]:
        """
        Fan out all 3 retrieval sources simultaneously.

        Returns:
            Dict with keys:
            - "capabilities": list[D365CapabilityMatch] (vector results)
            - "capabilities_bm25": list[D365CapabilityMatch] (BM25 results)
            - "ms_learn": list[DocChunkMatch]
            - "historical": list[HistoricalFitmentMatch]
            - "sources_available": list[str] of source names that responded
        """
        sources_available: list[str] = []

        # Run all 3 sources in parallel
        cap_task = asyncio.create_task(self._retrieve_capabilities_dense(query, module))
        bm25_task = asyncio.create_task(self._retrieve_capabilities_bm25(query, module))
        ms_learn_task = asyncio.create_task(self._retrieve_ms_learn(query))
        history_task = asyncio.create_task(self._retrieve_historical(query, module))

        cap_result, bm25_result, ms_learn_result, history_result = await asyncio.gather(
            cap_task,
            bm25_task,
            ms_learn_task,
            history_task,
            return_exceptions=True,
        )

        # D365 KB is a hard dependency — raise on failure
        if isinstance(cap_result, Exception):
            log.error(
                "capabilities_retrieval_failed",
                atom_id=query.atom_id,
                error=str(cap_result),
            )
            raise cap_result  # Re-raise — Phase 2 will mark atom as ERROR

        capabilities = cap_result
        sources_available.append("d365_kb")

        # BM25 soft failure
        if isinstance(bm25_result, Exception):
            log.warning("bm25_retrieval_soft_failed", atom_id=query.atom_id, error=str(bm25_result))
            bm25_caps: list[D365CapabilityMatch] = []
        else:
            bm25_caps = bm25_result

        # MS Learn soft failure
        if isinstance(ms_learn_result, Exception):
            log.warning(
                "ms_learn_retrieval_failed",
                atom_id=query.atom_id,
                error=str(ms_learn_result),
            )
            ms_learn_docs: list[DocChunkMatch] = []
        else:
            ms_learn_docs = ms_learn_result
            if ms_learn_docs:
                sources_available.append("ms_learn")

        # Historical soft failure
        if isinstance(history_result, Exception):
            log.warning(
                "historical_retrieval_failed",
                atom_id=query.atom_id,
                error=str(history_result),
            )
            historical: list[HistoricalFitmentMatch] = []
        else:
            historical = history_result
            if historical:
                sources_available.append("history")

        return {
            "capabilities": capabilities,
            "capabilities_bm25": bm25_caps,
            "ms_learn": ms_learn_docs,
            "historical": historical,
            "sources_available": sources_available,
        }

    async def _retrieve_capabilities_dense(
        self, query: RetrievalQuery, module: str
    ) -> list[D365CapabilityMatch]:
        """Dense vector search in D365 capability KB."""
        return await qdrant_client.search_capabilities(
            vector=query.dense_vector,
            module_filter=module,
            limit=settings.RETRIEVAL_TOP_K_SOURCES,
        )

    async def _retrieve_capabilities_bm25(
        self, query: RetrievalQuery, module: str
    ) -> list[D365CapabilityMatch]:
        """BM25 keyword search in D365 capability KB."""
        return await qdrant_client.keyword_search_capabilities(
            tokens=query.sparse_tokens,
            module_filter=module,
            limit=settings.RETRIEVAL_TOP_K_SOURCES,
        )

    async def _retrieve_ms_learn(self, query: RetrievalQuery) -> list[DocChunkMatch]:
        """Semantic search in MS Learn documentation corpus."""
        return await qdrant_client.search_ms_learn(
            vector=query.dense_vector,
            limit=settings.MS_LEARN_TOP_K,
        )

    async def _retrieve_historical(
        self, query: RetrievalQuery, module: str
    ) -> list[HistoricalFitmentMatch]:
        """Exact hash + semantic similarity search in historical fitments."""
        return await pgvector_client.find_by_hash_or_similar(
            atom_hash=query.atom_hash,
            embedding=query.dense_vector,
            module=module,
            limit=5,
        )
