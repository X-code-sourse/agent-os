"""
Intent OS — Semantic Search Engine for Capability Registry

Provides text-based semantic search over registered capabilities using
TF-IDF vectorization and cosine similarity — all in pure Python with
zero external dependencies.

No embedding API calls, no vector database, no ML models required.
The index is built in-memory from the capability registry's metadata
(name, description, tags, publisher, input/output schema field names).

Design decisions:
  - TF-IDF over bag-of-words: lightweight, deterministic, reproducible
  - Lazy index rebuild: index is rebuilt on first search after registry changes
  - Stop word removal: common English words filtered to improve relevance
  - Score normalization: results are ranked 0.0–1.0 for intuitive interpretation

Phase 2+: Can be swapped for a vector embedding approach (OpenAI/text-embedding-3
or similar) without changing the search API — the registry only depends on
SearchIndexInterface, not on the TF-IDF implementation.
"""

from __future__ import annotations

import math
import re
from typing import Any


# ──────────────────────────────────────────────
# Stop words (common English words with low signal)
# ──────────────────────────────────────────────

_STOP_WORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
    "we", "you", "your", "our", "not", "no", "nor", "so", "if", "then",
    "than", "too", "very", "just", "about", "up", "down", "out", "off",
    "over", "under", "again", "further", "once", "here", "there", "all",
    "each", "every", "both", "few", "more", "most", "other", "some", "such",
    "only", "own", "same", "into", "onto", "upon", "per", "via",
}


