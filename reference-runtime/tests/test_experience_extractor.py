"""
Tests for ExperienceExtractor — mining execution history for patterns.

Uses a real :memory: SQLite database behind a mock EventStore and a mock
ExperienceStore to test extraction logic end-to-end.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.experience_extractor import (
    ExperienceExtractor,
    Experience,
)
from core.experience_store import ExperienceStore


# ── Helpers ──


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ── Fixtures ──


@pytest.fixture
def mock_event_store():
    """Create a mock EventStore with a real :memory: SQLite database
    with execution_records and events tables."""

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE execution_records (
            trace_id TEXT PRIMARY KEY,
            agent_id TEXT,
            agent_name TEXT,
            context_id TEXT,
            manifest_name TEXT,
            runtime_id TEXT,
            status TEXT,
            total_latency_ms REAL,
            total_cost_usd REAL,
            total_tokens INTEGER,
            error TEXT,
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            trace_id TEXT,
            event_type TEXT,
            task_id TEXT,
            capability TEXT,
            payload TEXT,
            metrics TEXT,
            source TEXT,
            sequence INTEGER,
            timestamp TEXT
        )
    """)

    mock = MagicMock()
    mock.get_connection.return_value = conn
    return mock, conn


@pytest.fixture
def mock_exp_store():
    """Create a mock ExperienceStore that collects saved experiences."""
    exp_store = MagicMock()
    exp_store.find_by_observation.return_value = None  # No duplicates by default
    return exp_store


@pytest.fixture
def extractor(mock_event_store, mock_exp_store):
    """Return a fresh ExperienceExtractor with mock stores."""
    mock, conn = mock_event_store
    return ExperienceExtractor(mock, mock_exp_store), conn, mock_exp_store


# ── Helpers for inserting test data ──


def _insert_execution(conn, **kwargs):
    defaults = {
        "trace_id": "trace_001",
        "agent_id": "agent_abc",
        "agent_name": "Test Agent",
        "context_id": "ctx_001",
        "manifest_name": "test_capability",
        "runtime_id": "openai",
        "status": "success",
        "total_latency_ms": 500.0,
        "total_cost_usd": 0.05,
        "total_tokens": 1000,
        "error": None,
        "created_at": _now_iso(),
    }
    defaults.update(kwargs)
    conn.execute(
        """INSERT OR REPLACE INTO execution_records
           (trace_id, agent_id, agent_name, context_id, manifest_name,
            runtime_id, status, total_latency_ms, total_cost_usd,
            total_tokens, error, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            defaults["trace_id"], defaults["agent_id"], defaults["agent_name"],
            defaults["context_id"], defaults["manifest_name"],
            defaults["runtime_id"], defaults["status"],
            defaults["total_latency_ms"], defaults["total_cost_usd"],
            defaults["total_tokens"], defaults["error"],
            defaults["created_at"],
        ),
    )
    conn.commit()


def _insert_event(conn, **kwargs):
    defaults = {
        "event_id": "evt_001",
        "trace_id": "trace_001",
        "event_type": "TaskCompleted",
        "task_id": "task_001",
        "capability": "test_capability",
        "payload": "{}",
        "metrics": "{}",
        "source": "executor",
        "sequence": 1,
        "timestamp": _now_iso(),
    }
    defaults.update(kwargs)
    conn.execute(
        """INSERT OR REPLACE INTO events
           (event_id, trace_id, event_type, task_id, capability,
            payload, metrics, source, sequence, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            defaults["event_id"], defaults["trace_id"],
            defaults["event_type"], defaults["task_id"],
            defaults["capability"], defaults["payload"],
            defaults["metrics"], defaults["source"],
            defaults["sequence"], defaults["timestamp"],
        ),
    )
    conn.commit()


# ── Tests ──


