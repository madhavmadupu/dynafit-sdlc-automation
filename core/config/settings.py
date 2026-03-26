"""
core/config/settings.py
Environment-driven configuration for DYNAFIT.
All external configuration accessed through this singleton — never use os.environ directly.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DynafitSettings(BaseSettings):
    """
    Pydantic Settings loaded from environment variables / .env file.
    Singleton — import `settings` everywhere.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────────────────────
    CLASSIFICATION_MODEL: str = Field(
        default="claude-sonnet-4-6",
        description="Anthropic model for Phase 4 classification (chain-of-thought)",
    )
    INGESTION_MODEL: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Anthropic model for Phase 1 requirement extraction (high-volume, lower cost)",
    )
    LLM_MAX_RETRIES: int = Field(
        default=3, description="Max retry attempts for LLM calls (tenacity)"
    )
    CLASSIFICATION_MAX_TOKENS: int = Field(
        default=1500, description="Max completion tokens for classification calls"
    )
    INGESTION_MAX_TOKENS: int = Field(
        default=4000, description="Max completion tokens for ingestion/extraction calls"
    )
    LLM_TEMPERATURE: float = Field(
        default=0.1, description="Temperature for LLM calls (low = deterministic)"
    )

    # ── Cost Guard ───────────────────────────────────────────────────────────
    MAX_LLM_COST_USD_PER_RUN: float = Field(
        default=5.00,
        description="Hard cap on LLM spend per pipeline run. Abort Phase 4 if exceeded.",
    )

    # ── Anthropic Auth ───────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = Field(description="Anthropic API key — NEVER log this value")

    # ── LangSmith Tracing (Optional) ─────────────────────────────────────────
    LANGCHAIN_API_KEY: str | None = Field(
        default=None, description="Set to enable LangSmith traces for all LLM calls"
    )
    LANGCHAIN_PROJECT: str = Field(
        default="dynafit", description="LangSmith project name for trace grouping"
    )

    # ── Vector Database (Qdrant) ─────────────────────────────────────────────
    QDRANT_HOST: str = Field(default="localhost")
    QDRANT_PORT: int = Field(default=6333)
    QDRANT_GRPC_PORT: int = Field(default=6334)
    QDRANT_PREFER_GRPC: bool = Field(
        default=False, description="Use gRPC for Qdrant if True (faster for large vectors)"
    )
    QDRANT_API_KEY: str | None = Field(
        default=None, description="Qdrant API key (required for Qdrant Cloud)"
    )
    D365_KB_COLLECTION: str = Field(
        default="d365_capabilities", description="Qdrant collection for D365 capability KB"
    )
    MS_LEARN_COLLECTION: str = Field(
        default="ms_learn_docs", description="Qdrant collection for MS Learn corpus"
    )

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    POSTGRES_URL: str = Field(
        default="postgresql+asyncpg://dynafit:password@localhost:5432/dynafit",
        description="Async SQLAlchemy connection string for PostgreSQL + pgvector",
    )
    POSTGRES_POOL_MIN: int = Field(default=5)
    POSTGRES_POOL_MAX: int = Field(default=20)

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for retrieval cache and Celery broker",
    )
    RETRIEVAL_CACHE_TTL_SEC: int = Field(
        default=86400, description="RetrievalContext cache TTL in seconds (24 hours)"
    )

    # ── Pipeline Behaviour ────────────────────────────────────────────────────
    BATCH_SIZE: int = Field(default=50, description="Number of requirements per processing batch")
    MAX_INGESTION_RETRIES: int = Field(
        default=2, description="Max re-extraction retries for rejected atoms"
    )
    KB_VERSION: str = Field(
        default="v1.0.0",
        description="Knowledge base version — bump after KB re-ingestion to invalidate cache",
    )

    # ── Retrieval ─────────────────────────────────────────────────────────────
    RETRIEVAL_TOP_K_SOURCES: int = Field(
        default=20, description="Top-K per source before RRF fusion"
    )
    RERANKER_TOP_K: int = Field(default=5, description="Final top-K after CrossEncoder reranking")
    MS_LEARN_TOP_K: int = Field(default=10, description="Top-K from MS Learn before RRF")
    EMBEDDING_MODEL: str = Field(
        default="BAAI/bge-large-en-v1.5", description="Embedding model for requirement vectors"
    )
    EMBEDDING_DIM: int = Field(default=1024)
    RERANKER_MODEL: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="CrossEncoder model for capability reranking",
    )

    # ── API ───────────────────────────────────────────────────────────────────
    API_KEY: str = Field(
        default="dev-api-key-change-me",
        description="API key for FastAPI endpoint authentication",
    )
    API_RATE_LIMIT_PER_HOUR: int = Field(
        default=10, description="Max API requests per hour per API key"
    )
    UPLOAD_DIR: str = Field(
        default="/tmp/dynafit/uploads",
        description="Directory for uploaded BRD files",
    )
    OUTPUT_DIR: str = Field(
        default="/tmp/dynafit/outputs",
        description="Directory for generated fitment_matrix.xlsx files",
    )

    # ── Observability ──────────────────────────────────────────────────────────
    METRICS_PORT: int = Field(default=9090, description="Prometheus metrics exposure port")
    LOG_LEVEL: str = Field(default="INFO")


settings = DynafitSettings()  # Singleton — import this everywhere, never instantiate again
