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

from core.models import Experience, VALID_EXPERIENCE_TYPES

# Default database path
EXPERIENCE_DB = str(Path.home() / ".intent-os" / "intent.db")

# Current schema version — bump when columns are added
_SCHEMA_VERSION = 3

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
    expires_at TEXT,
    structured_situation TEXT NOT NULL DEFAULT '',
    structured_mistake TEXT NOT NULL DEFAULT '',
    structured_lesson TEXT NOT NULL DEFAULT '',
    structured_trigger TEXT NOT NULL DEFAULT '',
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    source_data TEXT NOT NULL DEFAULT '{}'
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
            conn.close()

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

            # ── Migration: schema version 2 (v0.10.0, SPEC-0010 structured fields) ──
            _STRUCTURED_COLS = [
                "structured_situation",
                "structured_mistake",
                "structured_lesson",
                "structured_trigger",
            ]
            for col in _STRUCTURED_COLS:
                if col not in existing_cols:
                    conn.execute(
                        f"ALTER TABLE experiences ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
                    )

            # ── Migration: schema version 3 (v0.15.0, code hygiene) ──
            _HYGIENE_COLS = ["occurrence_count", "source_data"]
            for col in _HYGIENE_COLS:
                if col not in existing_cols:
                    if col == "occurrence_count":
                        conn.execute(f"ALTER TABLE experiences ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
                    elif col == "source_data":
                        conn.execute(f"ALTER TABLE experiences ADD COLUMN {col} TEXT NOT NULL DEFAULT '{{}}'")

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
            "structured_situation": row["structured_situation"] if "structured_situation" in row.keys() else "",
            "structured_mistake": row["structured_mistake"] if "structured_mistake" in row.keys() else "",
            "structured_lesson": row["structured_lesson"] if "structured_lesson" in row.keys() else "",
            "structured_trigger": row["structured_trigger"] if "structured_trigger" in row.keys() else "",
            "occurrence_count": row["occurrence_count"] if "occurrence_count" in row.keys() else 0,
            "source_data": _json_loads(row["source_data"]) if "source_data" in row.keys() and isinstance(row["source_data"], str) else {},
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
        structured_situation: str = "",
        structured_mistake: str = "",
        structured_lesson: str = "",
        structured_trigger: str = "",
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
        if type not in VALID_EXPERIENCE_TYPES:
            raise ExperienceStoreError(
                f"Invalid experience type '{type}'. "
                f"Must be one of: {', '.join(sorted(VALID_EXPERIENCE_TYPES))}"
            )

        exp_id = f"exp_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        src_execs = source_executions or []
        tag_list = tags or []

        with self._lock:
            conn = self._get_conn()
            try:
                # ── Conflict resolution: if same agent + trigger exists, keep higher confidence ──
                if structured_trigger:
                    cursor = conn.execute(
                        """SELECT experience_id, confidence FROM experiences
                           WHERE agent_id = ? AND structured_trigger = ?
                           LIMIT 1""",
                        (agent_id, structured_trigger),
                    )
                    existing = cursor.fetchone()
                    if existing is not None and existing["confidence"] >= confidence:
                        # Existing experience is already as good or better — skip insert
                        self._close_conn(conn)
                        existing_full = self.get(existing["experience_id"])
                        return existing_full if existing_full else {
                            "experience_id": existing["experience_id"],
                            "agent_id": agent_id,
                            "type": type,
                            "observation": observation,
                        }
                    elif existing is not None:
                        # New experience has higher confidence — remove old one
                        conn.execute(
                            "DELETE FROM experiences WHERE experience_id = ?",
                            (existing["experience_id"],),
                        )

                conn.execute(
                    """INSERT INTO experiences
                       (experience_id, agent_id, source_executions, type,
                        observation, recommendation, confidence, domain, tags,
                        created_at, last_validated_at, usage_count,
                        success_rate_when_applied, expires_at,
                        structured_situation, structured_mistake,
                        structured_lesson, structured_trigger)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, 0.0, ?,
                               ?, ?, ?, ?)""",
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
                        structured_situation,
                        structured_mistake,
                        structured_lesson,
                        structured_trigger,
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
            "structured_situation": structured_situation,
            "structured_mistake": structured_mistake,
            "structured_lesson": structured_lesson,
            "structured_trigger": structured_trigger,
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
        sort_by: str | None = None,
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
        if sort_by == "confidence":
            order_clause = "confidence DESC, created_at DESC"
        elif sort_by == "usage":
            order_clause = "usage_count DESC, created_at DESC"
        else:
            order_clause = "created_at DESC"
        query = (
            f"SELECT * FROM experiences {where} "
            f"ORDER BY {order_clause} LIMIT ?"
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

    def get_by_context(
        self,
        context_id: str,
        limit: int = 50,
        event_store: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Return experiences linked to a specific execution context.

        Looks up all ``trace_id`` values from ``execution_records``
        that belong to *context_id*, then returns experiences whose
        ``source_executions`` JSON array contains at least one of
        those trace IDs.

        Args:
            context_id: The execution context to query.
            limit: Maximum number of experiences to return.
            event_store: An :class:`EventStore` instance used to query
                ``execution_records``.  If ``None``, the method returns
                an empty list gracefully.

        Returns:
            List of experience dicts ordered by ``created_at``
            descending.
        """
        if event_store is None:
            return []

        # ── Collect trace_ids belonging to this context ──
        try:
            ev_conn = event_store.get_connection()
        except AttributeError:
            return []

        trace_rows = ev_conn.execute(
            """SELECT DISTINCT trace_id
               FROM execution_records
               WHERE context_id = ?
                 AND trace_id IS NOT NULL""",
            (context_id,),
        ).fetchall()

        trace_ids = [r["trace_id"] for r in trace_rows]
        if not trace_ids:
            return []

        # ── Find experiences whose source_executions overlap ──
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM experiences ORDER BY created_at DESC"
            )
            all_rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        finally:
            self._close_conn(conn)

        matched: list[dict[str, Any]] = []
        trace_set = set(trace_ids)
        for exp in all_rows:
            src_execs = exp.get("source_executions") or []
            if isinstance(src_execs, list) and trace_set.intersection(src_execs):
                matched.append(exp)
                if len(matched) >= limit:
                    break

        return matched

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

    def find_by_observation(self, agent_id: str, observation: str) -> dict[str, Any] | None:
        """Find an experience by exact agent_id + observation match."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM experiences WHERE agent_id = ? AND observation = ? LIMIT 1",
                (agent_id, observation),
            )
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            self._close_conn(conn)

    def count(self) -> int:
        """Total number of stored experiences."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT COUNT(*) AS cnt FROM experiences")
            return cursor.fetchone()["cnt"]
        finally:
            conn.close()


    def save(self, exp) -> bool:
        """INSERT OR REPLACE an experience by experience_id.
        
        Accepts both dataclass instances and dicts.
        """
        from datetime import datetime, timezone
        if hasattr(exp, '__dataclass_fields__'):
            exp = exp.__dict__
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO experiences "
                "(experience_id, agent_id, type, observation, recommendation, "
                "confidence, domain, tags, created_at, usage_count, "
                "success_rate_when_applied, expires_at, "
                "structured_situation, structured_mistake, "
                "structured_lesson, structured_trigger, "
                "occurrence_count, source_data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    exp.get("experience_id", ""),
                    exp.get("agent_id", ""),
                    exp.get("type", ""),
                    exp.get("observation", ""),
                    exp.get("recommendation", ""),
                    float(exp.get("confidence", 0.0)),
                    exp.get("domain", ""),
                    _json_dumps(exp.get("tags", [])),
                    exp.get("created_at", "") or datetime.now(timezone.utc).isoformat(),
                    int(exp.get("usage_count", 0)),
                    float(exp.get("success_rate_when_applied", 0.0)),
                    exp.get("expires_at"),
                    exp.get("structured_situation", ""),
                    exp.get("structured_mistake", ""),
                    exp.get("structured_lesson", ""),
                    exp.get("structured_trigger", ""),
                    int(exp.get("occurrence_count", 0)),
                    _json_dumps(exp.get("source_data", {})),
                ),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            self._close_conn(conn)

    def update_tags(self, experience_id: str, tags: list[str]) -> bool:
        """Replace tags for an experience. Returns True if updated."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "UPDATE experiences SET tags = ? WHERE experience_id = ?",
                (_json_dumps(tags), experience_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            self._close_conn(conn)


    # ══ Memory management ────────────────────────────────────

    @staticmethod
    def compute_memory_score(confidence: float, usage_count: int,
                              created_at: str) -> float:
        """Score an experience's value (0.0–1.0) for retention decisions.

        Combines confidence, usage frequency, and recency:

            score = confidence * 0.4
                  + min(usage_count / 10, 1) * 0.3
                  + recency_factor * 0.3

        Where ``recency_factor`` decays from 1.0 (today) to 0.0 (≥30 days old).

        Args:
            confidence: 0.0–1.0 confidence score.
            usage_count: How many times this experience has been applied.
            created_at: ISO 8601 creation timestamp.

        Returns:
            A float between 0.0 and 1.0.
        """
        recency_factor = 0.0
        if created_at:
            try:
                from datetime import datetime, timezone
                from datetime import timedelta
                created = datetime.fromisoformat(created_at)
                days_old = (datetime.now(timezone.utc) - created).days
                recency_factor = max(0.0, min(1.0, (30 - days_old) / 30))
            except (ValueError, TypeError):
                pass

        return (
            confidence * 0.4
            + min(usage_count / 10, 1.0) * 0.3
            + recency_factor * 0.3
        )

    def prune(self, agent_id: str, keep: int = 50,
              min_score: float = 0.15, dry_run: bool = False) -> dict[str, Any]:
        """Prune low-value experiences for an agent.

        Keeps the top *keep* experiences by memory score, then also
        keeps any remaining experiences above *min_score*.  Deletes
        the rest.

        Args:
            agent_id: The agent whose experiences to prune.
            keep: Minimum number of high-value experiences to preserve
                (default 50).
            min_score: Experiences below this score AND outside the
                top *keep* are deleted (default 0.15).
            dry_run: If True, only report what would be deleted.

        Returns:
            A dict with ``deleted``, ``kept``, ``total``.
        """
        all_exps = self.list(agent_id=agent_id, limit=1000)

        if not all_exps:
            return {"total": 0, "deleted": 0, "kept": 0, "dry_run": dry_run}

        # Score and sort descending
        scored = sorted(
            (
                (exp, self.compute_memory_score(
                    confidence=float(exp.get("confidence", 0)),
                    usage_count=int(exp.get("usage_count", 0)),
                    created_at=exp.get("created_at", ""),
                ))
                for exp in all_exps
            ),
            key=lambda x: x[1],
            reverse=True,
        )

        # Keep top N, plus anything above threshold
        kept_ids: set[str] = {item[0]["experience_id"] for item in scored[:keep]}
        for exp, score in scored[keep:]:
            if score >= min_score:
                kept_ids.add(exp["experience_id"])

        # Everything else gets pruned
        prune_ids = [
            exp["experience_id"]
            for exp, _ in scored
            if exp["experience_id"] not in kept_ids
        ]

        result = {
            "total": len(all_exps),
            "deleted": len(prune_ids),
            "kept": len(all_exps) - len(prune_ids),
            "dry_run": dry_run,
        }

        if not dry_run and prune_ids:
            for pid in prune_ids:
                self.delete(pid)

        return result

    def memory_stats(self, agent_id: str) -> dict[str, Any]:
        """Return memory health statistics for an agent."""
        from datetime import datetime, timezone
        from statistics import mean

        all_exps = self.list(agent_id=agent_id, limit=10000)
        if not all_exps:
            return {
                "total": 0,
                "by_type": {},
                "avg_confidence": 0.0,
                "avg_usage_count": 0.0,
                "avg_memory_score": 0.0,
                "oldest_days": 0,
                "prune_candidates": 0,
            }

        by_type: dict[str, int] = {}
        confidences: list[float] = []
        usage_counts: list[int] = []
        scores: list[float] = []
        oldest = ""
        now = datetime.now(timezone.utc)

        for exp in all_exps:
            t = exp.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
            conf = float(exp.get("confidence", 0))
            confidences.append(conf)
            uc = int(exp.get("usage_count", 0))
            usage_counts.append(uc)
            score = self.compute_memory_score(conf, uc, exp.get("created_at", ""))
            scores.append(score)
            if not oldest or exp.get("created_at", "") < oldest:
                oldest = exp.get("created_at", "")

        oldest_days = 0
        if oldest:
            try:
                oldest_dt = datetime.fromisoformat(oldest)
                oldest_days = (now - oldest_dt).days
            except (ValueError, TypeError):
                pass

        prune_candidates = sum(1 for s in scores if s < 0.2)

        return {
            "total": len(all_exps),
            "by_type": by_type,
            "avg_confidence": round(mean(confidences), 4) if confidences else 0.0,
            "avg_usage_count": round(mean(usage_counts), 2) if usage_counts else 0.0,
            "avg_memory_score": round(mean(scores), 4) if scores else 0.0,
            "oldest_days": oldest_days,
            "prune_candidates": prune_candidates,
        }

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