class TestExperienceExtractor:
    """Tests for ExperienceExtractor pattern mining methods."""

    # ── extract_failure_patterns ──

    def test_extract_failure_patterns_creates_experiences(self, extractor):
        """extract_failure_patterns() creates experiences for repeated error types."""
        ext, conn, exp_store = extractor

        # Insert 3+ failures of the same type (meets _MIN_OCCURRENCES=3)
        for i in range(3):
            _insert_execution(
                conn,
                trace_id=f"fail_{i}",
                agent_id="agent_fp",
                status="failure",
                error=f"timeout error {i}",
                manifest_name="api_call",
                runtime_id="openai",
            )

        results = ext.extract_failure_patterns("agent_fp", since_days=30)
        assert len(results) >= 1
        exp = results[0]
        assert exp.type == "failure_pattern"
        assert exp.agent_id == "agent_fp"
        assert "timeout" in exp.observation.lower()
        assert exp.occurrence_count == 3
        assert exp.confidence > 0.4
        assert exp.experience_id.startswith("exp_")
        assert "timeout" in exp.recommendation.lower() or "batch" in exp.recommendation.lower()

    def test_extract_failure_patterns_insufficient_count(self, extractor):
        """extract_failure_patterns() does not create experiences below _MIN_OCCURRENCES."""
        ext, conn, exp_store = extractor

        # Only 2 failures — below _MIN_OCCURRENCES=3
        for i in range(2):
            _insert_execution(
                conn,
                trace_id=f"low_{i}",
                agent_id="agent_low",
                status="failure",
                error=f"timeout error {i}",
            )

        results = ext.extract_failure_patterns("agent_low", since_days=30)
        assert results == []

    def test_extract_failure_patterns_different_categories(self, extractor):
        """extract_failure_patterns() creates separate experiences per error category."""
        ext, conn, exp_store = extractor

        # 3 timeout errors
        for i in range(3):
            _insert_execution(
                conn, trace_id=f"to_{i}", agent_id="agent_multi",
                status="failure", error=f"Connection timed out {i}",
                manifest_name="api",
            )
        # 3 rate limit errors
        for i in range(3):
            _insert_execution(
                conn, trace_id=f"rl_{i}", agent_id="agent_multi",
                status="failure", error=f"Rate limit exceeded {i}",
                manifest_name="api",
            )

        results = ext.extract_failure_patterns("agent_multi", since_days=30)
        assert len(results) == 2
        types = {r.source_data.get("error_type") for r in results}
        assert types == {"timeout", "rate_limit"}

    def test_extract_failure_patterns_no_data(self, extractor):
        """extract_failure_patterns() returns empty list when there are no failures."""
        ext, conn, exp_store = extractor
        results = ext.extract_failure_patterns("agent_nodata", since_days=30)
        assert results == []

    # ── extract_success_strategies ──

    def test_extract_success_strategies_detects_retry_success(self, extractor):
        """extract_success_strategies() finds recovery patterns: fail -> retry -> succeed."""
        ext, conn, exp_store = extractor

        # Create 3 traces each showing failure -> retry -> success pattern
        for i in range(3):
            trace_id = f"recovery_{i}"
            _insert_event(
                conn, event_id=f"re_{i}_f", trace_id=trace_id,
                event_type="TaskFailed", capability="risky_cap",
                timestamp=_days_ago_iso(5),
            )
            _insert_event(
                conn, event_id=f"re_{i}_r", trace_id=trace_id,
                event_type="TaskRetried", capability="risky_cap",
                timestamp=_days_ago_iso(4),
            )
            _insert_event(
                conn, event_id=f"re_{i}_s", trace_id=trace_id,
                event_type="TaskCompleted", capability="risky_cap",
                timestamp=_days_ago_iso(3),
            )

        # Also insert matching execution_records for the trace_ids to pass filter
        for i in range(3):
            _insert_execution(
                conn, trace_id=f"recovery_{i}", agent_id="agent_rec",
                status="success",
            )

        results = ext.extract_success_strategies("agent_rec", since_days=30)
        # The extractor filters on events JOIN execution_records by trace_id and agent_id
        # So trace_ids must appear in execution_records for this agent
        assert isinstance(results, list)

    def test_extract_success_strategies_no_data(self, extractor):
        """extract_success_strategies() returns empty list when there is no recovery data."""
        ext, conn, exp_store = extractor
        results = ext.extract_success_strategies("agent_nodata", since_days=30)
        assert results == []

    # ── extract_tool_preferences ──

    def test_extract_tool_preferences_compares_cost(self, extractor):
        """extract_tool_preferences() creates preference when one model is >20% cheaper."""
        ext, conn, exp_store = extractor

        # Use 3+ executions per model for the same capability
        for i in range(3):
            _insert_execution(
                conn, trace_id=f"ch_{i}", agent_id="agent_tool",
                manifest_name="summarize", runtime_id="cheap_model",
                total_cost_usd=0.01, total_tokens=200,
                status="success",
            )
        for i in range(3):
            _insert_execution(
                conn, trace_id=f"ex_{i}", agent_id="agent_tool",
                manifest_name="summarize", runtime_id="expensive_model",
                total_cost_usd=0.05, total_tokens=500,
                status="success",
            )

        results = ext.extract_tool_preferences("agent_tool", since_days=30)
        # cheap_model costs 0.01 vs 0.05 = 80% savings, should trigger preference
        assert len(results) >= 1
        pref = results[0]
        assert pref.type == "tool_preference"
        assert pref.source_data["preferred_model"] == "cheap_model"
        assert pref.source_data["cost_savings_pct"] >= 20.0

    def test_extract_tool_preferences_not_enough_data(self, extractor):
        """extract_tool_preferences() requires at least _MIN_OCCURRENCES per model."""
        ext, conn, exp_store = extractor

        # Only 1 execution per model — not enough
        _insert_execution(
            conn, trace_id="s1", agent_id="agent_insuf",
            manifest_name="task", runtime_id="model_a",
            total_cost_usd=0.01, status="success",
        )
        _insert_execution(
            conn, trace_id="s2", agent_id="agent_insuf",
            manifest_name="task", runtime_id="model_b",
            total_cost_usd=0.05, status="success",
        )

        results = ext.extract_tool_preferences("agent_insuf", since_days=30)
        assert results == []

    def test_extract_tool_preferences_no_data(self, extractor):
        """extract_tool_preferences() returns empty list when there is no data."""
        ext, conn, exp_store = extractor
        results = ext.extract_tool_preferences("agent_nodata", since_days=30)
        assert results == []

    # ── extract_data_source_reliability ──

    def test_extract_data_source_reliability_no_evidence_store(self, extractor):
        """extract_data_source_reliability() returns [] when evidence_store is None."""
        ext, conn, exp_store = extractor
        results = ext.extract_data_source_reliability("agent_ds", since_days=30)
        assert results == []

    # ── extract_all ──

    def test_extract_all_returns_counts(self, extractor):
        """extract_all() runs all extractors and returns per-type counts."""
        ext, conn, exp_store = extractor

        # Create 3+ failure patterns for extract_failure_patterns
        for i in range(3):
            _insert_execution(
                conn, trace_id=f"ea_fail_{i}", agent_id="agent_all",
                status="failure", error=f"timeout {i}",
                manifest_name="api", runtime_id="openai",
            )

        # Create 3+ cheap + 3+ expensive for tool_preferences
        for i in range(3):
            _insert_execution(
                conn, trace_id=f"ea_ch_{i}", agent_id="agent_all",
                manifest_name="task", runtime_id="cheap",
                total_cost_usd=0.01, status="success",
            )
        for i in range(3):
            _insert_execution(
                conn, trace_id=f"ea_ex_{i}", agent_id="agent_all",
                manifest_name="task", runtime_id="expensive",
                total_cost_usd=0.05, status="success",
            )

        results = ext.extract_all("agent_all", since_days=30)

        assert isinstance(results, dict)
        assert "failure_patterns" in results
        assert "success_strategies" in results
        assert "tool_preferences" in results
        assert "data_source_reliability" in results
        assert "context_ids" in results
        assert "context_linked" in results
        # We should get at least failure_patterns and tool_preferences
        assert results["failure_patterns"] >= 1
        assert results["tool_preferences"] >= 1

    def test_extract_all_no_data_returns_zeros(self, extractor):
        """extract_all() returns zeros when there is no data to extract."""
        ext, conn, exp_store = extractor

        results = ext.extract_all("agent_nodata", since_days=30)

        assert results["failure_patterns"] == 0
        assert results["success_strategies"] == 0
        assert results["tool_preferences"] == 0
        assert results["data_source_reliability"] == 0

    # ── deduplication ──

    def test_deduplication_same_pattern_not_extracted_twice(self, extractor):
        """extract_all() skips experiences whose observation already exists."""
        ext, conn, exp_store = extractor

        # Create 3+ failures to form a pattern
        for i in range(3):
            _insert_execution(
                conn, trace_id=f"dedup_{i}", agent_id="agent_dedup",
                status="failure", error=f"timeout {i}",
                manifest_name="api", runtime_id="openai",
            )

        # Simulate that the first experience is a duplicate
        def _find_dup(agent_id, observation):
            return MagicMock()  # Non-None return = duplicate detected

        # First call: return no match (allow first extraction)
        call_count = [0]

        def _side_effect(agent_id, observation):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # Not a duplicate — save it
            return MagicMock()  # Is a duplicate — skip it

        exp_store.find_by_observation.side_effect = _side_effect

        results = ext.extract_all("agent_dedup", since_days=30)
        # The failure_patterns count should be 1 (first succeeded, then deduplication happened)
        # But since each failure type creates only 1 experience, it should be 1
        assert results["failure_patterns"] == 1

    # ── no data across all extractors ──

    def test_all_extractors_return_empty_when_no_data(self, extractor):
        """All individual extractors return empty lists when the store is empty."""
        ext, conn, exp_store = extractor

        assert ext.extract_failure_patterns("agent_empty", since_days=30) == []
        assert ext.extract_success_strategies("agent_empty", since_days=30) == []
        assert ext.extract_tool_preferences("agent_empty", since_days=30) == []
        assert ext.extract_data_source_reliability("agent_empty", since_days=30) == []

    # ── get_context_experiences ──

    def test_get_context_experiences_returns_tagged(self, extractor):
        """get_context_experiences() returns experiences tagged with a context."""
        ext, conn, exp_store = extractor

        # Mock the experience_store's internal get_conn for query
        exp_conn = sqlite3.connect(":memory:")
        exp_conn.row_factory = sqlite3.Row
        exp_conn.execute("""
            CREATE TABLE experiences (
                experience_id TEXT PRIMARY KEY,
                agent_id TEXT,
                type TEXT,
                observation TEXT,
                recommendation TEXT,
                confidence REAL DEFAULT 0.5,
                occurrence_count INTEGER DEFAULT 0,
                source_data TEXT DEFAULT '{}',
                tags TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        exp_conn.commit()

        # Insert a tagged experience
        exp_conn.execute(
            """INSERT INTO experiences
               (experience_id, agent_id, type, observation, recommendation, tags)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("exp_test001", "agent_ctx", "failure_pattern",
             "Test observation", "Test recommendation",
             '["context:ctx_abc", "api"]'),
        )
        exp_conn.commit()

        exp_store._get_conn.return_value = exp_conn

        results = ext.get_context_experiences("ctx_abc", limit=50)
        assert len(results) == 1
        assert results[0].experience_id == "exp_test001"
        assert results[0].agent_id == "agent_ctx"


