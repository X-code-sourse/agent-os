"""
Intent OS — Experience Store (BluePrint Layer 7 — Evolution)

SQLite-backed persistent store for learned experiences.

Experiences capture patterns, strategies, and insights discovered during
Agent execution. They feed back into the Evolution Loop to improve
future decision-making.

Each Experience links to one or more source Executions and is scoped
to an Agent, domain, and type.

Usage:
    store = ExperienceStore()
    exp = store.create(
        agent_id="agent_abc123",
        type="failure_pattern",
        observation="Timeouts when API called during market open",
        recommendation="Queue requests during 9:30-10:00 ET",
        domain="finance",
        tags=["api", "rate-limit", "market-hours"],
    )
    store.list(agent_id="agent_abc123")
    store.query_by_task("analyze quarterly earnings", domain="finance")
    store.record_usage("exp_abc", success=True)
    store.update_validation("exp_abc")
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import Experience, _VALID_EXPERIENCE_TYPES

# Default database path
EXPERIENCE_DB = str(Path.home() / ".intent-os" / "experience.db")

# Current schema version — bump when columns are added
_SCHEMA_VERSION = 1

CREATE_EXPERIENCES_TABLE = """
CREATE TABLE IF NOT EXISTS experiences (
    experience_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    source_executions TEXT NOT NULL DEFAULT '[]',
    type TEXT NOT NULL DEFAULT '',
    observation TEXT NOT NULL DEFAULT '',
    recommendation TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    domain TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%Sf','now')),
    last_validated_at TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0,
    success_rate_when_applied REAL NOT NULL DEFAULT 0.0,
    expires_at TEXT
);
"""

CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS _schema_version (
    version INTEGER NOT NULL
);
"""


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


class ExperienceStoreError(Exception):
    """Raised when Experience Store operations fail."""
    pass


