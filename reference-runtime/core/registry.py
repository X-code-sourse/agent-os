"""
Intent OS — Capability Registry with Persistence

Provides capability registration, discovery, and lookup by name@version.
Supports both in-memory (fast) and SQLite-backed (persistent) modes.

Phase 0: In-memory only.
Phase 1: SQLite persistence added (current implementation).
Phase 2+: Semantic search, capability graph, federated registries.

Thread-safe for concurrent access.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import yaml

from core.models import CapabilityManifest
from core.parser import parse_manifest
from core.search import SearchIndex


class RegistryError(Exception):
    """Raised on registry operation failures."""
    pass


class CapabilityRegistry:
    """
    Thread-safe capability registry with optional SQLite persistence.

    Supports:
      - Register a capability (name@version)
      - Look up by exact name@version
      - Look up by name (returns latest version)
      - List all registered capabilities
      - Persist to SQLite and restore on restart
      - Discover by tag or filter
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        # {name@version: CapabilityManifest}
        self._manifests: dict[str, CapabilityManifest] = {}
        # {name: [version, ...]}
        self._versions: dict[str, list[str]] = {}
        self._db_path: Path | None = None

        # Semantic search index (lazy rebuild on first search after changes)
        self._search_index = SearchIndex()
        self._search_dirty = True

        # Initialize SQLite if a path is provided
        if db_path:
            self._db_path = Path(db_path)
            self._init_db()
            self._load_from_db()

    # ── Persistence ──

    def _get_conn(self) -> sqlite3.Connection:
        """Get a SQLite connection for persistence."""
        if not self._db_path:
            raise RegistryError("Persistence not enabled (no db_path provided)")
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize the SQLite table for capabilities."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS capabilities (
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                publisher TEXT,
                description TEXT,
                manifest_yaml TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (name, version)
            )
        """)
        conn.commit()
        conn.close()

    def _load_from_db(self) -> None:
        """Load all capabilities from SQLite into memory."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT manifest_yaml FROM capabilities ORDER BY name, version"
        )
        for row in cursor.fetchall():
            try:
                manifest, _ = parse_manifest(row["manifest_yaml"])
                cap_id = manifest.id
                self._manifests[cap_id] = manifest
                if manifest.name not in self._versions:
                    self._versions[manifest.name] = []
                if manifest.version not in self._versions[manifest.name]:
                    self._versions[manifest.name].append(manifest.version)
                    self._versions[manifest.name].sort()
            except Exception:
                pass  # Skip corrupted entries
        conn.close()

    def _save_to_db(self, manifest: CapabilityManifest) -> None:
        """Persist a single capability to SQLite."""
        if not self._db_path:
            return

        conn = self._get_conn()
        try:
            # Serialize manifest back to YAML
            manifest_dict = {
                "kind": "Capability",
                "metadata": {
                    "name": manifest.name,
                    "version": manifest.version,
                    "publisher": manifest.metadata.publisher,
                    "description": manifest.metadata.description,
                    "tags": manifest.metadata.tags,
                },
                "spec": {
                    "input": {
                        fn: {"type": fs.type, "description": fs.description}
                        for fn, fs in manifest.input_schema.items()
                    },
                    "output": {
                        fn: {"type": fs.type, "description": fs.description}
                        for fn, fs in manifest.output_schema.items()
                    },
                },
            }
            manifest_yaml = yaml.dump(manifest_dict, default_flow_style=False)

            conn.execute(
                """INSERT OR REPLACE INTO capabilities
                   (name, version, publisher, description, manifest_yaml)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    manifest.name,
                    manifest.version,
                    manifest.metadata.publisher,
                    manifest.metadata.description,
                    manifest_yaml,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _remove_from_db(self, name: str, version: str) -> None:
        """Remove a capability from SQLite."""
        if not self._db_path:
            return
        conn = self._get_conn()
        try:
            conn.execute(
                "DELETE FROM capabilities WHERE name = ? AND version = ?",
                (name, version),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Registry Operations (with persistence) ──

    def register(self, manifest: CapabilityManifest) -> None:
        """
        Register a capability manifest.

        Args:
            manifest: Parsed and validated CapabilityManifest.

        Raises:
            RegistryError: If the manifest is invalid or already registered.
        """
        if manifest.id in self._manifests:
            raise RegistryError(
                f"Capability '{manifest.id}' is already registered. "
                "Use a new version or unregister first."
            )

        with self._lock:
            self._manifests[manifest.id] = manifest
            if manifest.name not in self._versions:
                self._versions[manifest.name] = []
            if manifest.version not in self._versions[manifest.name]:
                self._versions[manifest.name].append(manifest.version)
                self._versions[manifest.name].sort()

            # Invalidate search index
            self._search_dirty = True

            # Persist to SQLite
            self._save_to_db(manifest)

    def unregister(self, name: str, version: str | None = None) -> None:
        """
        Unregister a capability.

        Args:
            name: Capability name.
            version: Specific version to remove, or None to remove all.

        Raises:
            RegistryError: If the capability is not found.
        """
        with self._lock:
            if version:
                key = f"{name}@{version}"
                if key not in self._manifests:
                    raise RegistryError(f"Capability '{key}' not found")
                del self._manifests[key]
                if name in self._versions and version in self._versions[name]:
                    self._versions[name].remove(version)
                self._remove_from_db(name, version)
            else:
                if name not in self._versions:
                    raise RegistryError(f"No capabilities registered under name '{name}'")
                for ver in list(self._versions.get(name, [])):
                    key = f"{name}@{ver}"
                    self._manifests.pop(key, None)
                    self._remove_from_db(name, ver)
                self._versions.pop(name, None)

            # Invalidate search index
            self._search_dirty = True

    def get(self, name: str, version: str | None = None) -> CapabilityManifest | None:
        """
        Look up a capability by name and optional version.

        Args:
            name: Capability name.
            version: Specific version, or None for the latest.

        Returns:
            CapabilityManifest, or None if not found.
        """
        with self._lock:
            if version:
                return self._manifests.get(f"{name}@{version}")

            # Return latest version
            versions = self._versions.get(name, [])
            if not versions:
                return None
            latest = versions[-1]
            return self._manifests.get(f"{name}@{latest}")

    def list_capabilities(self) -> list[dict[str, Any]]:
        """
        List all registered capabilities.

        Returns:
            List of summary dicts with name, version, publisher, description.
        """
        with self._lock:
            results = []
            for manifest in self._manifests.values():
                results.append({
                    "name": manifest.name,
                    "version": manifest.version,
                    "id": manifest.id,
                    "publisher": manifest.metadata.publisher,
                    "description": manifest.metadata.description,
                    "tags": manifest.metadata.tags,
                })
            return sorted(results, key=lambda x: x["id"])

    def find_by_tag(self, tag: str) -> list[CapabilityManifest]:
        """
        Find capabilities by tag.

        Args:
            tag: Tag to search for.

        Returns:
            List of matching CapabilityManifests.
        """
        with self._lock:
            results = []
            for manifest in self._manifests.values():
                if manifest.metadata.tags and tag in manifest.metadata.tags:
                    results.append(manifest)
            return results

    def count(self) -> int:
        """Return the number of registered capabilities."""
        with self._lock:
            return len(self._manifests)

    # ── Semantic Search ──

    def _rebuild_search_index(self) -> None:
        """Rebuild the in-memory search index from current capabilities.

        Called lazily by find_by_text() when the index is dirty.
        Thread-safe: caller should hold self._lock.
        """
        docs = [
            {
                "id": manifest.id,
                "name": manifest.name,
                "description": manifest.metadata.description or "",
                "tags": manifest.metadata.tags or [],
                "publisher": manifest.metadata.publisher or "",
            }
            for manifest in self._manifests.values()
        ]
        self._search_index.build(docs)
        self._search_dirty = False

    def find_by_text(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Search capabilities by free-text query with semantic ranking.

        Uses TF-IDF vectorization and cosine similarity — no external
        dependencies, no API calls, fully offline.

        Args:
            query: Free-text search query.
            limit: Maximum number of results.
            min_score: Minimum similarity score threshold (0.0–1.0).

        Returns:
            List of result dicts, each with:
              - capability: capability summary dict
              - score: similarity score (0.0–1.0)
            Sorted by descending score. Empty list if no matches.
        """
        with self._lock:
            if self._search_dirty:
                self._rebuild_search_index()
            return self._search_index.search(
                query=query, limit=limit, min_score=min_score,
            )

    def save_snapshot(self, path: str | Path) -> Path:
        """Export all registered capabilities as a JSON snapshot file."""
        path = Path(path)
        data = []
        for manifest in self._manifests.values():
            data.append({
                "name": manifest.name,
                "version": manifest.version,
                "id": manifest.id,
                "publisher": manifest.metadata.publisher,
                "description": manifest.metadata.description,
                "tags": manifest.metadata.tags,
            })
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path
