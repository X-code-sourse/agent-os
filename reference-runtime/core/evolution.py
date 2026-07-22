"""
Intent OS — Evolution Loop (SPEC-0003, Algorithm 5)

The Evolution Loop drives continuous optimization by analyzing execution
history from the Event Store, generating optimization suggestions,
auto-applying low-risk ones, and queuing higher-risk ones for human review.

Architecture:
  - iterate(): Run one pass of the loop
  - Pending suggestions are stored in a SQLite-backed suggestion queue
  - Human-in-the-loop: approve/reject queued suggestions via CLI
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.analytics import AnalyticsEngine
from core.event_store import EventStore


class EvolutionLoopError(Exception):
    """Raised when Evolution Loop operations fail."""


class EvolutionLoop:
    """
    Continuous optimization loop for the Intent OS runtime.

    Analyzes execution analytics via the AnalyticsEngine, generates
    improvement suggestions, auto-applies high-confidence changes,
    and queues the rest for human review.

    Usage:
        store = EventStore("path/to/store.db")
        analytics = AnalyticsEngine(store)
        loop = EvolutionLoop(store, analytics)
        result = loop.iterate()
    """

    def __init__(
        self,
        event_store: EventStore,
        analytics: AnalyticsEngine,
        db_path: str | Path | None = None,
    ) -> None:
        self._store = event_store
        self._analytics = analytics
        self._db_path_override = Path(db_path) if db_path else None

    # ── Database ──

    def _get_db_path(self) -> Path:
        """Get the path to the evolution store database."""
        if self._db_path_override:
            return self._db_path_override
        store_dir = Path.home() / ".intent-os"
        store_dir.mkdir(parents=True, exist_ok=True)
        return store_dir / "evolution.db"

    def _get_conn(self) -> sqlite3.Connection:
        """Get a connection to the evolution store (creates schema if needed)."""
        db_path = self._get_db_path()
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                suggestion_type TEXT NOT NULL,
                summary     TEXT NOT NULL,
                rationale   TEXT NOT NULL,
                expected_impact TEXT NOT NULL,
                confidence  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                resolved_at TEXT
            )
        """)
        conn.commit()
        return conn

    # ── Main Loop ──

    def iterate(self) -> dict[str, Any]:
        """
        Run one iteration of the Evolution Loop.

        Fetches optimization suggestions from the AnalyticsEngine,
        auto-applies high-confidence ones, and queues the rest.

        Returns:
            Dict with keys:
              - applied_count: number of auto-applied suggestions
              - queued_count:  number queued for human review
              - total:         total suggestions generated
              - applied:       list of auto-applied suggestion dicts
              - queued:        list of queued suggestion dicts
        """
        suggestions = self._analytics.get_optimization_suggestions()
        applied: list[dict[str, Any]] = []
        queued: list[dict[str, Any]] = []

        for s in suggestions:
            if s.get("confidence") == "high":
                self._apply(s)
                applied.append(s)
            else:
                self._queue(s)
                queued.append(s)

        return {
            "applied_count": len(applied),
            "queued_count": len(queued),
            "total": len(suggestions),
            "applied": applied,
            "queued": queued,
        }

    def _apply(self, suggestion: dict[str, Any]) -> None:
        """Auto-apply a low-risk suggestion."""
        s_type = suggestion.get("type", "unknown")
        s_summary = suggestion.get("suggestion", "")
        print(f"  [auto-apply] {s_type}: {s_summary[:80]}")

    def _queue(self, suggestion: dict[str, Any]) -> int:
        """Persist a suggestion for human review."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO suggestions
               (suggestion_type, summary, rationale, expected_impact, confidence, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (
                suggestion.get("type", ""),
                suggestion.get("suggestion", ""),
                suggestion.get("rationale", ""),
                suggestion.get("expected_impact", ""),
                suggestion.get("confidence", "low"),
            ),
        )
        conn.commit()
        row_id: int = cursor.lastrowid  # type: ignore[assignment]
        conn.close()
        return row_id

    # ── Query API ──

    def get_pending_count(self) -> int:
        """Return the number of suggestions awaiting human review."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT COUNT(*) AS cnt FROM suggestions WHERE status = 'pending'"
        )
        row = cursor.fetchone()
        conn.close()
        return row["cnt"] if row else 0

    def get_pending_suggestions(self) -> list[dict[str, Any]]:
        """Return all suggestions awaiting human review, newest first."""
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT id, suggestion_type AS type, summary AS suggestion,
                      rationale, expected_impact, confidence, created_at
               FROM suggestions
               WHERE status = 'pending'
               ORDER BY created_at DESC"""
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def approve_suggestion(self, suggestion_id: int) -> bool:
        """Mark a pending suggestion as approved. Returns True if updated."""
        conn = self._get_conn()
        cursor = conn.execute(
            """UPDATE suggestions
               SET status = 'approved', resolved_at = datetime('now')
               WHERE id = ? AND status = 'pending'""",
            (suggestion_id,),
        )
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def reject_suggestion(self, suggestion_id: int) -> bool:
        """Mark a pending suggestion as rejected. Returns True if updated."""
        conn = self._get_conn()
        cursor = conn.execute(
            """UPDATE suggestions
               SET status = 'rejected', resolved_at = datetime('now')
               WHERE id = ? AND status = 'pending'""",
            (suggestion_id,),
        )
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0
