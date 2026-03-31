"""
tests/ingestion/test_semantic_chunker.py
Unit tests for the semantic chunker.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from agents.ingestion.doc_parser import RawChunk
from agents.ingestion.semantic_chunker import (
    SemanticChunkerConfig,
    _cosine_similarity,
    _find_split_points,
    _group_sentences,
    _split_sentences,
    semantic_chunk,
)


# ── Helper ───────────────────────────────────────────────────────────────────


def _make_chunk(text: str, source_ref: str = "test.txt:para_1", idx: int = 0) -> RawChunk:
    return RawChunk(text=text, source_ref=source_ref, source_file="test.txt", chunk_index=idx)


def _random_embedding(dim: int = 1024, seed: int = 0) -> np.ndarray:
    rng = np.random.RandomState(seed)
    vec = rng.randn(dim).astype(np.float32)
    return vec / np.linalg.norm(vec)


# ── _cosine_similarity ──────────────────────────────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = _random_embedding(seed=42)
        assert _cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-5)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert _cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-5)

    def test_zero_vector(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 0.0])
        assert _cosine_similarity(a, b) == 0.0


# ── _find_split_points ──────────────────────────────────────────────────────


class TestFindSplitPoints:
    def test_no_embeddings(self):
        assert _find_split_points(np.array([]), threshold=0.5) == []

    def test_single_embedding(self):
        emb = _random_embedding(seed=1).reshape(1, -1)
        assert _find_split_points(emb, threshold=0.5) == []

    def test_similar_embeddings_no_split(self):
        """Two near-identical embeddings should not produce a split."""
        base = _random_embedding(dim=64, seed=10)
        noise = np.random.RandomState(11).randn(64).astype(np.float32) * 0.01
        similar = (base + noise) / np.linalg.norm(base + noise)
        embeddings = np.stack([base, similar])
        assert _find_split_points(embeddings, threshold=0.5) == []

    def test_dissimilar_embeddings_split(self):
        """Two orthogonal-ish embeddings should produce a split."""
        a = _random_embedding(dim=64, seed=20)
        b = _random_embedding(dim=64, seed=999)  # very different seed → different direction
        embeddings = np.stack([a, b])
        # With low-dim random vectors, similarity is ~0, so threshold=0.5 should split
        splits = _find_split_points(embeddings, threshold=0.5)
        assert splits == [1]


# ── _group_sentences ─────────────────────────────────────────────────────────


class TestGroupSentences:
    def test_no_split_points(self):
        sentences = ["Hello world.", "How are you."]
        result = _group_sentences(sentences, [])
        assert result == ["Hello world. How are you."]

    def test_single_split_point(self):
        sentences = ["A.", "B.", "C.", "D."]
        result = _group_sentences(sentences, [2])
        assert result == ["A. B.", "C. D."]

    def test_multiple_split_points(self):
        sentences = ["A.", "B.", "C.", "D.", "E."]
        result = _group_sentences(sentences, [1, 3])
        assert result == ["A.", "B. C.", "D. E."]


# ── _split_sentences ─────────────────────────────────────────────────────────


class TestSplitSentences:
    def test_single_sentence(self):
        result = _split_sentences("The vendor invoice must be validated.")
        assert len(result) == 1

    def test_multiple_sentences(self):
        text = "The system shall process invoices. It must also handle credits. Reports are optional."
        result = _split_sentences(text)
        assert len(result) >= 3


# ── semantic_chunk (integration) ─────────────────────────────────────────────


class TestSemanticChunk:
    @pytest.mark.asyncio
    async def test_empty_input(self):
        result = await semantic_chunk([])
        assert result == []

    @pytest.mark.asyncio
    async def test_short_chunk_passes_through(self):
        """Chunks with fewer than min_sentences_to_chunk pass through unchanged."""
        chunk = _make_chunk("The vendor invoice must be validated.")
        config = SemanticChunkerConfig(min_sentences_to_chunk=3)
        result = await semantic_chunk([chunk], config)
        assert len(result) == 1
        assert result[0].text == chunk.text

    @pytest.mark.asyncio
    async def test_multi_sentence_chunk_gets_processed(self):
        """A chunk with many sentences about different topics should be split."""
        # Deliberately mix unrelated topics
        text = (
            "The accounts payable module must support three-way matching for purchase orders. "
            "Vendor invoices should be validated against goods receipts. "
            "The warehouse management system needs barcode scanning for inventory counts. "
            "Cycle counting must be performed weekly in all storage locations. "
            "The general ledger should support multi-currency consolidation across legal entities."
        )
        chunk = _make_chunk(text)
        config = SemanticChunkerConfig(
            similarity_threshold=0.75,
            min_sentences_to_chunk=3,
        )

        # Mock the embedder to return controlled embeddings
        # AP sentences (0,1) are similar, WMS sentences (2,3) are similar, GL (4) is different
        dim = 1024
        ap_base = _random_embedding(dim=dim, seed=100)
        wms_base = _random_embedding(dim=dim, seed=200)
        gl_base = _random_embedding(dim=dim, seed=300)

        fake_embeddings = np.stack([
            ap_base,
            ap_base + np.random.RandomState(101).randn(dim).astype(np.float32) * 0.05,
            wms_base,
            wms_base + np.random.RandomState(201).randn(dim).astype(np.float32) * 0.05,
            gl_base,
        ])
        # Re-normalize
        fake_embeddings = fake_embeddings / np.linalg.norm(
            fake_embeddings, axis=1, keepdims=True
        )

        with patch(
            "agents.ingestion.semantic_chunker._embed_sentences",
            return_value=fake_embeddings,
        ):
            result = await semantic_chunk([chunk], config)

        # Should have been split into at least 2 chunks (AP vs WMS vs GL)
        assert len(result) > 1
        # All source_refs should reference the original chunk
        for r in result:
            assert r.source_ref.startswith("test.txt:para_1")
            assert r.source_file == "test.txt"

    @pytest.mark.asyncio
    async def test_preserves_order_with_mixed_chunks(self):
        """Short and long chunks should maintain original order."""
        short = _make_chunk("Short sentence.", source_ref="test.txt:row_1", idx=0)
        long_text = (
            "First topic sentence one. First topic sentence two. "
            "Second topic completely different. Second topic elaboration. "
            "Third unrelated topic here."
        )
        long_chunk = _make_chunk(long_text, source_ref="test.txt:row_2", idx=1)
        trailing = _make_chunk("Another short one.", source_ref="test.txt:row_3", idx=2)

        config = SemanticChunkerConfig(min_sentences_to_chunk=3)

        # Mock embedder: make all embeddings identical so no splits happen
        dim = 1024
        same_vec = _random_embedding(dim=dim, seed=42)

        with patch(
            "agents.ingestion.semantic_chunker._embed_sentences",
            return_value=np.stack([same_vec] * 5),  # 5 sentences, all identical
        ):
            result = await semantic_chunk([short, long_chunk, trailing], config)

        # Short chunks pass through, long chunk stays as one (identical embeddings)
        assert len(result) == 3
        assert result[0].source_ref == "test.txt:row_1"
        assert result[1].source_ref.startswith("test.txt:row_2")
        assert result[2].source_ref == "test.txt:row_3"

    @pytest.mark.asyncio
    async def test_min_chunk_length_filters_tiny_segments(self):
        """Segments shorter than min_chunk_length are dropped."""
        text = "A. B. This is a longer segment that should survive the filter."
        chunk = _make_chunk(text)
        config = SemanticChunkerConfig(
            similarity_threshold=0.01,  # Force split everywhere
            min_sentences_to_chunk=2,
            min_chunk_length=10,
        )

        # Each sentence gets a random orthogonal embedding → splits everywhere
        dim = 1024
        fake_embeddings = np.stack([
            _random_embedding(dim=dim, seed=i) for i in range(3)
        ])

        with patch(
            "agents.ingestion.semantic_chunker._embed_sentences",
            return_value=fake_embeddings,
        ):
            result = await semantic_chunk([chunk], config)

        # "A." and "B." are < 10 chars, should be filtered out
        for r in result:
            assert len(r.text) >= config.min_chunk_length
