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
import sys
import threading
from pathlib import Path
from typing import Any

import yaml

from core.models import CapabilityEntry, CapabilityManifest
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
        # Marketplace metadata — BluePrint Layer 6 (Interoperability)
        # {name@version: dict}
        self._marketplace: dict[str, CapabilityEntry] = {}
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
        # BluePrint Layer 6 — Interoperability: marketplace metadata columns.
        # Safe migration — add columns only if they don't already exist.
        for col, col_def in [
            ("visibility", "TEXT NOT NULL DEFAULT 'private'"),
            ("usage_count", "INTEGER NOT NULL DEFAULT 0"),
            ("rating", "REAL NOT NULL DEFAULT 0.0"),
            ("verified", "INTEGER NOT NULL DEFAULT 0"),
            ("updated_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
        ]:
            try:
                conn.execute(f"ALTER TABLE capabilities ADD COLUMN {col} {col_def}")
            except sqlite3.OperationalError:
                pass  # Column already exists — skip
        conn.commit()
        conn.close()

    def _load_from_db(self) -> None:
        """Load all capabilities from SQLite into memory."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT manifest_yaml, visibility, publisher, usage_count, rating,"
            "       verified, created_at, updated_at"
            " FROM capabilities ORDER BY name, version"
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
                # Load marketplace metadata (BluePrint Layer 6)
                self._marketplace[cap_id] = CapabilityEntry(
                    capability_id=cap_id,
                    manifest_yaml=row["manifest_yaml"],
                    publisher=row["publisher"] or "",
                    visibility=row["visibility"] if "visibility" in row.keys() else "private",
                    verified=bool(row["verified"]) if "verified" in row.keys() else False,
                    usage_count=row["usage_count"] if "usage_count" in row.keys() else 0,
                    rating=row["rating"] if "rating" in row.keys() else 0.0,
                    created_at=row["created_at"] if "created_at" in row.keys() else "",
                    updated_at=row["updated_at"] if "updated_at" in row.keys() else "",
                )
            except Exception as e:
                sys.stderr.write(f"Warning: {e}\n")  # Skip corrupted entries
        conn.close()

    def _save_to_db(
        self,
        manifest: CapabilityManifest,
        visibility: str = "private",
        publisher: str | None = None,
        verified: bool = False,
    ) -> None:
        """Persist a single capability to SQLite with marketplace metadata."""
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
                   (name, version, publisher, description, manifest_yaml,
                    visibility, verified, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    manifest.name,
                    manifest.version,
                    manifest.metadata.publisher,
                    manifest.metadata.description,
                    manifest_yaml,
                    visibility,
                    1 if verified else 0,
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
                self._marketplace.pop(key, None)
                if name in self._versions and version in self._versions[name]:
                    self._versions[name].remove(version)
                self._remove_from_db(name, version)
            else:
                if name not in self._versions:
                    raise RegistryError(f"No capabilities registered under name '{name}'")
                for ver in list(self._versions.get(name, [])):
                    key = f"{name}@{ver}"
                    self._manifests.pop(key, None)
                    self._marketplace.pop(key, None)
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
            List of summary dicts with name, version, publisher, description,
            and marketplace metadata.
        """
        with self._lock:
            results = []
            for manifest in self._manifests.values():
                entry = self._marketplace.get(manifest.id)
                results.append({
                    "name": manifest.name,
                    "version": manifest.version,
                    "id": manifest.id,
                    "publisher": manifest.metadata.publisher,
                    "description": manifest.metadata.description,
                    "tags": manifest.metadata.tags,
                    "visibility": entry.visibility if entry else "private",
                    "usage_count": entry.usage_count if entry else 0,
                    "rating": entry.rating if entry else 0.0,
                    "verified": entry.verified if entry else False,
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
        visibility: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search capabilities by free-text query with semantic ranking.

        Uses TF-IDF vectorization and cosine similarity — no external
        dependencies, no API calls, fully offline.

        Args:
            query: Free-text search query.
            limit: Maximum number of results.
            min_score: Minimum similarity score threshold (0.0–1.0).
            visibility: Optional filter — 'public', 'team', or 'private'.

        Returns:
            List of result dicts, each with:
              - capability: capability summary dict
              - score: similarity score (0.0–1.0)
            Sorted by descending score. Empty list if no matches.
        """
        with self._lock:
            if self._search_dirty:
                self._rebuild_search_index()
            results = self._search_index.search(
                query=query, limit=limit if not visibility else max(limit * 3, 30),
                min_score=min_score,
            )
            # Apply visibility filter post-search (BluePrint Layer 6)
            if visibility:
                filtered = []
                for r in results:
                    cap = r["capability"]
                    cap_id = cap.get("id") or f"{cap.get('name')}@{cap.get('version')}"
                    entry = self._marketplace.get(cap_id)
                    cap_visibility = entry.visibility if entry else "private"
                    if visibility == cap_visibility:
                        filtered.append(r)
                    if len(filtered) >= limit:
                        break
                return filtered
            return results

    # ── Marketplace (BluePrint Layer 6 — Interoperability) ──

    def publish(
        self,
        manifest: CapabilityManifest,
        visibility: str = "public",
        publisher: str | None = None,
        verified: bool = False,
    ) -> CapabilityEntry:
        """Publish a capability to the marketplace.

        Registers the manifest and attaches marketplace metadata
        (visibility, publisher, rating, verified status).

        Args:
            manifest: Parsed and validated CapabilityManifest.
            visibility: 'public', 'team', or 'private'.
            publisher: Who is publishing (Agent ID, Org ID, or username).
            verified: Whether the capability has been verified.

        Returns:
            Marketplace entry dict.

        Raises:
            RegistryError: If the capability is already published.
            ValueError: If visibility is invalid.
        """
        if visibility not in ("public", "team", "private"):
            raise ValueError(
                f"Invalid visibility '{visibility}'. Must be public, team, or private."
            )

        with self._lock:
            if manifest.id in self._manifests:
                raise RegistryError(
                    f"Capability '{manifest.id}' is already registered. "
                    "Use a new version or unregister first."
                )

            # Register the manifest in-memory
            self._manifests[manifest.id] = manifest
            if manifest.name not in self._versions:
                self._versions[manifest.name] = []
            if manifest.version not in self._versions[manifest.name]:
                self._versions[manifest.name].append(manifest.version)
                self._versions[manifest.name].sort()

            # Store marketplace metadata as CapabilityEntry
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()

            # Serialize manifest to YAML for CapabilityEntry
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

            self._marketplace[manifest.id] = CapabilityEntry(
                capability_id=manifest.id,
                manifest_yaml=manifest_yaml,
                publisher=publisher or "",
                visibility=visibility,
                usage_count=0,
                rating=0.0,
                verified=verified,
                created_at=now,
                updated_at=now,
            )

            # Invalidate search index
            self._search_dirty = True

            # Persist to SQLite with marketplace metadata
            self._save_to_db(
                manifest,
                visibility=visibility,
                publisher=publisher,
                verified=verified,
            )

        return self._marketplace[manifest.id]

    def get_entry(self, capability_id: str) -> CapabilityEntry | None:
        """Get a CapabilityEntry from the marketplace.

        Args:
            capability_id: 'name@version' formatted identifier.

        Returns:
            CapabilityEntry if found in the marketplace, or None.
        """
        with self._lock:
            entry = self._marketplace.get(capability_id)
            if entry is not None:
                return entry
            # Try parsing as name@version in case the id format differs
            if "@" in capability_id:
                name, version = capability_id.rsplit("@", 1)
                entry = self._marketplace.get(f"{name}@{version}")
            return entry

    def record_usage(self, capability_id: str) -> None:
        """Increment usage_count on a marketplace entry.

        Called from the capability execution path to track how often
        each capability is used.  Silently returns when *capability_id*
        is not in the marketplace.

        Args:
            capability_id: ``name@version`` formatted identifier.
        """
        with self._lock:
            entry = self._marketplace.get(capability_id)
            if entry is None:
                return

            entry.usage_count += 1
            from datetime import datetime, timezone
            entry.updated_at = datetime.now(timezone.utc).isoformat()

            # Persist to SQLite if enabled
            if self._db_path is not None:
                conn = self._get_conn()
                try:
                    conn.execute(
                        """UPDATE capabilities
                           SET usage_count = ?,
                               updated_at = ?
                         WHERE name || '@' || version = ?""",
                        (entry.usage_count, entry.updated_at, capability_id),
                    )
                    conn.commit()
                finally:
                    conn.close()

    def save_snapshot(self, path: str | Path) -> Path:
        """Export all registered capabilities as a JSON snapshot file."""
        path = Path(path)
        data = []
        for manifest in self._manifests.values():
            entry = self._marketplace.get(manifest.id)
            data.append({
                "name": manifest.name,
                "version": manifest.version,
                "id": manifest.id,
                "publisher": manifest.metadata.publisher,
                "description": manifest.metadata.description,
                "tags": manifest.metadata.tags,
                "visibility": entry.visibility if entry else "private",
                "usage_count": entry.usage_count if entry else 0,
                "rating": entry.rating if entry else 0.0,
                "verified": entry.verified if entry else False,
                "created_at": entry.created_at if entry else "",
                "updated_at": entry.updated_at if entry else "",
            })
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path
