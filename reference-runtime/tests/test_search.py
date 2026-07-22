"""
Intent OS — Semantic Search Tests

Tests cover:
  1. tokenize() — text preprocessing
  2. TfidfVectorizer — fit/transform cycle
  3. cosine_similarity — vector comparison
  4. SearchIndex — build/search workflow
  5. Edge cases — empty corpus, single document, no matches
"""

from __future__ import annotations

import sys
import math
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.search import (
    TfidfVectorizer,
    SearchIndex,
    cosine_similarity,
    tokenize,
)


# ====================================================================
# 1. Tokenizer
# ====================================================================

class TestTokenizer:
    """Test text tokenization."""

    def test_basic_tokenization(self):
        """Simple text should split into lowercase tokens."""
        tokens = tokenize("Hello World Test")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_stop_words_removed(self):
        """Common English stop words should be filtered."""
        tokens = tokenize("the quick brown fox jumps over the lazy dog")
        assert "the" not in tokens
        assert "over" not in tokens
        assert "quick" in tokens
        assert "brown" in tokens

    def test_single_char_filtered(self):
        """Single-character tokens should be removed."""
        tokens = tokenize("a b c test")
        assert "test" in tokens
        assert "a" not in tokens
        assert "b" not in tokens

    def test_case_normalization(self):
        """All tokens should be lowercase."""
        tokens = tokenize("UPPER lower Mixed")
        assert tokens == ["upper", "lower", "mixed"]

    def test_special_characters(self):
        """Hyphens and underscores should be treated as separators."""
        tokens = tokenize("text-summarize and/or data_analysis")
        assert "text" in tokens
        assert "summarize" in tokens
        assert "data" in tokens
        assert "analysis" in tokens
        assert "or" not in tokens  # two-letter stop word

    def test_empty_string(self):
        """Empty string should produce empty token list."""
        assert tokenize("") == []

    def test_only_stop_words(self):
        """Text with only stop words should produce empty token list."""
        assert tokenize("the and or of") == []


# ====================================================================
# 2. TF-IDF Vectorizer
# ====================================================================

class TestTfidfVectorizer:
    """Test the pure Python TF-IDF implementation."""

    def test_fit_and_transform(self):
        """Simple corpus should produce non-zero vectors."""
        vec = TfidfVectorizer()
        docs = [
            tokenize("search the web for information"),
            tokenize("analyze text content"),
            tokenize("generate report from data"),
        ]
        vec.fit(docs)
        assert vec.is_fitted
        assert vec.vocabulary_size > 0

    def test_transform_produces_l2_normalized_vector(self):
        """Output vectors should be L2-normalized (magnitude ~1.0)."""
        vec = TfidfVectorizer()
        docs = [
            tokenize("search web"),
            tokenize("analyze text"),
        ]
        vec.fit(docs)
        v = vec.transform(tokenize("search web"))
        magnitude = math.sqrt(sum(x * x for x in v))
        assert abs(magnitude - 1.0) < 0.001

    def test_different_docs_produce_different_vectors(self):
        """Different documents should yield different vector representations."""
        vec = TfidfVectorizer()
        docs = [
            tokenize("search web information retrieval"),
            tokenize("financial analysis stock market"),
        ]
        vec.fit(docs)
        v1 = vec.transform(tokenize("search web"))
        v2 = vec.transform(tokenize("financial analysis"))
        assert v1 != v2

    def test_empty_corpus(self):
        """Empty corpus should produce empty vocabulary."""
        vec = TfidfVectorizer()
        vec.fit([])
        assert vec.vocabulary_size == 0

    def test_transform_before_fit_raises(self):
        """Calling transform() before fit() should raise."""
        vec = TfidfVectorizer()
        with pytest.raises(RuntimeError, match="not fitted"):
            vec.transform([])


# ====================================================================
# 3. Cosine Similarity
# ====================================================================

