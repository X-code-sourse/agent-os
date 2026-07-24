"""Intent OS — Execution Context Store (BluePrint Layer 1)

SQLite-backed store for Execution Contexts — the task-level environment
snapshots that bound an Agent's behaviour (project, goal, constraints).

A Context is NOT user-preference memory.  It records *what* the Agent
is supposed to do and *under what limits*, not *who* the user is.

Usage:
    store = ContextStore()
    ctx = store.create(name="US Stock Analysis", goal="Find undervalued",
                       constraints=["SEC only"], task_scope="research",
                       variables={"tickers": ["AAPL","TSLA"]})
    store.assign_agent(ctx_id, agent_id)
    all = store.list()
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTEXT_DB = str(Path.home() / ".intent-os" / "contexts.db")

CREATE_CONTEXTS = """
CREATE TABLE IF NOT EXISTS execution_contexts (
    context_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    goal TEXT NOT NULL DEFAULT '',
    constraints TEXT NOT NULL DEFAULT '[]',
    task_scope TEXT NOT NULL DEFAULT '',
    variables TEXT NOT NULL DEFAULT '{}',
    parent_context_id TEXT,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT
);
"""

CREATE_ASSIGNMENTS = """
CREATE TABLE IF NOT EXISTS context_assignments (
    context_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (context_id, agent_id)
);
"""


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


class ContextStoreError(Exception):
    """Raised when context store operations fail."""
    pass


class ContextStore:
    """SQLite-backed Execution Context store.

    Usage:
        store = ContextStore()
        ctx = store.create(name="Project X", goal="Analyze...",
                           constraints=["only SEC"], task_scope="research")
        store.assign_agent(ctx["context_id"], "agent_abc123")
        store.list()
        store.get("ctx_abc123")
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = str(db_path or CONTEXT_DB)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(CREATE_CONTEXTS)
        conn.execute(CREATE_ASSIGNMENTS)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Context CRUD ──

    def create(
        self,
        name: str,
        goal: str = "",
        constraints: list[str] | None = None,
        task_scope: str = "",
        variables: dict[str, Any] | None = None,
        parent_context_id: str | None = None,
        created_by: str = "",
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a new execution context."""
        ctx_id = f"ctx_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO execution_contexts
                   (context_id, name, goal, constraints, task_scope,
                    variables, parent_context_id, created_by, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ctx_id, name, goal,
                 _json_dumps(constraints or []), task_scope,
                 _json_dumps(variables or {}), parent_context_id,
                 created_by, now, expires_at),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ContextStoreError(f"Context creation failed: {exc}") from exc
        finally:
            conn.close()
        return {
            "context_id": ctx_id, "name": name, "goal": goal,
            "constraints": constraints or [], "task_scope": task_scope,
            "variables": variables or {}, "parent_context_id": parent_context_id,
            "created_by": created_by, "created_at": now, "expires_at": expires_at,
        }

    def get(self, context_id: str) -> dict[str, Any] | None:
        """Look up a context by ID."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM execution_contexts WHERE context_id = ?",
                (context_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_context(row)
        finally:
            conn.close()

    def list(self, created_by: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List contexts, optionally filtered by creator."""
        conn = self._get_conn()
        try:
            if created_by:
                cursor = conn.execute(
                    "SELECT * FROM execution_contexts WHERE created_by = ? ORDER BY created_at DESC LIMIT ?",
                    (created_by, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM execution_contexts ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            return [_row_to_context(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def delete(self, context_id: str) -> bool:
        """Remove a context and its agent assignments. Returns True if deleted."""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM context_assignments WHERE context_id = ?", (context_id,))
            cursor = conn.execute("DELETE FROM execution_contexts WHERE context_id = ?", (context_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ── Agent Assignments ──

    def assign_agent(self, context_id: str, agent_id: str) -> bool:
        """Assign an agent to a context."""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO context_assignments (context_id, agent_id, assigned_at) "
                "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%Sf','now'))",
                (context_id, agent_id),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_assigned_agents(self, context_id: str) -> list[str]:
        """Return the list of agent IDs assigned to a context."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT agent_id FROM context_assignments WHERE context_id = ?",
                (context_id,),
            )
            return [row["agent_id"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_contexts_for_agent(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return all contexts an agent is assigned to."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT c.* FROM execution_contexts c
                   JOIN context_assignments a ON c.context_id = a.context_id
                   WHERE a.agent_id = ?
                   ORDER BY c.created_at DESC LIMIT ?""",
                (agent_id, limit),
            )
            return [_row_to_context(row) for row in cursor.fetchall()]
        finally:
            conn.close()


def _row_to_context(row: Any) -> dict[str, Any]:
    return {
        "context_id": row["context_id"],
        "name": row["name"],
        "goal": row["goal"] or "",
        "constraints": _json_loads(row["constraints"]),
        "task_scope": row["task_scope"] or "",
        "variables": _json_loads(row["variables"]),
        "parent_context_id": row["parent_context_id"],
        "created_by": row["created_by"] or "",
        "created_at": row["created_at"] or "",
        "expires_at": row["expires_at"],
    }
