"""
Tests for ExperienceStore — SQLite-backed learned-experience persistence.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.experience_store import ExperienceStore, ExperienceStoreError


# ── Fixtures ──


@pytest.fixture
def store():
    """Return a fresh ExperienceStore backed by :memory: SQLite."""
    return ExperienceStore(db_path=":memory:")


# ── Tests ──


class TestExperienceStore:
    """Tests for ExperienceStore CRUD and query operations."""

    # ── create ──

    def test_create_exp_prefix_and_all_fields(self, store):
        """create() returns a dict with exp_ prefix and all expected fields."""
        exp = store.create(
            agent_id="agent_abc123",
            type="failure_pattern",
            observation="Timeout when calling API",
            recommendation="Add retry logic",
            source_executions=["exec_001", "exec_002"],
            confidence=0.8,
            domain="finance",
            tags=["api", "timeout"],
        )

        assert exp["experience_id"].startswith("exp_")
        assert len(exp["experience_id"]) == 16  # "exp_" + 12 hex
        assert exp["agent_id"] == "agent_abc123"
        assert exp["type"] == "failure_pattern"
        assert exp["observation"] == "Timeout when calling API"
        assert exp["recommendation"] == "Add retry logic"
        assert exp["source_executions"] == ["exec_001", "exec_002"]
        assert exp["confidence"] == 0.8
        assert exp["domain"] == "finance"
        assert exp["tags"] == ["api", "timeout"]
        assert exp["usage_count"] == 0
        assert exp["success_rate_when_applied"] == 0.0
        assert exp["last_validated_at"] is None
        assert exp["expires_at"] is None
        assert "created_at" in exp

    def test_create_with_defaults(self, store):
        """create() with minimal args uses sensible defaults."""
        exp = store.create(
            agent_id="agent_min",
            type="failure_pattern",
            observation="Something happened",
        )

        assert exp["recommendation"] == ""
        assert exp["source_executions"] == []
        assert exp["confidence"] == 0.0
        assert exp["domain"] == ""
        assert exp["tags"] == []

    # ── type validation ──

    def test_type_validation_invalid_rejected(self, store):
        """create() raises ExperienceStoreError for an invalid type."""
        with pytest.raises(ExperienceStoreError, match="Invalid experience type"):
            store.create(
                agent_id="agent_x",
                type="invalid_type_name",
                observation="Test",
            )

    def test_all_valid_types_accepted(self, store):
        """All valid experience types are accepted."""
        valid_types = [
            "failure_pattern",
            "success_strategy",
            "tool_preference",
            "model_performance",
            "data_source_reliability",
            "environment_constraint",
            "user_feedback",
        ]
        for t in valid_types:
            exp = store.create(agent_id="agent_vt", type=t, observation=f"Test {t}")
            assert exp["type"] == t

    # ── get ──

    def test_get_retrieves_by_id(self, store):
        """get() returns the experience dict for an existing ID."""
        exp = store.create(
            agent_id="agent_g",
            type="failure_pattern",
            observation="Find me",
        )
        retrieved = store.get(exp["experience_id"])

        assert retrieved is not None
        assert retrieved["experience_id"] == exp["experience_id"]
        assert retrieved["observation"] == "Find me"

    def test_get_nonexistent_returns_none(self, store):
        """get() returns None for a nonexistent experience ID."""
        result = store.get("exp_nonexistent")
        assert result is None

    # ── list ──

    def test_list_all(self, store):
        """list() without filters returns all experiences."""
        store.create(agent_id="agent_a", type="failure_pattern", observation="A")
        store.create(agent_id="agent_b", type="success_strategy", observation="B")
        store.create(agent_id="agent_a", type="tool_preference", observation="C")

        results = store.list()
        assert len(results) == 3

    def test_list_filter_by_agent_id(self, store):
        """list() filters by agent_id correctly."""
        store.create(agent_id="agent_x", type="failure_pattern", observation="X1")
        store.create(agent_id="agent_x", type="failure_pattern", observation="X2")
        store.create(agent_id="agent_y", type="failure_pattern", observation="Y")

        results = store.list(agent_id="agent_x")
        assert len(results) == 2
        assert all(r["agent_id"] == "agent_x" for r in results)

    def test_list_filter_by_type(self, store):
        """list() filters by type correctly."""
        store.create(agent_id="agent_t", type="failure_pattern", observation="F")
        store.create(agent_id="agent_t", type="success_strategy", observation="S1")
        store.create(agent_id="agent_t", type="success_strategy", observation="S2")

        failures = store.list(type="failure_pattern")
        assert len(failures) == 1
        assert failures[0]["observation"] == "F"

        successes = store.list(type="success_strategy")
        assert len(successes) == 2

    def test_list_filter_by_domain(self, store):
        """list() filters by domain using case-insensitive substring match."""
        store.create(agent_id="agent_d", type="failure_pattern",
                     observation="D1", domain="finance")
        store.create(agent_id="agent_d", type="failure_pattern",
                     observation="D2", domain="FINANCE_US")
        store.create(agent_id="agent_d", type="failure_pattern",
                     observation="D3", domain="healthcare")

        # Substring match — "finance" matches "finance" and "FINANCE_US"
        results = store.list(domain="finance")
        assert len(results) == 2

    def test_list_combined_filters(self, store):
        """list() supports combining agent_id, type, and domain filters."""
        store.create(agent_id="agent_m", type="failure_pattern",
                     observation="M1", domain="finance")
        store.create(agent_id="agent_m", type="success_strategy",
                     observation="M2", domain="finance")
        store.create(agent_id="agent_n", type="failure_pattern",
                     observation="M3", domain="finance")

        results = store.list(agent_id="agent_m", type="failure_pattern", domain="finance")
        assert len(results) == 1
        assert results[0]["observation"] == "M1"

    # ── query_by_task ──

    def test_query_by_task_keyword_matching(self, store):
        """query_by_task() finds experiences whose text matches goal keywords."""
        store.create(
            agent_id="agent_q",
            type="failure_pattern",
            observation="API timeout during earnings analysis",
            recommendation="Queue requests",
            domain="finance",
            tags=["api", "timeout"],
        )

        results = store.query_by_task("analyze quarterly earnings")
        assert len(results) >= 1
        # "earnings" keyword should match the observation
        assert any("timeout" in (r["observation"] or "") for r in results)

    def test_query_by_task_empty_goal(self, store):
        """query_by_task() with empty goal returns empty list (no keywords to match)."""
        store.create(agent_id="agent_eq", type="failure_pattern",
                     observation="Test observation")
        store.create(agent_id="agent_eq", type="success_strategy",
                     observation="Another observation")

        results = store.query_by_task("")
        assert results == []

    def test_query_by_task_no_matches(self, store):
        """query_by_task() returns empty list when no keywords match."""
        store.create(agent_id="agent_nm", type="failure_pattern",
                     observation="Network timeout")

        results = store.query_by_task("xyz unicorn rainbow")
        assert results == []

    # ── record_usage ──

    def test_record_usage_increments_count_and_updates_success_rate(self, store):
        """record_usage() increments usage_count and updates success_rate_when_applied."""
        exp = store.create(agent_id="agent_u", type="failure_pattern",
                          observation="Usage test")

        store.record_usage(exp["experience_id"], success=True)
        updated = store.get(exp["experience_id"])
        assert updated["usage_count"] == 1
        assert updated["success_rate_when_applied"] == 1.0

        store.record_usage(exp["experience_id"], success=False)
        updated = store.get(exp["experience_id"])
        assert updated["usage_count"] == 2
        assert updated["success_rate_when_applied"] == 0.5

        store.record_usage(exp["experience_id"], success=True)
        updated = store.get(exp["experience_id"])
        assert updated["usage_count"] == 3
        # Source rounds to 4 decimal places: round(2/3, 4) = 0.6667
        assert updated["success_rate_when_applied"] == 0.6667

    def test_record_usage_nonexistent_returns_false(self, store):
        """record_usage() returns False for nonexistent experience."""
        result = store.record_usage("exp_nonexistent", success=True)
        assert result is False

    # ── update_validation ──

    def test_update_validation_sets_timestamp(self, store):
        """update_validation() sets last_validated_at to the current timestamp."""
        exp = store.create(agent_id="agent_v", type="failure_pattern",
                          observation="Validation test")

        assert exp["last_validated_at"] is None

        result = store.update_validation(exp["experience_id"])
        assert result is True

        updated = store.get(exp["experience_id"])
        assert updated["last_validated_at"] is not None

    def test_update_validation_nonexistent_returns_false(self, store):
        """update_validation() returns False for nonexistent experience."""
        result = store.update_validation("exp_nonexistent")
        assert result is False

    # ── delete ──

    def test_delete_removes_record(self, store):
        """delete() removes the experience and returns True."""
        exp = store.create(agent_id="agent_del", type="failure_pattern",
                          observation="Delete me")

        assert store.get(exp["experience_id"]) is not None

        result = store.delete(exp["experience_id"])
        assert result is True
        assert store.get(exp["experience_id"]) is None

    def test_delete_nonexistent_returns_false(self, store):
        """delete() returns False for nonexistent experience."""
        result = store.delete("exp_nonexistent")
        assert result is False

    # ── empty query ──

    def test_empty_goal_returns_empty(self, store):
        """query_by_task('') returns empty list (no keywords to match)."""
        store.create(agent_id="agent_all", type="failure_pattern",
                     observation="One")
        store.create(agent_id="agent_all", type="success_strategy",
                     observation="Two")

        results = store.query_by_task("")
        assert results == []

    # ── get_by_context ──

    def test_get_by_context_no_event_store(self, store):
        """get_by_context() returns [] when no event_store is provided."""
        results = store.get_by_context("ctx_abc")
        assert results == []

    def test_get_by_context_event_store_without_connection(self, store):
        """get_by_context() returns [] when event_store has no get_connection."""
        results = store.get_by_context("ctx_abc", event_store="not_an_event_store")
        assert results == []
