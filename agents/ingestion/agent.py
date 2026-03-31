"""
agents/ingestion/agent.py
Phase 1 — Ingestion Agent LangGraph node.
Transforms raw document files into structured RequirementAtom objects.
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.ingestion.doc_parser import parse_document
from agents.ingestion.normalizer import normalize_atoms
from agents.ingestion.req_extractor import extract_atoms_from_chunks
from agents.ingestion.semantic_chunker import SemanticChunkerConfig, semantic_chunk
from agents.ingestion.validator import validate_atoms
from core.config.settings import settings

log = structlog.get_logger()
PHASE = "ingestion"


async def run(state: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 1 LangGraph node: Ingestion Agent.

    Reads: state["source_files"], state["run_id"]
    Writes: state["atoms"], state["rejected_atoms"], state["ingestion_errors"]

    Processing:
    1. Parse each source file into RawChunks
    2. Extract PartialAtoms via LLM (batched, with retry logic for rejections)
    3. Normalize (dedup + term align)
    4. Validate against schema (hard reject / soft flag)
    """
    run_id: str = state["run_id"]
    source_files: list[str] = state.get("source_files", [])

    log.info(f"{PHASE}.start", run_id=run_id, file_count=len(source_files))

    all_partial_atoms = []
    ingestion_errors: list[dict] = []

    # ── Phase 1a: Parse documents ─────────────────────────────────────────────
    for file_path in source_files:
        try:
            chunks = parse_document(file_path)
            log.info(
                f"{PHASE}.parsed",
                run_id=run_id,
                file=file_path,
                chunks=len(chunks),
            )

            # ── Phase 1a.5: Semantic chunking ────────────────────────────────
            sc_config = SemanticChunkerConfig(
                similarity_threshold=settings.SEMANTIC_CHUNK_THRESHOLD,
                min_sentences_to_chunk=settings.SEMANTIC_CHUNK_MIN_SENTENCES,
            )
            chunks = await semantic_chunk(chunks, sc_config)
            log.info(
                f"{PHASE}.semantic_chunked",
                run_id=run_id,
                file=file_path,
                chunks=len(chunks),
            )

            # ── Phase 1b: Extract atoms via LLM ──────────────────────────────
            partial_atoms = await extract_atoms_from_chunks(
                chunks=chunks,
                run_id=run_id,
            )
            all_partial_atoms.extend(partial_atoms)

        except Exception as e:
            log.error(
                f"{PHASE}.file_failed",
                run_id=run_id,
                file=file_path,
                error=str(e),
                exc_info=True,
            )
            ingestion_errors.append(
                {
                    "phase": PHASE,
                    "file": file_path,
                    "error": str(e),
                }
            )

    # ── Phase 1c: Normalize ───────────────────────────────────────────────────
    normalized = normalize_atoms(all_partial_atoms)

    # ── Phase 1d: Validate with retry for rejections ─────────────────────────
    valid_atoms, rejected_atoms = validate_atoms(normalized)

    # Retry rejected atoms (max MAX_INGESTION_RETRIES times)
    if rejected_atoms:
        for retry_attempt in range(1, settings.MAX_INGESTION_RETRIES + 1):
            retry_rejected = [
                r for r in rejected_atoms if "Schema validation" not in r.rejection_reason
            ]
            if not retry_rejected:
                break

            log.info(
                f"{PHASE}.retrying_rejected",
                run_id=run_id,
                count=len(retry_rejected),
                attempt=retry_attempt,
            )

            retry_results = []
            for rejected in retry_rejected:
                # Re-extract with rejection reason in prompt
                from agents.ingestion.doc_parser import RawChunk

                mock_chunk = RawChunk(
                    text=rejected.raw_text,
                    source_ref=rejected.source_ref,
                    source_file=rejected.source_file,
                )
                re_extracted = await extract_atoms_from_chunks(
                    chunks=[mock_chunk],
                    run_id=run_id,
                    rejection_reason=rejected.rejection_reason,
                    retry_count=retry_attempt,
                )
                retry_results.extend(re_extracted)

            if retry_results:
                retry_normalized = normalize_atoms(retry_results)
                retry_valid, retry_still_rejected = validate_atoms(retry_normalized)
                valid_atoms.extend(retry_valid)
                rejected_atoms = retry_still_rejected

    log.info(
        f"{PHASE}.complete",
        run_id=run_id,
        valid_atoms=len(valid_atoms),
        rejected_atoms=len(rejected_atoms),
        errors=len(ingestion_errors),
        needs_review=sum(1 for a in valid_atoms if a.needs_review),
    )

    return {
        "atoms": valid_atoms,
        "rejected_atoms": rejected_atoms,
        "ingestion_errors": ingestion_errors,
        "pipeline_errors": state.get("pipeline_errors", []) + ingestion_errors,
    }