# ──────────────────────────────────────────────
# Tokenizer
# ──────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase terms, filtering stop words and short tokens.

    Args:
        text: Raw text string.

    Returns:
        List of cleaned, meaningful tokens.
    """
    # Split on non-alphanumeric characters; treat underscores and hyphens as separators
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9]{1,}", text.lower().replace("_", " ").replace("-", " "))
    # Filter stop words and single-character tokens
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


# ──────────────────────────────────────────────
# TF-IDF Implementation (pure Python)
# ──────────────────────────────────────────────

class TfidfVectorizer:
    """Lightweight TF-IDF vectorizer with no external dependencies.

    Term Frequency = log(1 + count(t, d))
    Inverse Document Frequency = log(1 + N / df(t))
    TF-IDF = TF * IDF  (L2-normalized per document)
    """

    def __init__(self) -> None:
        self._vocab: dict[str, int] = {}         # term → index
        self._idf: list[float] = []               # IDF per term
        self._num_docs: int = 0
        self._fitted: bool = False

    def fit(self, documents: list[list[str]]) -> None:
        """Build vocabulary and compute IDF from a corpus of tokenized documents.

        Args:
            documents: List of token lists, one per document.
        """
        # Build vocabulary
        term_doc_count: dict[str, int] = {}
        for tokens in documents:
            seen = set()
            for t in tokens:
                if t not in seen:
                    term_doc_count[t] = term_doc_count.get(t, 0) + 1
                    seen.add(t)

        self._vocab = {term: idx for idx, term in enumerate(sorted(term_doc_count))}
        self._num_docs = len(documents)
        N = self._num_docs

        # Compute IDF
        self._idf = [0.0] * len(self._vocab)
        for term, idx in self._vocab.items():
            df = term_doc_count.get(term, 1)
            self._idf[idx] = 1.0 + math.log(N / df)

        self._fitted = True

    def transform(self, tokens: list[str]) -> list[float]:
        """Transform a tokenized document into a TF-IDF vector.

        Args:
            tokens: Tokenized document.

        Returns:
            L2-normalized TF-IDF vector as a list of floats.
        """
        if not self._fitted:
            raise RuntimeError("Vectorizer not fitted — call fit() first.")

        vec = [0.0] * len(self._vocab)
        term_count: dict[str, int] = {}
        for t in tokens:
            term_count[t] = term_count.get(t, 0) + 1

        max_tf = max(term_count.values()) if term_count else 1
        for term, count in term_count.items():
            if term in self._vocab:
                idx = self._vocab[term]
                # TF = count / max_tf  (normalized term frequency)
                tf = count / max_tf
                vec[idx] = tf * self._idf[idx]

        # L2 normalization
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]

        return vec

    @property
    def vocabulary_size(self) -> int:
        """Return the size of the vocabulary."""
        return len(self._vocab)

    @property
    def is_fitted(self) -> bool:
        """Whether the vectorizer has been fitted."""
        return self._fitted


# ──────────────────────────────────────────────
# Cosine Similarity
# ──────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a, b: Two vectors of equal length.

    Returns:
        Similarity score in [0.0, 1.0].
    """
    if len(a) != len(b):
        raise ValueError(f"Vector dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(av * bv for av, bv in zip(a, b))
    norm_a = math.sqrt(sum(av * av for av in a))
    norm_b = math.sqrt(sum(bv * bv for bv in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return min(max(dot / (norm_a * norm_b), 0.0), 1.0)


# ──────────────────────────────────────────────
# Search Document Builder
# ──────────────────────────────────────────────

def _build_search_text(doc: dict[str, Any]) -> str:
    """Build a searchable text from a capability document.

    Combines name, description, tags, publisher, and schema field names
    into a single weighted text string. Name and description are repeated
    to boost their weight vs tags and field names.

    Args:
        doc: Capability summary dict (from registry.list_capabilities()).

    Returns:
        Weighted search text.
    """
    parts: list[str] = []

    # Name — highest weight (repeated)
    name = doc.get("name", "")
    if name:
        parts.extend([name] * 3)

    # Description — high weight (repeated)
    desc = doc.get("description", "") or ""
    if desc:
        parts.extend([desc] * 2)

    # Tags — medium weight
    tags = doc.get("tags") or []
    parts.extend(tags)

    # Publisher — low weight
    pub = doc.get("publisher") or ""
    if pub:
        # Extract meaningful parts from reverse domain notation
        pub_parts = pub.replace(".", " ").replace("-", " ").split()
        parts.extend(pub_parts)

    return " ".join(parts)


# ──────────────────────────────────────────────
# Search Index
# ──────────────────────────────────────────────

class SearchIndex:
    """In-memory semantic search index over capability documents.

    The index is built lazily and rebuilt when documents change.
    Thread-safe for read operations; write operations should be
    externally synchronized (caller's responsibility).

    Usage:
        index = SearchIndex()
        index.build(documents)       # Build or rebuild from capability list
        results = index.search("text analysis")  # Returns ranked results
    """

    def __init__(self) -> None:
        self._vectorizer = TfidfVectorizer()
        self._vectors: list[list[float]] = []
        self._documents: list[dict[str, Any]] = []
        self._built: bool = False

    def build(self, documents: list[dict[str, Any]]) -> None:
        """Build or rebuild the search index from capability documents.

        Args:
            documents: List of capability summary dicts, typically from
                       CapabilityRegistry.list_capabilities().
                       Each dict must have at least 'name' and 'id' keys.
        """
        self._documents = list(documents)
        self._vectorizer = TfidfVectorizer()  # Fresh vectorizer

        # Tokenize all documents
        tokenized = [tokenize(_build_search_text(doc)) for doc in documents]

        # Fit vectorizer and transform
        if tokenized:
            self._vectorizer.fit(tokenized)
            self._vectors = [self._vectorizer.transform(tokens) for tokens in tokenized]
        else:
            self._vectors = []

        self._built = True

    def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Search the index for capabilities matching the query.

        Args:
            query: Free-text search query.
            limit: Maximum number of results.
            min_score: Minimum similarity score threshold (0.0–1.0).

        Returns:
            List of result dicts, each with:
              - capability: original capability summary dict
              - score: similarity score (0.0–1.0)
            Sorted by descending score.
        """
        if not self._built or not self._documents:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        query_vec = self._vectorizer.transform(query_tokens)

        # Score all documents
        scored: list[tuple[float, dict[str, Any]]] = []
        for i, doc_vec in enumerate(self._vectors):
            score = cosine_similarity(query_vec, doc_vec)
            if score > min_score:  # Exclude zero and below-threshold scores
                scored.append((score, self._documents[i]))

        # Sort by score descending, take top-k
        scored.sort(key=lambda x: -x[0])
        top = scored[:limit]

        return [
            {"capability": doc, "score": round(score, 4)}
            for score, doc in top
        ]

    @property
    def document_count(self) -> int:
        """Number of documents in the index."""
        return len(self._documents)

    @property
    def is_built(self) -> bool:
        """Whether the index has been built."""
        return self._built

    def get_vocabulary_size(self) -> int:
        """Size of the search vocabulary."""
        return self._vectorizer.vocabulary_size if self._vectorizer.is_fitted else 0
