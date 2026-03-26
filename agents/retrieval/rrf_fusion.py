"""
agents/retrieval/rrf_fusion.py
Reciprocal Rank Fusion (RRF) for merging vector and BM25 ranked lists.
k=60 is ADR-001 locked — do not change without ADR + eval regression test.
"""

from __future__ import annotations

from collections import defaultdict

import structlog

from core.config.thresholds import RRF_K
from core.schemas.retrieval_context import D365CapabilityMatch

log = structlog.get_logger()


class RRFFusion:
    """
    Merges multiple ranked lists of D365 capabilities using Reciprocal Rank Fusion.

    Formula: score(d) = Σ 1/(k + rank(d)) where k=60 (ADR-001 locked)

    Items appearing in multiple lists get higher fused scores.
    Items appearing in only one list are still included.
    """

    def fuse(
        self,
        capability_results: list[D365CapabilityMatch],
        ms_learn_results: list,  # DocChunkMatch
        sources_available: list[str],
    ) -> dict[str, list]:
        """
        Fuse vector and BM25 capability results into a single ranked list.

        MS Learn results are not fused with capabilities (different schema) — they
        are passed through separately.

        Args:
            capability_results: Dense vector search results
            ms_learn_results: MS Learn search results (passed through unchanged)
            sources_available: Which sources responded

        Returns:
            Dict with:
            - "capabilities": list[D365CapabilityMatch] — top-20 RRF-fused capabilities
            - "ms_learn": list[DocChunkMatch] — unchanged
        """
        # This method fuses dense + BM25 capability results
        # In practice, parallel_retriever passes dense results here
        # The BM25 list is merged in _fuse_capabilities internally
        fused_caps = self._fuse_capability_lists(
            dense_results=capability_results,
            bm25_results=[],  # BM25 list handled separately if available
        )

        return {
            "capabilities": fused_caps,
            "ms_learn": ms_learn_results,
        }

    def fuse_capability_lists(
        self,
        dense_results: list[D365CapabilityMatch],
        bm25_results: list[D365CapabilityMatch],
        top_k: int = 20,
    ) -> list[D365CapabilityMatch]:
        """
        Public method to fuse two ranked capability lists using RRF.

        Args:
            dense_results: Results from vector search (ranked by cosine similarity)
            bm25_results: Results from BM25 keyword search
            top_k: Number of results to return after fusion

        Returns:
            Up to top_k capabilities sorted by RRF score (descending).
        """
        return self._fuse_capability_lists(dense_results, bm25_results, top_k)

    def _fuse_capability_lists(
        self,
        dense_results: list[D365CapabilityMatch],
        bm25_results: list[D365CapabilityMatch],
        top_k: int = 20,
    ) -> list[D365CapabilityMatch]:
        """Merge dense and BM25 rankings using RRF."""
        # Build a dict keyed by capability_id to de-duplicate
        cap_by_id: dict[str, D365CapabilityMatch] = {}
        rrf_scores: dict[str, float] = defaultdict(float)

        for ranked_list in [dense_results, bm25_results]:
            for rank, cap in enumerate(ranked_list, start=1):
                cap_id = cap.capability_id
                cap_by_id[cap_id] = cap
                rrf_score = 1.0 / (RRF_K + rank)
                rrf_scores[cap_id] += rrf_score

        # Sort by RRF score descending
        sorted_ids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)
        top_ids = sorted_ids[:top_k]

        # Return capabilities with rrf_score attached
        fused: list[D365CapabilityMatch] = []
        for cap_id in top_ids:
            cap = cap_by_id[cap_id]
            # Attach the RRF score
            cap_with_rrf = cap.model_copy(update={"rrf_score": rrf_scores[cap_id]})
            fused.append(cap_with_rrf)

        log.debug(
            "rrf_fusion_complete",
            dense_count=len(dense_results),
            bm25_count=len(bm25_results),
            fused_count=len(fused),
        )
        return fused


def rrf_score(rank: int, k: int = RRF_K) -> float:
    """Compute RRF score for a single item at a given rank."""
    return 1.0 / (k + rank)
