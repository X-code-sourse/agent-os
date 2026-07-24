"""
Tests for ContextStore — SQLite-backed execution context store.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.context_store import ContextStore, ContextStoreError


# ── Fixtures ──


@pytest.fixture
def store(tmp_path):
    """Return a fresh ContextStore backed by a temp file SQLite DB."""
    db_path = str(tmp_path / "test_contexts.db")
    s = ContextStore(db_path=db_path)
    return s


# ── Tests ──


class TestContextStore:
    """Tests for ContextStore CRUD and versioning."""

    # ── create ──

    def test_create_returns_all_fields(self, store):
        """create() returns a dict with all expected fields and ctx_ prefix."""
        ctx = store.create(
            name="Test Analysis",
            goal="Analyze Q3 earnings",
            constraints=["SEC only", "NASDAQ"],
            task_scope="research",
            variables={"tickers": ["AAPL", "MSFT"]},
            created_by="user_1",
        )

        assert ctx["context_id"].startswith("ctx_")
        assert len(ctx["context_id"]) == 16  # "ctx_" + 12 hex
        assert ctx["name"] == "Test Analysis"
        assert ctx["goal"] == "Analyze Q3 earnings"
        assert ctx["constraints"] == ["SEC only", "NASDAQ"]
        assert ctx["task_scope"] == "research"
        assert ctx["variables"] == {"tickers": ["AAPL", "MSFT"]}
        assert ctx["created_by"] == "user_1"
        assert ctx["version"] == 1
        assert "created_at" in ctx
        assert ctx["expires_at"] is None
        assert ctx["parent_context_id"] is None

    def test_create_defaults(self, store):
        """create() with minimal args uses sensible defaults."""
        ctx = store.create(name="Minimal")

        assert ctx["goal"] == ""
        assert ctx["constraints"] == []
        assert ctx["task_scope"] == ""
        assert ctx["variables"] == {}
        assert ctx["created_by"] == ""

    # ── get ──

    def test_get_retrieves_by_id(self, store):
        """get() returns the context dict for an existing ID."""
        ctx = store.create(name="Find Me")
        retrieved = store.get(ctx["context_id"])

        assert retrieved is not None
        assert retrieved["context_id"] == ctx["context_id"]
        assert retrieved["name"] == "Find Me"

    def test_get_nonexistent_returns_none(self, store):
        """get() returns None for a nonexistent context ID."""
        result = store.get("ctx_nonexistent")
        assert result is None

    # ── list ──

    def test_list_filters_by_created_by(self, store):
        """list() filters by created_by correctly."""
        store.create(name="A", created_by="alice")
        store.create(name="B", created_by="bob")
        store.create(name="C", created_by="alice")

        alice_contexts = store.list(created_by="alice")
        assert len(alice_contexts) == 2
        assert all(c["created_by"] == "alice" for c in alice_contexts)

        bob_contexts = store.list(created_by="bob")
        assert len(bob_contexts) == 1
        assert bob_contexts[0]["name"] == "B"

    def test_list_empty_store(self, store):
        """list() on an empty store returns []."""
        result = store.list()
        assert result == []

    # ── assign_agent ──

    def test_assign_agent_and_get_assigned(self, store):
        """assign_agent() adds an assignment; get_assigned_agents() returns it."""
        ctx = store.create(name="Agent Test")
        result = store.assign_agent(ctx["context_id"], "agent_abc")

        assert result is True

        agents = store.get_assigned_agents(ctx["context_id"])
        assert agents == ["agent_abc"]

    def test_get_contexts_for_agent(self, store):
        """get_contexts_for_agent() returns all contexts an agent is assigned to."""
        ctx1 = store.create(name="Project A")
        ctx2 = store.create(name="Project B")
        store.assign_agent(ctx1["context_id"], "agent_x")
        store.assign_agent(ctx2["context_id"], "agent_x")

        contexts = store.get_contexts_for_agent("agent_x")
        assert len(contexts) == 2
        names = {c["name"] for c in contexts}
        assert names == {"Project A", "Project B"}

    # ── delete ──

    def test_delete_removes_context_and_assignments(self, store):
        """delete() removes the context and its assignments."""
        ctx = store.create(name="To Delete")
        store.assign_agent(ctx["context_id"], "agent_del")

        assert store.get(ctx["context_id"]) is not None
        assert store.get_assigned_agents(ctx["context_id"]) == ["agent_del"]

        deleted = store.delete(ctx["context_id"])
        assert deleted is True
        assert store.get(ctx["context_id"]) is None
        assert store.get_assigned_agents(ctx["context_id"]) == []

    def test_delete_nonexistent_returns_false(self, store):
        """delete() returns False for a nonexistent context."""
        result = store.delete("ctx_nonexistent")
        assert result is False

    # ── versioning ──

    def test_versioning_create_then_bump(self, store):
        """create() starts at version 1; bump_version() increments and get_history() returns entries."""
        ctx = store.create(name="Version Test")
        assert ctx["version"] == 1

        new_version = store.bump_version(ctx["context_id"], reason="Updated scope")
        assert new_version == 2

        # Verify current version is now 2
        current = store.get(ctx["context_id"])
        assert current is not None
        assert current["version"] == 2

        # get_history should have both versions
        history = store.get_history(ctx["context_id"])
        assert len(history) == 2
        assert history[0]["version"] == 2  # newest first
        assert history[0]["reason"] == "Updated scope"
        assert history[1]["version"] == 1

    def test_bump_version_nonexistent_raises(self, store):
        """bump_version() raises ContextStoreError for nonexistent context."""
        with pytest.raises(ContextStoreError, match="Context not found"):
            store.bump_version("ctx_nonexistent")

    def test_get_version_returns_snapshot(self, store):
        """get_version() returns the snapshot at a specific version."""
        ctx = store.create(name="v1 name")
        store.update(ctx["context_id"], name="v2 name", reason="Renamed")
        store.update(ctx["context_id"], name="v3 name", reason="Renamed again")

        v1 = store.get_version(ctx["context_id"], 1)
        assert v1 is not None
        assert v1["name"] == "v1 name"
        assert v1["version"] == 1

        v2 = store.get_version(ctx["context_id"], 2)
        assert v2 is not None
        assert v2["name"] == "v2 name"

        v3 = store.get_version(ctx["context_id"], 3)
        assert v3 is not None
        assert v3["name"] == "v3 name"

    def test_get_version_nonexistent(self, store):
        """get_version() returns None for nonexistent version."""
        ctx = store.create(name="Test")
        result = store.get_version(ctx["context_id"], 999)
        assert result is None

    # ── update ──

    def test_update_partial_fields(self, store):
        """update() only changes provided fields."""
        ctx = store.create(name="Original", goal="Old goal", task_scope="research")

        updated = store.update(ctx["context_id"], goal="New goal", reason="Scope change")

        assert updated["name"] == "Original"  # unchanged
        assert updated["goal"] == "New goal"
        assert updated["task_scope"] == "research"  # unchanged
        assert updated["version"] == 2

        # Verify persistence
        fetched = store.get(ctx["context_id"])
        assert fetched is not None
        assert fetched["goal"] == "New goal"
        assert fetched["version"] == 2

    # ── inheritance ──

    def test_inheritance_child_merges_constraints_and_variables(self, store):
        """Child context with parent merges constraints (union) and variables (parent defaults)."""
        parent = store.create(
            name="Parent",
            constraints=["SEC only", "limit 10"],
            variables={"base_dir": "/data", "timeout": 30},
        )
        child = store.create(
            name="Child",
            constraints=["limit 5"],
            variables={"timeout": 60},
            parent_context_id=parent["context_id"],
        )

        # Constraints: union of parent + child, deduplicated
        assert "SEC only" in child["constraints"]
        assert "limit 10" in child["constraints"]
        assert "limit 5" in child["constraints"]
        assert len(child["constraints"]) == 3

        # Variables: parent defaults, child overrides
        assert child["variables"]["base_dir"] == "/data"
        assert child["variables"]["timeout"] == 60  # child wins

    def test_inheritance_deduplicates_constraints(self, store):
        """Duplicate constraints across parent and child are collapsed."""
        parent = store.create(name="Parent", constraints=["A", "B"])
        child = store.create(
            name="Child",
            constraints=["B", "C"],
            parent_context_id=parent["context_id"],
        )

        assert child["constraints"] == ["A", "B", "C"]

    def test_inheritance_merges_variables(self, store):
        """Child variables override parent defaults on key conflict."""
        parent = store.create(
            name="Parent",
            variables={"x": 1, "y": 2, "z": 3},
        )
        child = store.create(
            name="Child",
            variables={"y": 20, "w": 4},
            parent_context_id=parent["context_id"],
        )

        assert child["variables"] == {"x": 1, "y": 20, "z": 3, "w": 4}

    def test_inheritance_chain_walks_to_root(self, store):
        """get_inheritance_chain() returns contexts from rootmost ancestor to child."""
        grandparent = store.create(name="Grandparent")
        parent = store.create(
            name="Parent",
            variables={"level": "parent"},
            parent_context_id=grandparent["context_id"],
        )
        child = store.create(
            name="Child",
            variables={"level": "child"},
            parent_context_id=parent["context_id"],
        )

        chain = store.get_inheritance_chain(child["context_id"])
        assert len(chain) == 3
        assert chain[0]["name"] == "Grandparent"
        assert chain[1]["name"] == "Parent"
        assert chain[2]["name"] == "Child"

    def test_inheritance_chain_no_parent(self, store):
        """get_inheritance_chain() returns a single-element list for a root context."""
        ctx = store.create(name="Root")
        chain = store.get_inheritance_chain(ctx["context_id"])

        assert len(chain) == 1
        assert chain[0]["name"] == "Root"

    def test_missing_parent_still_creates_child(self, store):
        """Child context with a nonexistent parent_context_id still works (orphaned)."""
        child = store.create(
            name="Orphan",
            constraints=["C1"],
            variables={"v": 1},
            parent_context_id="ctx_nonexistent_parent",
        )

        assert child["context_id"].startswith("ctx_")
        assert child["name"] == "Orphan"
        assert child["constraints"] == ["C1"]
        assert child["variables"] == {"v": 1}
        # Should be retrievable
        fetched = store.get(child["context_id"])
        assert fetched is not None

    # ── diff ──

    def test_diff_between_versions_shows_changes(self, store):
        """diff() between two versions of the same context shows what changed."""
        ctx = store.create(
            name="Diff Test",
            goal="original goal",
            constraints=["A", "B"],
            variables={"x": 1, "y": 2},
            task_scope="old-scope",
        )
        store.update(
            ctx["context_id"],
            goal="updated goal",
            constraints=["A", "C"],
            variables={"x": 1, "z": 3},
            task_scope="new-scope",
            reason="Changed",
        )

        result = store.diff(ctx["context_id"], version_a=2, version_b=1)

        assert result["goal_changed"] is True
        assert result["scope_changed"] is True
        assert set(result["constraints_added"]) == {"C"}
        assert set(result["constraints_removed"]) == {"B"}
        assert set(result["variables_added"]) == {"z"}
        assert set(result["variables_removed"]) == {"y"}
        assert result["identical"] is False
        assert result["context_a"]["id"] == ctx["context_id"]
        assert result["context_b"]["id"] == ctx["context_id"]

    def test_diff_same_version_identical(self, store):
        """diff() between identical versions returns identical=True."""
        ctx = store.create(name="Same")
        store.update(ctx["context_id"], name="Changed", reason="...")

        # Compare v2 against itself
        result = store.diff(ctx["context_id"], version_a=2, version_b=2)

        assert result["identical"] is True

    def test_diff_single_version_fallback(self, store):
        """diff() without versions compares current vs previous automatically."""
        ctx = store.create(name="Only V1")

        result = store.diff(ctx["context_id"])

        assert result["single_version"] is True
        assert result["context_b"] is None
        assert result["identical"] is True
        assert result["context_a"]["name"] == "Only V1"

    def test_diff_two_different_contexts(self, store):
        """diff() between two different context IDs works."""
        ctx_a = store.create(name="Context A", constraints=["A1"], variables={"a": 1})
        ctx_b = store.create(name="Context B", constraints=["B1"], variables={"b": 2})

        result = store.diff(ctx_a["context_id"], context_id_b=ctx_b["context_id"])

        assert result["context_a"]["name"] == "Context A"
        assert result["context_b"]["name"] == "Context B"
        assert result["identical"] is False

    def test_diff_nonexistent_context_raises(self, store):
        """diff() raises ContextStoreError for nonexistent context."""
        with pytest.raises(ContextStoreError, match="Context not found"):
            store.diff("ctx_nonexistent")
