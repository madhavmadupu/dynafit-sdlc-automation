"""
infrastructure/vector_db/embedder.py
BAAI/bge-large-en-v1.5 embedding wrapper.
Singleton — loaded once at module import, never per-request.
Always use instruction prefix for requirement texts.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

import structlog

from core.config.settings import settings

log = structlog.get_logger()

INSTRUCTION_PREFIX = "Represent this D365 business requirement for retrieval: "
CAPABILITY_PREFIX = ""  # No special prefix for capability descriptions
EMBEDDING_DIM = 1024
MAX_BATCH_SIZE = 256


@lru_cache(maxsize=1)
def _load_model() -> object:
    """Load the embedding model once. Cached via lru_cache (singleton)."""
    from sentence_transformers import SentenceTransformer

    log.info("embedder.loading_model", model=settings.EMBEDDING_MODEL)
    model = SentenceTransformer(settings.EMBEDDING_MODEL)
    log.info("embedder.model_loaded", model=settings.EMBEDDING_MODEL, dim=EMBEDDING_DIM)
    return model


class BgeEmbedder:
    """
    Wrapper for BAAI/bge-large-en-v1.5 (1024-dim embeddings).

    ALWAYS use `embed_requirement()` for requirement texts — the instruction prefix
    significantly improves retrieval quality. Omitting the prefix degrades quality.

    Uses asyncio thread pool for CPU-bound inference (non-blocking for other coroutines).
    """

    @property
    def model(self) -> object:
        return _load_model()

    async def embed_requirement(self, text: str) -> list[float]:
        """
        Embed a single requirement text with the D365 instruction prefix.

        Args:
            text: Normalized requirement text.

        Returns:
            1024-dimensional embedding vector.
        """
        prefixed = f"{INSTRUCTION_PREFIX}{text}"
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.model.encode([prefixed], normalize_embeddings=True),  # type: ignore[attr-defined]
        )
        return result[0].tolist()

    async def embed_requirements_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Batch-embed requirement texts. Automatically splits into max 256-item batches.

        Args:
            texts: List of normalized requirement texts.

        Returns:
            List of 1024-dimensional embedding vectors, in same order as input.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[i : i + MAX_BATCH_SIZE]
            prefixed = [f"{INSTRUCTION_PREFIX}{t}" for t in batch]

            loop = asyncio.get_event_loop()
            batch_result = await loop.run_in_executor(
                None,
                lambda p=prefixed: self.model.encode(p, normalize_embeddings=True),  # type: ignore[attr-defined]
            )
            all_embeddings.extend([vec.tolist() for vec in batch_result])

        return all_embeddings

    async def embed_capability(self, text: str) -> list[float]:
        """
        Embed a D365 capability description (no instruction prefix needed).

        Args:
            text: Capability description text.

        Returns:
            1024-dimensional embedding vector.
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.model.encode([text], normalize_embeddings=True),  # type: ignore[attr-defined]
        )
        return result[0].tolist()

    async def health_check(self) -> bool:
        """Verify model is loaded and produces correct dimensionality."""
        try:
            test_vec = await self.embed_requirement("health check test")
            if len(test_vec) != EMBEDDING_DIM:
                log.error(
                    "embedder.health_check_failed",
                    expected_dim=EMBEDDING_DIM,
                    actual_dim=len(test_vec),
                )
                return False
            log.debug("embedder.health_check_ok", dim=EMBEDDING_DIM)
            return True
        except Exception as e:
            log.error("embedder.health_check_failed", error=str(e))
            return False


# Module-level singleton — import this everywhere
embedder = BgeEmbedder()