class TestCosineSimilarity:
    """Test cosine similarity computation."""

    def test_identical_vectors(self):
        """Identical vectors should have similarity 1.0."""
        v = [0.5, 0.3, 0.2]
        sim = cosine_similarity(v, v)
        assert abs(sim - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        """Orthogonal vectors should have similarity 0.0."""
        sim = cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(sim) < 0.001

    def test_partial_match(self):
        """Partially matching vectors should have intermediate similarity."""
        sim = cosine_similarity([1.0, 0.5], [0.5, 1.0])
        assert 0.0 < sim < 1.0

    def test_dimension_mismatch_raises(self):
        """Vectors of different lengths should raise ValueError."""
        with pytest.raises(ValueError, match="dimension"):
            cosine_similarity([1.0], [0.5, 0.5])

    def test_zero_vector(self):
        """Zero vector should produce 0.0 similarity."""
        sim = cosine_similarity([0.0, 0.0], [1.0, 0.0])
        assert abs(sim) < 0.001


# ====================================================================
# 4. SearchIndex
# ====================================================================

class TestSearchIndex:
    """Test the full search index workflow."""

    def test_empty_index_returns_empty(self):
        """Searching an empty index should return empty list."""
        idx = SearchIndex()
        idx.build([])
        assert idx.search("anything") == []

    def test_basic_search(self):
        """Search should return ranked results."""
        idx = SearchIndex()
        idx.build([
            {"id": "search@1.0.0", "name": "web_search", "description": "Search the web for information", "tags": ["search", "web"]},
            {"id": "analyze@1.0.0", "name": "text_analyze", "description": "Analyze text content for insights", "tags": ["nlp", "analysis"]},
            {"id": "report@1.0.0", "name": "report_generate", "description": "Generate formatted reports", "tags": ["report", "format"]},
        ])

        results = idx.search("search web")
        assert len(results) > 0
        # web_search should be the top result for "search web"
        assert results[0]["capability"]["name"] == "web_search"

    def test_scored_results(self):
        """Results should include a score between 0 and 1."""
        idx = SearchIndex()
        idx.build([
            {"id": "a@1.0.0", "name": "alpha", "description": "Text analysis nlp", "tags": []},
            {"id": "b@1.0.0", "name": "beta", "description": "Web search", "tags": []},
        ])
        results = idx.search("text analysis nlp")
        assert len(results) > 0
        for r in results:
            assert 0.0 <= r["score"] <= 1.0

    def test_min_score_filter(self):
        """min_score should filter low-relevance results."""
        idx = SearchIndex()
        idx.build([
            {"id": "match@1.0.0", "name": "exact_match", "description": "The exact query term", "tags": []},
            {"id": "nosie@1.0.0", "name": "unrelated", "description": "Something completely different", "tags": []},
        ])
        results = idx.search("exact query term")
        assert len(results) >= 1
        # With high min_score, only good matches survive
        good = idx.search("exact query term", min_score=0.01)
        assert len(good) >= 1

    def test_limit(self):
        """limit parameter should cap result count."""
        idx = SearchIndex()
        docs = [
            {"id": f"cap{i}@1.0.0", "name": f"capability_{i}", "description": "A test capability for search", "tags": []}
            for i in range(20)
        ]
        idx.build(docs)
        results = idx.search("test capability search", limit=5)
        assert len(results) <= 5

    def test_rebuild_updates_index(self):
        """Rebuilding with new documents should replace old index."""
        idx = SearchIndex()
        idx.build([
            {"id": "old@1.0.0", "name": "old_cap", "description": "Original", "tags": []},
        ])
        assert idx.document_count == 1

        idx.build([
            {"id": "new@1.0.0", "name": "new_cap", "description": "Replacement", "tags": []},
        ])
        assert idx.document_count == 1
        # Search should find the new, not the old
        results = idx.search("replacement")
        assert len(results) > 0
        assert results[0]["capability"]["name"] == "new_cap"


class TestSearchIndexEdgeCases:
    """Test edge cases for the search index."""

    def test_single_document(self):
        """Index with one document should still work."""
        idx = SearchIndex()
        idx.build([
            {"id": "only@1.0.0", "name": "only_capability", "description": "The only capability in the registry", "tags": []},
        ])
        results = idx.search("capability registry")
        assert len(results) == 1
        assert results[0]["capability"]["name"] == "only_capability"

    def test_query_with_no_common_terms(self):
        """Query with terms not in any document should return empty."""
        idx = SearchIndex()
        idx.build([
            {"id": "a@1.0.0", "name": "alpha", "description": "Numbers and math", "tags": []},
        ])
        results = idx.search("quantum physics astrophysics")
        assert results == []

    def test_query_only_stop_words(self):
        """Query consisting entirely of stop words should return empty."""
        idx = SearchIndex()
        idx.build([
            {"id": "a@1.0.0", "name": "alpha", "description": "Something", "tags": []},
        ])
        results = idx.search("the and of or")
        assert results == []

    def test_document_count_property(self):
        """document_count should reflect the number of indexed documents."""
        idx = SearchIndex()
        assert idx.document_count == 0
        idx.build([
            {"id": "a@1.0.0", "name": "a", "description": "", "tags": []},
            {"id": "b@1.0.0", "name": "b", "description": "", "tags": []},
        ])
        assert idx.document_count == 2