class ExperienceStore:
    """SQLite-backed Experience Store with thread-safe operations.

    Follows the same connection pattern as EvidenceStore and ContextStore — new
    connection per operation, closed immediately after.  Adds a threading Lock
    for write operations so concurrent callers cannot corrupt the database.

    Usage:
        store = ExperienceStore()
        exp = store.create(
            agent_id="agent_abc123",
            type="failure_pattern",
            observation="Timeouts when API called during market open",
            recommendation="Queue requests during 9:30-10:00 ET",
            domain="finance",
            tags=["api", "rate-limit", "market-hours"],
        )
        store.list(agent_id="agent_abc123")
        store.query_by_task("analyze quarterly earnings", domain="finance")
        store.record_usage("exp_abc", success=True)
        store.update_validation("exp_abc")
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = str(db_path or EXPERIENCE_DB)
        self._lock = threading.Lock()
        self._shared_conn: sqlite3.Connection | None = None
        if self._db_path == ":memory:":
            Path.home().mkdir(parents=True, exist_ok=True)
        else:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema and run migrations."""
        conn = self._get_conn()
        try:
            conn.execute(CREATE_EXPERIENCES_TABLE)
            conn.execute(CREATE_SCHEMA_VERSION)
            self._run_migrations(conn)
            conn.commit()
        finally:
            if self._db_path != ":memory:":
                self._close_conn(conn)

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection. For :memory: DBs, reuses the same connection."""
        if self._db_path == ":memory:":
            if self._shared_conn is None:
                self._shared_conn = sqlite3.connect(self._db_path, timeout=30)
                self._shared_conn.row_factory = sqlite3.Row
            return self._shared_conn
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _close_conn(self, conn: sqlite3.Connection) -> None:
        """Close a connection, unless it is the shared :memory: connection."""
        if self._db_path != ":memory:":
            self._close_conn(conn)

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        """Run any pending schema migrations.

        Checks the stored schema version against ``_SCHEMA_VERSION`` and
        applies any missing column additions.  Future versions can add
        new ``ALTER TABLE`` blocks keyed by version number.
        """
        cursor = conn.execute("SELECT MAX(version) FROM _schema_version")
        row = cursor.fetchone()
        current = row[0] if row and row[0] is not None else 0

        if current < _SCHEMA_VERSION:
            # Get existing columns so we only ADD what's missing
            cursor = conn.execute("PRAGMA table_info(experiences)")
            existing_cols = {r["name"] for r in cursor.fetchall()}

            # ── Migration: schema version 1 (baseline) ──
            # Handled by CREATE TABLE IF NOT EXISTS above.

            # ── Future migration template ──
            # if current < 2 and "new_field" not in existing_cols:
            #     conn.execute(
            #         "ALTER TABLE experiences ADD COLUMN new_field TEXT NOT NULL DEFAULT ''"
            #     )

            # Record latest schema version
            conn.execute("DELETE FROM _schema_version")
            conn.execute(
                "INSERT INTO _schema_version (version) VALUES (?)",
                (_SCHEMA_VERSION,),
            )

    # ── Helpers ──

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a database row to a dict with deserialized JSON fields."""
        return {
            "experience_id": row["experience_id"],
            "agent_id": row["agent_id"],
            "source_executions": _json_loads(row["source_executions"]),
            "type": row["type"],
            "observation": row["observation"],
            "recommendation": row["recommendation"],
            "confidence": row["confidence"],
            "domain": row["domain"],
            "tags": _json_loads(row["tags"]),
            "created_at": row["created_at"],
            "last_validated_at": row["last_validated_at"],
            "usage_count": row["usage_count"],
            "success_rate_when_applied": row["success_rate_when_applied"],
            "expires_at": row["expires_at"],
        }

    # ── CRUD ──

    def create(
        self,
        agent_id: str,
        type: str,
        observation: str,
        recommendation: str = "",
        source_executions: list[str] | None = None,
        confidence: float = 0.0,
        domain: str = "",
        tags: list[str] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a new experience record.

        Args:
            agent_id: The agent that generated this experience.
            type: One of ``failure_pattern``, ``success_strategy``,
                ``tool_preference``, ``model_performance``,
                ``data_source_reliability``, ``environment_constraint``,
                ``user_feedback``.
            observation: What was observed.
            recommendation: Suggested action based on this experience.
            source_executions: List of execution IDs that produced this
                experience.
            confidence: How confident (0.0–1.0) the system is in this
                experience.
            domain: Domain this experience applies to (e.g. ``"finance"``,
                ``"healthcare"``).
            tags: Categorization tags.
            expires_at: ISO 8601 timestamp when this experience expires.

        Returns:
            A dict representation of the created experience.

        Raises:
            ExperienceStoreError: If *type* is not one of the valid values.
        """
        if type not in _VALID_EXPERIENCE_TYPES:
            raise ExperienceStoreError(
                f"Invalid experience type '{type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_EXPERIENCE_TYPES))}"
            )

        exp_id = f"exp_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        src_execs = source_executions or []
        tag_list = tags or []

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO experiences
                       (experience_id, agent_id, source_executions, type,
                        observation, recommendation, confidence, domain, tags,
                        created_at, last_validated_at, usage_count,
                        success_rate_when_applied, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, 0.0, ?)""",
                    (
                        exp_id,
                        agent_id,
                        _json_dumps(src_execs),
                        type,
                        observation,
                        recommendation,
                        confidence,
                        domain,
                        _json_dumps(tag_list),
                        now,
                        expires_at,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ExperienceStoreError(
                    f"Experience creation failed: {exc}"
                ) from exc
            finally:
                self._close_conn(conn)

        return {
            "experience_id": exp_id,
            "agent_id": agent_id,
            "source_executions": src_execs,
            "type": type,
            "observation": observation,
            "recommendation": recommendation,
            "confidence": confidence,
            "domain": domain,
            "tags": tag_list,
            "created_at": now,
            "last_validated_at": None,
            "usage_count": 0,
            "success_rate_when_applied": 0.0,
            "expires_at": expires_at,
        }

    def get(self, experience_id: str) -> dict[str, Any] | None:
        """Look up a single experience by ID.

        Args:
            experience_id: The experience to retrieve.

        Returns:
            A dict of the experience, or ``None`` if not found.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM experiences WHERE experience_id = ?",
                (experience_id,),
            )
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            self._close_conn(conn)

    def list(
        self,
        agent_id: str | None = None,
        type: str | None = None,
        domain: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List experiences with optional filters.

        Args:
            agent_id: Filter by agent ID (exact match).
            type: Filter by experience type (exact match).
            domain: Filter by domain (case-insensitive substring match).
            limit: Maximum number of results to return.

        Returns:
            List of experience dicts ordered by ``created_at`` descending.
        """
        clauses: list[str] = []
        params: list[Any] = []

        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if type:
            clauses.append("type = ?")
            params.append(type)
        if domain:
            clauses.append("domain LIKE ?")
            params.append(f"%{domain}%")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            f"SELECT * FROM experiences {where} "
            f"ORDER BY created_at DESC LIMIT ?"
        )
        params.append(limit)

        conn = self._get_conn()
        try:
            cursor = conn.execute(query, params)
            return [self._row_to_dict(row) for row in cursor.fetchall()]
        finally:
            self._close_conn(conn)

    def query_by_task(
        self,
        goal: str,
        domain: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Query experiences relevant to a task by keyword matching.

        Splits the *goal* text into keywords (words of 3+ characters) and
        matches them against ``observation``, ``recommendation``, ``type``,
        and ``tags`` using ``LIKE``.  Any keyword hit counts — AND logic is
        not required.

        Results are ranked by ``confidence * success_rate_when_applied`` so
        that validated, effective experiences surface first.

        Args:
            goal: Task goal text to match against.
            domain: Optional domain filter (case-insensitive substring).
            limit: Maximum number of results.

        Returns:
            List of matching experience dicts, ordered by relevance descending.
        """
        # Extract keywords from goal — words with 3+ characters
        keywords = [
            w.strip().lower()
            for w in goal.split()
            if len(w.strip()) >= 3
        ]
        if not keywords:
            # Fallback: use the whole trimmed goal if no words pass the filter
            trimmed = goal.strip()
            keywords = [trimmed.lower()] if trimmed else []

        # Build OR chains: each keyword × each searchable column
        or_clauses: list[str] = []
        params: list[Any] = []
        search_cols = ["observation", "recommendation", "type", "tags"]

        for kw in keywords:
            for col in search_cols:
                or_clauses.append(f"{col} LIKE ?")
                params.append(f"%{kw}%")

        if not or_clauses:
            return []

        where_clause = f"({' OR '.join(or_clauses)})"

        if domain:
            where_clause += " AND domain LIKE ?"
            params.append(f"%{domain}%")

        query = (
            f"SELECT * FROM experiences WHERE {where_clause} "
            f"ORDER BY (confidence * success_rate_when_applied) DESC, "
            f"usage_count DESC "
            f"LIMIT ?"
        )
        params.append(limit)

        conn = self._get_conn()
        try:
            cursor = conn.execute(query, params)
            return [self._row_to_dict(row) for row in cursor.fetchall()]
        finally:
            self._close_conn(conn)

    def update_validation(self, experience_id: str) -> bool:
        """Update the ``last_validated_at`` timestamp for an experience.

        Args:
            experience_id: The experience to mark as validated.

        Returns:
            ``True`` if the experience was found and updated, ``False``
            otherwise.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "UPDATE experiences SET last_validated_at = ? "
                    "WHERE experience_id = ?",
                    (now, experience_id),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                self._close_conn(conn)

    def record_usage(
        self,
        experience_id: str,
        success: bool = True,
    ) -> bool:
        """Record an experience usage event.

        Increments ``usage_count`` and updates ``success_rate_when_applied``
        using a rolling average:

            new_rate = (old_rate * old_count + (1 if success else 0)) / new_count

        Args:
            experience_id: The experience that was applied.
            success: Whether applying the experience led to a successful
                outcome.

        Returns:
            ``True`` if the experience was found and updated, ``False``
            otherwise.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "SELECT usage_count, success_rate_when_applied "
                    "FROM experiences WHERE experience_id = ?",
                    (experience_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return False

                old_count = row["usage_count"]
                old_rate = row["success_rate_when_applied"]

                new_count = old_count + 1
                success_value = 1.0 if success else 0.0
                new_rate = (
                    (old_rate * old_count + success_value) / new_count
                )

                conn.execute(
                    "UPDATE experiences SET usage_count = ?, "
                    "success_rate_when_applied = ? "
                    "WHERE experience_id = ?",
                    (new_count, round(new_rate, 4), experience_id),
                )
                conn.commit()
                return True
            finally:
                self._close_conn(conn)

    def delete(self, experience_id: str) -> bool:
        """Delete an experience record.

        Args:
            experience_id: The experience to delete.

        Returns:
            ``True`` if the experience was found and deleted, ``False``
            otherwise.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM experiences WHERE experience_id = ?",
                    (experience_id,),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                self._close_conn(conn)
