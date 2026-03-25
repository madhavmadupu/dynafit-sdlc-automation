"""
scripts/setup_qdrant.py
Idempotent collection creation for Qdrant (D365 Capabilities & MS Learn).
Defines payload indices for exact and full-text matching.
"""
from __future__ import annotations

import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PayloadSchemaType, TextIndexParams, TextIndexType, TokenizerType

from core.config.settings import settings

log = structlog.get_logger()


async def setup_qdrant() -> None:
    uri = f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}"
    api_key = settings.QDRANT_API_KEY
    if not uri:
        log.error("setup.missing_qdrant_uri")
        sys.exit(1)

    log.info("setup.connecting_qdrant", uri=uri)
    client = AsyncQdrantClient(url=uri, api_key=api_key)

    try:
        collections = await client.get_collections()
        existing = [c.name for c in collections.collections]
    except Exception as e:
        log.error("setup.qdrant_connection_failed", error=str(e))
        sys.exit(1)

    # 1. D365 Capabilities Hybrid Collection
    cap_coll = settings.D365_KB_COLLECTION
    if cap_coll not in existing:
        log.info(f"setup.creating_collection", collection=cap_coll)
        await client.create_collection(
            collection_name=cap_coll,
            vectors_config=VectorParams(
                size=1024,  # BAAI/bge-large-en-v1.5 dim
                distance=Distance.COSINE,
            ),
        )

        # Exact match index for module filtering
        await client.create_payload_index(
            collection_name=cap_coll,
            field_name="module",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Full-text BM25 index for sparse hybrid search
        await client.create_payload_index(
            collection_name=cap_coll,
            field_name="description",
            field_schema=TextIndexParams(
                type=TextIndexType.TEXT,
                tokenizer=TokenizerType.WORD,
                min_token_len=3,
                max_token_len=15,
                lowercase=True,
            ),
        )
    else:
        log.info(f"setup.collection_exists", collection=cap_coll)

    # 2. MS Learn Documents Collection (Dense Only)
    msl_coll = settings.MS_LEARN_COLLECTION
    if msl_coll not in existing:
        log.info(f"setup.creating_collection", collection=msl_coll)
        await client.create_collection(
            collection_name=msl_coll,
            vectors_config=VectorParams(
                size=1024,
                distance=Distance.COSINE,
            ),
        )
    else:
        log.info(f"setup.collection_exists", collection=msl_coll)

    log.info("setup.qdrant_setup_complete")


if __name__ == "__main__":
    import asyncio
    asyncio.run(setup_qdrant())
