"""
agents/retrieval/query_builder.py
Transforms RequirementAtom objects into multi-modal retrieval queries.
Produces dense vectors, BM25 sparse tokens, and module-scoped SQL filters.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from core.schemas.requirement_atom import RequirementAtom
from infrastructure.vector_db.embedder import embedder

log = structlog.get_logger()

# D365-specific stopwords to exclude from BM25 tokenization
D365_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "system",
    "user",
    "must",
    "shall",
    "should",
    "will",
    "would",
    "can",
    "may",
    "might",
    "need",
    "needs",
    "have",
    "has",
    "had",
    "do",
    "does",
    "allow",
    "enable",
    "support",
    "provide",
    "ensure",
    "include",
    "access",
    "ability",
    "function",
    "functionality",
    "feature",
    "capability",
}


@dataclass
class RetrievalQuery:
    """All query forms needed for the hybrid retrieval pipeline."""

    atom_id: str
    atom_hash: str
    dense_vector: list[float]  # bge-large-en-v1.5 embedding
    sparse_tokens: list[str]  # BM25 tokens (lowercased, no stopwords)
    module_filter: str  # D365 module code for Qdrant filter
    country_filter: str | None  # Optional country code filter


class QueryBuilder:
    """
    Builds RetrievalQuery objects from RequirementAtom inputs.

    Dense: BAAI/bge-large-en-v1.5 with D365 instruction prefix
    Sparse: BM25 tokenization via rank_bm25 tokenizer
    Filter: Always module-scoped; optionally country-scoped
    """

    async def build(self, atom: RequirementAtom) -> RetrievalQuery:
        """
        Build the full retrieval query for a single RequirementAtom.

        Args:
            atom: A validated RequirementAtom from Phase 1.

        Returns:
            RetrievalQuery with all query modalities populated.
        """
        # Dense embedding with instruction prefix
        dense_vector = await embedder.embed_requirement(atom.text)

        # BM25 sparse tokens
        sparse_tokens = self._tokenize(atom.text)

        log.debug(
            "query_builder.built",
            atom_id=str(atom.id),
            module=atom.module.value,
            token_count=len(sparse_tokens),
        )

        return RetrievalQuery(
            atom_id=str(atom.id),
            atom_hash=atom.atom_hash,
            dense_vector=dense_vector,
            sparse_tokens=sparse_tokens,
            module_filter=atom.module.value,
            country_filter=atom.country,
        )

    def _tokenize(self, text: str) -> list[str]:
        """
        BM25-style tokenization: lowercase, split on non-alpha, remove stopwords.
        """
        import re

        words = re.split(r"[^a-zA-Z0-9]+", text.lower())
        return [w for w in words if w and w not in D365_STOPWORDS and len(w) > 2]