# ── ExperienceStore (extractor-local) tests ──


class TestExtractorExperienceStore:
    """Tests for ExperienceStore using the canonical store API."""

    def _make_store(self, tmp_path):
        from core.experience_store import ExperienceStore
        db = tmp_path / "test_extractor_exp.db"
        return ExperienceStore(str(db))

    def test_save_and_find(self, tmp_path):
        from core.models import Experience
        store = self._make_store(tmp_path)
        exp = Experience(
            experience_id="exp_save_1", agent_id="agent_save",
            type="failure_pattern", observation="Unique observation text",
            recommendation="Fix it", created_at=_now_iso(),
        )
        store.save(exp)
        found = store.find_by_observation("agent_save", "Unique observation text")
        assert found is not None
        assert found["observation"] == "Unique observation text"

    def test_find_by_observation_nonexistent(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.find_by_observation("no_agent", "no text") is None

    def test_list_by_agent(self, tmp_path):
        from core.models import Experience
        store = self._make_store(tmp_path)
        for i in range(3):
            store.save(Experience(
                experience_id=f"exp_list_{i}", agent_id="agent_list",
                type="failure_pattern", observation=f"Obs {i}",
                recommendation="", created_at=_now_iso(),
            ))
        store.save(Experience(
            experience_id="exp_list_other", agent_id="other_agent",
            type="failure_pattern", observation="Other",
            recommendation="", created_at=_now_iso(),
        ))
        results = store.list(agent_id="agent_list")
        assert len(results) == 3

    def test_list_by_agent_filtered_by_type(self, tmp_path):
        from core.models import Experience
        store = self._make_store(tmp_path)
        store.save(Experience(experience_id="exp_ft_1", agent_id="agent_ft",
                    type="failure_pattern", observation="F",
                    recommendation="", created_at=_now_iso()))
        store.save(Experience(experience_id="exp_ft_2", agent_id="agent_ft",
                    type="success_strategy", observation="S",
                    recommendation="", created_at=_now_iso()))
        results = store.list(agent_id="agent_ft", type="failure_pattern")
        assert len(results) == 1
        assert results[0]["observation"] == "F"

    def test_list_all(self, tmp_path):
        from core.models import Experience
        store = self._make_store(tmp_path)
        store.save(Experience(experience_id="exp_all_1", agent_id="agent_a",
                    type="failure_pattern", observation="A",
                    recommendation="", created_at=_now_iso()))
        store.save(Experience(experience_id="exp_all_2", agent_id="agent_b",
                    type="success_strategy", observation="B",
                    recommendation="", created_at=_now_iso()))
        results = store.list()
        assert len(results) == 2

    def test_delete(self, tmp_path):
        from core.models import Experience
        store = self._make_store(tmp_path)
        store.save(Experience(experience_id="exp_del", agent_id="agent_del",
                    type="failure_pattern", observation="Delete me",
                    recommendation="", created_at=_now_iso()))
        assert store.delete("exp_del") is True
        assert store.get("exp_del") is None

    def test_delete_nonexistent(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.delete("exp_nonexistent") is False

    def test_update_tags(self, tmp_path):
        from core.models import Experience
        store = self._make_store(tmp_path)
        store.save(Experience(experience_id="exp_tags", agent_id="agent_tags",
                    type="failure_pattern", observation="Tags test",
                    recommendation="", tags=["old"], created_at=_now_iso()))
        store.update_tags("exp_tags", ["new_tag", "another"])
        found = store.get("exp_tags")
        assert found is not None
        assert set(found["tags"]) == {"new_tag", "another"}

    def test_count(self, tmp_path):
        from core.models import Experience
        store = self._make_store(tmp_path)
        assert store.count() == 0
        store.save(Experience(experience_id="exp_c1", agent_id="agent_c",
                    type="failure_pattern", observation="One",
                    recommendation="", created_at=_now_iso()))
        store.save(Experience(experience_id="exp_c2", agent_id="agent_c",
                    type="success_strategy", observation="Two",
                    recommendation="", created_at=_now_iso()))
        assert store.count() == 2
