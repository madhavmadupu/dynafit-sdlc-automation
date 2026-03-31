"""
agents/ingestion/semantic_chunker.py
Embedding-based semantic chunking for RawChunk objects.

Splits multi-sentence RawChunks at semantic boundaries by:
1. Sentence tokenization (spaCy)
2. Embedding each sentence (BGE model)
3. Detecting cosine similarity drops between consecutive sentences
4. Grouping sentences into semantically coherent chunks

This runs BETWEEN doc_parser (Phase 1a) and req_extractor (Phase 1b),
producing tighter semantic units that reduce LLM atomization work.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np
import structlog

from agents.ingestion.doc_parser import RawChunk
from core.config.settings import settings

log = structlog.get_logger()

# ── Defaults ────────────────────────────────────────────────────────────────
DEFAULT_SIMILARITY_THRESHOLD = 0.75  # Split when cosine similarity drops below this
MIN_SENTENCES_TO_CHUNK = 3  # Don't bother splitting chunks with fewer sentences
MIN_CHUNK_LENGTH = 10  # Skip trivially short results


@dataclass
class SemanticChunkerConfig:
    """Tuneable parameters for semantic chunking."""

    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    min_sentences_to_chunk: int = MIN_SENTENCES_TO_CHUNK
    min_chunk_length: int = MIN_CHUNK_LENGTH


# ── spaCy singleton ─────────────────────────────────────────────────────────
_nlp = None


def _get_nlp():
    """Load spaCy model once. Only needs sentencizer, not full NER pipeline."""
    global _nlp
    if _nlp is None:
        import spacy

        try:
            _nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
        except OSError:
            # Fallback: blank model with just sentencizer
            log.warning("semantic_chunker.spacy_model_missing, using blank sentencizer")
            _nlp = spacy.blank("en")
            _nlp.add_pipe("sentencizer")
    return _nlp


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using spaCy."""
    nlp = _get_nlp()
    doc = nlp(text)
    return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors. Assumes normalized vectors from BGE."""
    dot = np.dot(a, b)
    # BGE outputs are already L2-normalized, but guard against edge cases
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _find_split_points(
    embeddings: np.ndarray,
    threshold: float,
) -> list[int]:
    """
    Find indices where semantic similarity drops below threshold.

    Returns list of split-point indices. A split at index i means
    sentences[0:i] form one group and sentences[i:] start the next.
    """
    if len(embeddings) < 2:
        return []

    split_points: list[int] = []
    for i in range(len(embeddings) - 1):
        sim = _cosine_similarity(embeddings[i], embeddings[i + 1])
        if sim < threshold:
            split_points.append(i + 1)

    return split_points


def _group_sentences(
    sentences: list[str],
    split_points: list[int],
) -> list[str]:
    """Group sentences into chunks based on split points."""
    if not split_points:
        return [" ".join(sentences)]

    groups: list[str] = []
    prev = 0
    for sp in split_points:
        group_text = " ".join(sentences[prev:sp]).strip()
        if group_text:
            groups.append(group_text)
        prev = sp

    # Last group
    last_group = " ".join(sentences[prev:]).strip()
    if last_group:
        groups.append(last_group)

    return groups


async def _embed_sentences(sentences: list[str]) -> np.ndarray:
    """Embed a batch of sentences using the BGE model (via thread pool)."""
    from infrastructure.vector_db.embedder import embedder

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: embedder.model.encode(sentences, normalize_embeddings=True),
    )
    return np.array(result)


async def semantic_chunk(
    chunks: list[RawChunk],
    config: SemanticChunkerConfig | None = None,
) -> list[RawChunk]:
    """
    Re-split RawChunks at semantic boundaries.

    Chunks with fewer than `min_sentences_to_chunk` sentences pass through unchanged.
    Multi-sentence chunks are split where cosine similarity between consecutive
    sentence embeddings drops below `similarity_threshold`.

    Args:
        chunks: RawChunks from doc_parser.
        config: Optional tuning parameters.

    Returns:
        New list of RawChunks, potentially more numerous but semantically tighter.
    """
    if not chunks:
        return []

    cfg = config or SemanticChunkerConfig()
    output: list[RawChunk] = []

    # Collect all sentences that need embedding (batch for efficiency)
    chunk_sentences: list[tuple[int, list[str]]] = []  # (chunk_idx, sentences)
    all_sentences: list[str] = []

    for i, chunk in enumerate(chunks):
        sentences = _split_sentences(chunk.text)
        if len(sentences) < cfg.min_sentences_to_chunk:
            # Pass through unchanged
            output.append(chunk)
        else:
            chunk_sentences.append((i, sentences))
            all_sentences.extend(sentences)

    if not all_sentences:
        log.info(
            "semantic_chunker.no_splits_needed",
            total_chunks=len(chunks),
            passed_through=len(output),
        )
        return output

    # Batch-embed all sentences at once
    all_embeddings = await _embed_sentences(all_sentences)

    # Map embeddings back to their chunk groups
    embed_offset = 0
    split_results: list[tuple[int, list[str]]] = []  # (original_chunk_idx, grouped_texts)

    for chunk_idx, sentences in chunk_sentences:
        n = len(sentences)
        chunk_embeddings = all_embeddings[embed_offset : embed_offset + n]
        embed_offset += n

        split_points = _find_split_points(chunk_embeddings, cfg.similarity_threshold)
        grouped = _group_sentences(sentences, split_points)
        split_results.append((chunk_idx, grouped))

    # Build output RawChunks preserving source metadata
    # We need to interleave pass-through chunks and split chunks in original order
    pass_through_set = {
        i for i in range(len(chunks)) if i not in {ci for ci, _ in chunk_sentences}
    }

    final_output: list[RawChunk] = []
    global_chunk_idx = 0

    for i, original_chunk in enumerate(chunks):
        if i in pass_through_set:
            final_output.append(
                RawChunk(
                    text=original_chunk.text,
                    source_ref=original_chunk.source_ref,
                    source_file=original_chunk.source_file,
                    chunk_index=global_chunk_idx,
                )
            )
            global_chunk_idx += 1
        else:
            # Find the split results for this chunk
            grouped_texts = next(g for ci, g in split_results if ci == i)
            for j, group_text in enumerate(grouped_texts):
                if len(group_text) >= cfg.min_chunk_length:
                    final_output.append(
                        RawChunk(
                            text=group_text,
                            source_ref=f"{original_chunk.source_ref}:seg_{j + 1}",
                            source_file=original_chunk.source_file,
                            chunk_index=global_chunk_idx,
                        )
                    )
                    global_chunk_idx += 1

    log.info(
        "semantic_chunker.complete",
        input_chunks=len(chunks),
        output_chunks=len(final_output),
        chunks_split=len(chunk_sentences),
        passed_through=len(pass_through_set),
        threshold=cfg.similarity_threshold,
    )

    return final_output
