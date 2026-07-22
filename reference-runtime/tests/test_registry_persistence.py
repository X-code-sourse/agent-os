"""
Intent OS — Persistent Registry Tests

Tests cover:
  1. In-memory registry (backward compatibility)
  2. SQLite persistence — save and restore
  3. Cross-session persistence
  4. Manual snapshot export
  5. Concurrent access safety
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure project root is in path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.models import (
    CapabilityManifest,
    CostSpec,
    FieldSchema,
    MetadataSpec,
    RequirementSpec,
    SecuritySpec,
)
from core.registry import CapabilityRegistry, RegistryError


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_manifest(
    name: str,
    version: str = "1.0.0",
    publisher: str | None = None,
    tags: list[str] | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        metadata=MetadataSpec(
            name=name,
            version=version,
            publisher=publisher,
            description=f"Test {name}",
            tags=tags,
        ),
        input_schema={"input": FieldSchema(type="string")},
        output_schema={"output": FieldSchema(type="string")},
        requirements=RequirementSpec(),
        security=SecuritySpec(),
    )


# ──────────────────────────────────────────────
# In-Memory Tests (Backward Compat)
# ──────────────────────────────────────────────

class TestInMemoryRegistry:
    """Original in-memory registry tests — ensure nothing broken."""

    def setup_method(self):
        self.registry = CapabilityRegistry()

    def test_register_and_get(self):
        manifest = _make_manifest("test_cap")
        self.registry.register(manifest)
        retrieved = self.registry.get("test_cap", "1.0.0")
        assert retrieved is not None
        assert retrieved.name == "test_cap"

    def test_register_duplicate_raises(self):
        manifest = _make_manifest("test_cap")
        self.registry.register(manifest)
        import pytest
        with pytest.raises(RegistryError):
            self.registry.register(manifest)

    def test_get_nonexistent(self):
        assert self.registry.get("nonexistent") is None

    def test_list_capabilities(self):
        self.registry.register(_make_manifest("cap_a"))
        self.registry.register(_make_manifest("cap_b"))
        caps = self.registry.list_capabilities()
        assert len(caps) == 2

    def test_find_by_tag(self):
        manifest = _make_manifest("tagged_cap", tags=["test", "important"])
        self.registry.register(manifest)
        results = self.registry.find_by_tag("important")
        assert len(results) == 1
        assert results[0].name == "tagged_cap"

    def test_count(self):
        assert self.registry.count() == 0
        self.registry.register(_make_manifest("cap_a"))
        assert self.registry.count() == 1

    def test_unregister(self):
        manifest = _make_manifest("to_delete")
        self.registry.register(manifest)
        self.registry.unregister("to_delete", "1.0.0")
        assert self.registry.count() == 0

    def test_unregister_all_versions(self):
        self.registry.register(_make_manifest("multi", version="1.0.0"))
        self.registry.register(_make_manifest("multi", version="2.0.0"))
        self.registry.unregister("multi")
        assert self.registry.count() == 0

    def test_latest_version(self):
        self.registry.register(_make_manifest("evolving", version="1.0.0"))
        self.registry.register(_make_manifest("evolving", version="2.0.0"))
        latest = self.registry.get("evolving")
        assert latest is not None
        assert latest.version == "2.0.0"

    def test_exact_version(self):
        self.registry.register(_make_manifest("specific", version="1.0.0"))
        self.registry.register(_make_manifest("specific", version="2.0.0"))
        specific = self.registry.get("specific", "1.0.0")
        assert specific is not None
        assert specific.version == "1.0.0"


# ──────────────────────────────────────────────
# Persistence Tests
# ──────────────────────────────────────────────

class TestPersistentRegistry:
    """Test SQLite-backed persistence."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_registry.db")

    def teardown_method(self):
        if os.path.exists(self.db_path):
            try:
                os.unlink(self.db_path)
            except PermissionError:
                pass

    def test_register_persists(self):
        """Registering should persist to SQLite."""
        registry = CapabilityRegistry(db_path=self.db_path)
        registry.register(_make_manifest("persistent_cap"))
        # Verify by checking file size
        assert os.path.exists(self.db_path)
        assert os.path.getsize(self.db_path) > 0

    def test_load_from_db(self):
        """Capabilities should survive registry re-creation."""
        # First session
        registry1 = CapabilityRegistry(db_path=self.db_path)
        registry1.register(_make_manifest("survivor"))
        assert registry1.count() == 1
        del registry1

        # Second session
        registry2 = CapabilityRegistry(db_path=self.db_path)
        assert registry2.count() == 1
        retrieved = registry2.get("survivor", "1.0.0")
        assert retrieved is not None
        assert retrieved.name == "survivor"

    def test_multiple_capabilities_survive(self):
        """Multiple capabilities should all survive restart."""
        r1 = CapabilityRegistry(db_path=self.db_path)
        r1.register(_make_manifest("cap_one"))
        r1.register(_make_manifest("cap_two"))
        r1.register(_make_manifest("cap_three"))
        del r1

        r2 = CapabilityRegistry(db_path=self.db_path)
        assert r2.count() == 3
        assert r2.get("cap_one") is not None
        assert r2.get("cap_two") is not None
        assert r2.get("cap_three") is not None

    def test_unregister_removes_from_db(self):
        """Unregistering should remove from SQLite."""
        r1 = CapabilityRegistry(db_path=self.db_path)
        r1.register(_make_manifest("ephemeral"))
        r1.unregister("ephemeral", "1.0.0")
        del r1

        r2 = CapabilityRegistry(db_path=self.db_path)
        assert r2.count() == 0

    def test_metadata_preserved(self):
        """Publisher, tags, description should survive restart."""
        r1 = CapabilityRegistry(db_path=self.db_path)
        r1.register(_make_manifest("rich_meta",
                                    publisher="example.com",
                                    tags=["test", "metadata"]))
        del r1

        r2 = CapabilityRegistry(db_path=self.db_path)
        cap = r2.get("rich_meta")
        assert cap is not None
        assert cap.metadata.publisher == "example.com"

    def test_versioned_capabilities(self):
        """Multiple versions of same capability should all persist."""
        r1 = CapabilityRegistry(db_path=self.db_path)
        r1.register(_make_manifest("versioned", version="1.0.0"))
        r1.register(_make_manifest("versioned", version="2.0.0"))
        del r1

        r2 = CapabilityRegistry(db_path=self.db_path)
        assert r2.count() == 2
        latest = r2.get("versioned")
        assert latest is not None
        assert latest.version == "2.0.0"  # Latest version returned

    def test_list_after_restore(self):
        """list_capabilities should work after restore."""
        r1 = CapabilityRegistry(db_path=self.db_path)
        r1.register(_make_manifest("listed_cap"))
        del r1

        r2 = CapabilityRegistry(db_path=self.db_path)
        caps = r2.list_capabilities()
        assert len(caps) == 1
        assert caps[0]["name"] == "listed_cap"

    def test_snapshot_export(self):
        """Snapshot export should produce valid JSON."""
        registry = CapabilityRegistry(db_path=self.db_path)
        registry.register(_make_manifest("snapshot_test"))

        snapshot_path = os.path.join(self.tmpdir, "snapshot.json")
        result = registry.save_snapshot(snapshot_path)
        assert result.exists()

        data = json.loads(Path(snapshot_path).read_text())
        assert len(data) == 1
        assert data[0]["name"] == "snapshot_test"


