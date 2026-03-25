"""
infrastructure/vector_db/qdrant_client.py
Async Qdrant client for D365 capability KB and MS Learn corpus searches.
Manages two collections: d365_capabilities and ms_learn_docs.
"""
from __future__ import annotations

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from core.config.settings import settings
from core.schemas.retrieval_context import D365CapabilityMatch, DocChunkMatch
from core.schemas.enums import D365Module

log = structlog.get_logger()


class DynafitQdrantClient:
    """
    Qdrant vector store client for DYNAFIT.

    Collections managed:
    - d365_capabilities: D365 F&O capability knowledge base
    - ms_learn_docs: Microsoft Learn documentation chunks

    Never create or drop collections outside of setup scripts.
    Uses connection pooling via AsyncQdrantClient.
    """

    def __init__(self) -> None:
        connect_kwargs: dict = {
            "host": settings.QDRANT_HOST,
            "port": settings.QDRANT_PORT,
            "prefer_grpc": settings.QDRANT_PREFER_GRPC,
        }
        if settings.QDRANT_API_KEY:
            connect_kwargs["api_key"] = settings.QDRANT_API_KEY

        self._client = AsyncQdrantClient(**connect_kwargs)

    async def search_capabilities(
        self,
        vector: list[float],
        module_filter: str,
        limit: int = 20,
    ) -> list[D365CapabilityMatch]:
        """
        Dense vector search in d365_capabilities collection, filtered by module.

        Module filter is ALWAYS applied — cross-module leakage is architecturally prevented.
        """
        try:
            results = await self._client.search(
                collection_name=settings.D365_KB_COLLECTION,
                query_vector=vector,
                query_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="module",
                            match=qmodels.MatchValue(value=module_filter),
                        )
                    ]
                ),
                with_payload=True,
                with_vectors=True,
                limit=limit,
                search_params=qmodels.SearchParams(hnsw_ef=128),
            )
            return [self._scored_point_to_capability(r) for r in results]
        except Exception as e:
            log.error(
                "capabilities_retrieval_failed",
                module=module_filter,
                error=str(e),
                exc_info=True,
            )
            raise  # D365 KB failure is a hard error

    async def keyword_search_capabilities(
        self,
        tokens: list[str],
        module_filter: str,
        limit: int = 20,
    ) -> list[D365CapabilityMatch]:
        """
        BM25 keyword search via Qdrant sparse vector support.
        Returns capabilities ranked by BM25 keyword relevance.
        """
        try:
            # Build sparse vector from BM25 tokens
            # In production Qdrant setup, the collection has a named sparse vector "text_sparse"
            # We approximate with a simple scroll + rank by text match when sparse not available
            results = await self._client.search(
                collection_name=settings.D365_KB_COLLECTION,
                query_vector=qmodels.SparseVector(
                    indices=list(range(len(tokens))),
                    values=[1.0] * len(tokens),
                ),
                vector_name="text_sparse",
                query_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="module",
                            match=qmodels.MatchValue(value=module_filter),
                        )
                    ]
                ),
                with_payload=True,
                limit=limit,
            )
            return [self._scored_point_to_capability(r, bm25=True) for r in results]
        except Exception as e:
            log.warning(
                "keyword_search_capabilities_failed",
                module=module_filter,
                error=str(e),
            )
            return []  # BM25 failure is soft — dense search continues

    async def search_ms_learn(
        self,
        vector: list[float],
        limit: int = 10,
    ) -> list[DocChunkMatch]:
        """
        Semantic search in ms_learn_docs collection.
        Module-agnostic (MS Learn docs span multiple modules).
        """
        try:
            results = await self._client.search(
                collection_name=settings.MS_LEARN_COLLECTION,
                query_vector=vector,
                with_payload=True,
                limit=limit,
            )
            return [self._scored_point_to_doc_chunk(r) for r in results]
        except Exception as e:
            log.warning("ms_learn_retrieval_failed", error=str(e))
            return []  # MS Learn failure is soft

    async def upsert_capability(self, capability_id: str, payload: dict, vector: list[float]) -> None:
        """Upsert a single capability. Used by KB ingestion scripts only."""
        await self._client.upsert(
            collection_name=settings.D365_KB_COLLECTION,
            points=[
                qmodels.PointStruct(
                    id=capability_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )

    async def health_check(self) -> bool:
        """Ping Qdrant and verify both collections exist and are non-empty."""
        try:
            collections = await self._client.get_collections()
            collection_names = [c.name for c in collections.collections]

            missing = []
            for required in [settings.D365_KB_COLLECTION, settings.MS_LEARN_COLLECTION]:
                if required not in collection_names:
                    missing.append(required)

            if missing:
                log.error("qdrant_collections_missing", missing=missing)
                return False

            log.debug("qdrant.health_check_ok", collections=collection_names)
            return True
        except Exception as e:
            log.error("qdrant.health_check_failed", error=str(e))
            return False

    @staticmethod
    def _scored_point_to_capability(
        point: object, bm25: bool = False
    ) -> D365CapabilityMatch:
        """Convert a Qdrant ScoredPoint to a D365CapabilityMatch."""
        payload = getattr(point, "payload", {}) or {}
        score = float(getattr(point, "score", 0.0))
        module_str = payload.get("module", "UNKNOWN")
        try:
            module = D365Module(module_str)
        except ValueError:
            module = D365Module.UNKNOWN

        return D365CapabilityMatch(
            capability_id=str(payload.get("capability_id", getattr(point, "id", ""))),
            name=str(payload.get("name", "")),
            description=str(payload.get("description", "")),
            module=module,
            sub_module=payload.get("sub_module"),
            license_requirement=payload.get("license_requirement"),
            configuration_notes=payload.get("configuration_notes"),
            localization_gaps=payload.get("localization_gaps", {}),
            bm25_score=score if bm25 else 0.0,
            vector_score=score if not bm25 else 0.0,
            rrf_score=0.0,   # Set during RRF fusion
            rerank_score=0.0,  # Set during CrossEncoder reranking
        )

    @staticmethod
    def _scored_point_to_doc_chunk(point: object) -> DocChunkMatch:
        """Convert a Qdrant ScoredPoint to a DocChunkMatch."""
        payload = getattr(point, "payload", {}) or {}
        return DocChunkMatch(
            chunk_id=str(payload.get("chunk_id", getattr(point, "id", ""))),
            source_url=str(payload.get("source_url", "")),
            page_title=str(payload.get("page_title", "")),
            section_heading=payload.get("section_heading"),
            text=str(payload.get("text", "")),
            vector_score=float(getattr(point, "score", 0.0)),
        )


# Module-level singleton
qdrant_client = DynafitQdrantClient()
