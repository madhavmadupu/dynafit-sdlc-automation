"""
infrastructure/vector_db/pgvector_client.py
PostgreSQL + pgvector client for historical fitment lookup and write-back.
Supports exact hash lookup and embedding similarity search.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.config.settings import settings
from core.schemas.enums import Verdict
from core.schemas.retrieval_context import HistoricalFitmentMatch

log = structlog.get_logger()


class PgVectorClient:
    """
    PostgreSQL + pgvector store for historical fitment decisions.

    Table: historical_fitments
    Lookups:
    1. Exact: atom_hash + module → O(1) using btree index
    2. Semantic: embedding similarity via pgvector <=> operator

    Write-back: Called from Phase 5 override_handler.py
    """

    def __init__(self) -> None:
        self._engine = create_async_engine(
            settings.POSTGRES_URL,
            pool_size=settings.POSTGRES_POOL_MIN,
            max_overflow=settings.POSTGRES_POOL_MAX - settings.POSTGRES_POOL_MIN,
            echo=False,
        )
        self._session_factory = sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def find_by_hash_or_similar(
        self,
        atom_hash: str,
        embedding: list[float],
        module: str,
        limit: int = 5,
    ) -> list[HistoricalFitmentMatch]:
        """
        Find historical fitments for an atom.
        Strategy: exact hash match first, fall back to embedding similarity.

        Args:
            atom_hash: SHA256 of normalized requirement text
            embedding: 1024-dim embedding vector for similarity fallback
            module: D365 module code (always scoped)
            limit: Max results to return

        Returns:
            List of HistoricalFitmentMatch objects, empty if none found.
        """
        try:
            async with self._session_factory() as session:
                # Try exact hash match first
                exact_result = await session.execute(
                    text("""
                        SELECT fitment_id, original_text, verdict, confidence, rationale,
                               wave_id, overridden_by_consultant, matched_capability,
                               1.0 AS similarity, true AS is_exact
                        FROM historical_fitments
                        WHERE atom_hash = :hash AND module = :module
                        LIMIT 1
                    """),
                    {"hash": atom_hash, "module": module},
                )
                rows = exact_result.fetchall()

                if not rows:
                    # Fall back to embedding similarity
                    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
                    sim_result = await session.execute(
                        text("""
                            SELECT fitment_id, original_text, verdict, confidence, rationale,
                                   wave_id, overridden_by_consultant, matched_capability,
                                   1 - (embedding <=> :vec::vector) AS similarity,
                                   false AS is_exact
                            FROM historical_fitments
                            WHERE module = :module
                              AND 1 - (embedding <=> :vec::vector) > :min_sim
                            ORDER BY similarity DESC
                            LIMIT :limit
                        """),
                        {
                            "vec": vec_str,
                            "module": module,
                            "min_sim": 0.75,
                            "limit": limit,
                        },
                    )
                    rows = sim_result.fetchall()

                return [
                    HistoricalFitmentMatch(
                        fitment_id=str(r.fitment_id),
                        original_text=str(r.original_text),
                        verdict=Verdict(r.verdict),
                        confidence=float(r.confidence),
                        rationale=str(r.rationale),
                        wave_id=str(r.wave_id),
                        overridden_by_consultant=bool(r.overridden_by_consultant),
                        matched_capability=r.matched_capability,
                        similarity_to_current=float(r.similarity),
                        is_exact_match=bool(r.is_exact),
                    )
                    for r in rows
                ]
        except Exception as e:
            log.warning(
                "historical_retrieval_failed",
                atom_hash=atom_hash,
                module=module,
                error=str(e),
            )
            return []  # Historical failure is soft — pipeline continues without history

    async def write_fitment(
        self,
        *,
        atom_hash: str,
        original_text: str,
        module: str,
        verdict: str,
        confidence: float,
        rationale: str,
        matched_capability: str | None,
        wave_id: str,
        embedding: list[float],
        overridden_by_consultant: bool = False,
    ) -> None:
        """
        Write a new historical fitment decision.
        Called from Phase 5 override_handler after consultant review.
        """
        try:
            vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
            async with self._session_factory() as session:
                await session.execute(
                    text("""
                        INSERT INTO historical_fitments
                            (atom_hash, original_text, module, verdict, confidence,
                             rationale, matched_capability, wave_id, embedding,
                             overridden_by_consultant)
                        VALUES
                            (:atom_hash, :original_text, :module, :verdict, :confidence,
                             :rationale, :matched_capability, :wave_id, :vec::vector,
                             :overridden)
                        ON CONFLICT (atom_hash, module) DO UPDATE SET
                            verdict = EXCLUDED.verdict,
                            confidence = EXCLUDED.confidence,
                            rationale = EXCLUDED.rationale,
                            overridden_by_consultant = EXCLUDED.overridden_by_consultant
                    """),
                    {
                        "atom_hash": atom_hash,
                        "original_text": original_text,
                        "module": module,
                        "verdict": verdict,
                        "confidence": confidence,
                        "rationale": rationale,
                        "matched_capability": matched_capability,
                        "wave_id": wave_id,
                        "vec": vec_str,
                        "overridden": overridden_by_consultant,
                    },
                )
                await session.commit()
                log.info(
                    "historical_fitment_written",
                    atom_hash=atom_hash,
                    module=module,
                    verdict=verdict,
                )
        except Exception as e:
            log.error(
                "historical_fitment_write_failed",
                atom_hash=atom_hash,
                error=str(e),
                exc_info=True,
            )
            raise

    async def health_check(self) -> bool:
        """Verify PostgreSQL connection and pgvector extension."""
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
                # Check pgvector extension
                result = await session.execute(
                    text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                )
                if not result.fetchone():
                    log.error("pgvector_extension_missing")
                    return False
            log.debug("pgvector.health_check_ok")
            return True
        except Exception as e:
            log.error("pgvector.health_check_failed", error=str(e))
            return False


pgvector_client = PgVectorClient()