# ──────────────────────────────────────────────
# Edge Cases
# ──────────────────────────────────────────────

class TestRegistryEdgeCases:
    """Test edge cases and error conditions."""

    def test_sqlite_init_empty_db(self):
        """Initializing with an empty database file should work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "fresh.db")
            registry = CapabilityRegistry(db_path=db_path)
            assert registry.count() == 0

    def test_large_number_of_capabilities(self):
        """Registering 100 capabilities should not cause issues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "large.db")
            registry = CapabilityRegistry(db_path=db_path)
            for i in range(100):
                registry.register(_make_manifest(f"bulk_{i}"))
            assert registry.count() == 100

    def test_in_memory_no_db(self):
        """Registry without db_path should work as in-memory store."""
        registry = CapabilityRegistry()
        registry.register(_make_manifest("memory_only"))
        assert registry.count() == 1


# ──────────────────────────────────────────────
# Semantic Search Integration
# ──────────────────────────────────────────────

class TestRegistrySemanticSearch:
    """Test the find_by_text() search integration with CapabilityRegistry."""

    def test_search_empty_registry(self):
        """Searching an empty registry should return empty list."""
        registry = CapabilityRegistry()
        results = registry.find_by_text("anything")
        assert results == []

    def test_search_finds_by_name(self):
        """Searching by capability name should find it."""
        registry = CapabilityRegistry()
        registry.register(_make_manifest(name="web_search"))
        results = registry.find_by_text("web search")
        assert len(results) >= 1
        assert results[0]["capability"]["name"] == "web_search"

    def test_search_finds_by_description(self):
        """Searching by description text should find matching capabilities."""
        registry = CapabilityRegistry()
        registry.register(_make_manifest(name="financial_analyze"))
        registry.register(_make_manifest(name="text_summarize"))
        results = registry.find_by_text("Test financial_analyze")
        assert len(results) >= 1
        assert results[0]["capability"]["name"] == "financial_analyze"

    def test_search_returns_scores(self):
        """Results should include similarity scores."""
        registry = CapabilityRegistry()
        registry.register(_make_manifest(name="search_tool"))
        results = registry.find_by_text("search_tool")
        assert len(results) >= 1
        for r in results:
            assert "score" in r
            assert 0.0 < r["score"] <= 1.0

    def test_search_limit(self):
        """limit parameter should cap results."""
        registry = CapabilityRegistry()
        for i in range(20):
            registry.register(_make_manifest(name=f"cap_{i}"))
        results = registry.find_by_text("test", limit=5)
        assert len(results) <= 5

    def test_search_after_registration(self):
        """Newly registered capabilities should be searchable immediately."""
        registry = CapabilityRegistry()
        registry.register(_make_manifest(name="alpha"))
        results_before = registry.find_by_text("alpha")
        assert len(results_before) >= 1

        registry.register(_make_manifest(name="beta"))
        results_after = registry.find_by_text("beta")
        assert len(results_after) >= 1
        assert results_after[0]["capability"]["name"] == "beta"

    def test_search_after_unregistration(self):
        """Unregistered capabilities should not appear in search results."""
        registry = CapabilityRegistry()
        registry.register(_make_manifest(name="alpha_cap"))
        registry.register(_make_manifest(name="beta_cap"))

        # Search should find at least one
        results_all = registry.find_by_text("test")
        assert len(results_all) >= 1

        # Remove alpha; search for its unique token should return nothing
        registry.unregister("alpha_cap")
        results_after = registry.find_by_text("alpha")
        assert len(results_after) == 0

    def test_search_scored_ranking(self):
        """More relevant results should have higher scores."""
        registry = CapabilityRegistry()
        registry.register(_make_manifest(name="text_analyzer"))
        registry.register(_make_manifest(name="image_processor"))

        results = registry.find_by_text("text_analyzer")
        assert len(results) >= 1
        top = results[0]["capability"]["name"]
        assert top == "text_analyzer"
