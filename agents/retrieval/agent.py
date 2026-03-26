"""
agents/retrieval/agent.py
Phase 2 — Knowledge Retrieval Agent (RAG) LangGraph node.
Reads atoms, writes retrieval_contexts with grounded D365 evidence.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from agents.retrieval.context_assembler import ContextAssembler
from agents.retrieval.parallel_retriever import ParallelRetriever
from agents.retrieval.query_builder import QueryBuilder
from agents.retrieval.reranker import CrossEncoderReranker
from agents.retrieval.rrf_fusion import RRFFusion
from core.config.settings import settings
from core.schemas.requirement_atom import RequirementAtom
from core.schemas.retrieval_context import RetrievalContext

log = structlog.get_logger()
PHASE = "retrieval"


async def run(state: dict[str, Any]) -> dict[str, Any]:
    """
    Phase 2 LangGraph node: Knowledge Retrieval Agent.

    Reads: state["atoms"], state["run_id"], state["kb_version"]
    Writes: state["retrieval_contexts"], state["retrieval_errors"]

    All atoms are processed in parallel via asyncio.gather().
    D365 KB failure → atom marked as error (hard failure).
    MS Learn / history failure → soft (empty, pipeline continues).
    Redis cache is checked first — cache hits skip all retrieval.
    """
    run_id: str = state["run_id"]
    atoms: list[RequirementAtom] = state.get("atoms", [])
    kb_version: str = state.get("kb_version", settings.KB_VERSION)

    log.info(f"{PHASE}.start", run_id=run_id, atom_count=len(atoms))

    # Instantiate components (singletons could be used but instantiating for testability)
    query_builder = QueryBuilder()
    retriever = ParallelRetriever()
    fuser = RRFFusion()
    reranker = CrossEncoderReranker()
    assembler = ContextAssembler()

    # Process all atoms in parallel
    tasks = [
        _retrieve_single(
            atom=atom,
            kb_version=kb_version,
            query_builder=query_builder,
            retriever=retriever,
            fuser=fuser,
            reranker=reranker,
            assembler=assembler,
            run_id=run_id,
        )
        for atom in atoms
    ]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    contexts: list[RetrievalContext] = []
    errors: list[dict] = []

    for atom, outcome in zip(atoms, outcomes, strict=False):
        if isinstance(outcome, Exception):
            log.error(
                f"{PHASE}.atom_failed",
                run_id=run_id,
                atom_id=str(atom.id),
                error=str(outcome),
                exc_info=False,
            )
            errors.append(
                {
                    "phase": PHASE,
                    "atom_id": str(atom.id),
                    "error": str(outcome),
                }
            )
        else:
            contexts.append(outcome)

    log.info(
        f"{PHASE}.complete",
        run_id=run_id,
        contexts=len(contexts),
        errors=len(errors),
        cache_hits=sum(1 for c in contexts if c.cache_hit),
    )

    return {
        "retrieval_contexts": contexts,
        "retrieval_errors": errors,
        "pipeline_errors": state.get("pipeline_errors", []) + errors,
    }


async def _retrieve_single(
    *,
    atom: RequirementAtom,
    kb_version: str,
    query_builder: QueryBuilder,
    retriever: ParallelRetriever,
    fuser: RRFFusion,
    reranker: CrossEncoderReranker,
    assembler: ContextAssembler,
    run_id: str,
) -> RetrievalContext:
    """Process retrieval for a single atom with cache check."""
    # Check Redis cache first
    cached = await assembler.get_cached(atom, kb_version)
    if cached:
        log.debug(f"{PHASE}.cache_hit", atom_id=str(atom.id))
        return cached

    # Build multi-modal query
    query = await query_builder.build(atom)

    # Fan out to all 3 sources
    raw = await retriever.retrieve_all(query=query, module=atom.module.value)

    # Fuse vector + BM25 results using RRF
    fused_caps = fuser.fuse_capability_lists(
        dense_results=raw["capabilities"],
        bm25_results=raw.get("capabilities_bm25", []),
        top_k=20,  # top-20 before reranking
    )

    # CrossEncoder rerank to top-5
    reranked = await reranker.rerank(
        requirement_text=atom.text,
        candidates=fused_caps,
        top_k=settings.RERANKER_TOP_K,
    )

    # Assemble final context
    context = assembler.assemble(
        atom=atom,
        top_capabilities=reranked,
        ms_learn_refs=raw["ms_learn"],
        prior_fitments=raw["historical"],
        sources_available=raw["sources_available"],
        cache_hit=False,
    )

    # Write to Redis cache
    await assembler.cache(context, kb_version)

    log.info(
        f"{PHASE}.success",
        run_id=run_id,
        atom_id=str(atom.id),
        capabilities=len(context.top_capabilities),
        history=len(context.prior_fitments),
    )
    return context
