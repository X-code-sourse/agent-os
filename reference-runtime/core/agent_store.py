"""
Intent OS — Agent Store (Metadata Plane)

Lightweight SQLite-backed store for agent identity.
Every registered agent gets a unique ``agent_id`` that can be
attached to executions, policies, and audit logs.

This is the foundation for the future Agent ID protocol:
  Agent → creates Executions → governed by Policies

Usage:
    store = AgentStore()
    agent = store.create("My Research Agent", "A research assistant")
    agent.agent_id  # "agent_8f92a1c3"

    store.get(agent.agent_id)
    store.list()
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AGENT_STORE_DB = str(Path.home() / ".intent-os" / "agents.db")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_seen_at TEXT
);
"""


@dataclass
class Agent:
    """A registered AI agent identity.

    Each agent has a unique ``agent_id`` that persists across
    executions, enabling traceability, governance, and audit.
    """
    agent_id: str
    name: str
    description: str = ""
    created_at: str = ""
    last_seen_at: str | None = None


class AgentStoreError(Exception):
    """Raised when agent store operations fail."""
    pass


class AgentStore:
    """Lightweight SQLite-backed agent identity store.

    Usage:
        store = AgentStore()
        agent = store.create(name="My Agent", description="...")
        all_agents = store.list()
        agent = store.get("agent_xxx")
        store.record_execution("agent_xxx")
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = str(db_path or AGENT_STORE_DB)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(CREATE_TABLE)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, name: str, description: str = "") -> Agent:
        """Register a new agent with a unique ID.

        Args:
            name: Human-readable name for the agent.
            description: Optional description of what the agent does.

        Returns:
            The newly created Agent.
        """
        agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO agents (agent_id, name, description, created_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (agent_id, name, description, now, now),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise AgentStoreError(f"Agent creation failed: {exc}") from exc
        finally:
            conn.close()

        return Agent(
            agent_id=agent_id,
            name=name,
            description=description,
            created_at=now,
            last_seen_at=now,
        )

    def get(self, agent_id: str) -> Agent | None:
        """Look up an agent by ID."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?",
                (agent_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return Agent(
                agent_id=row["agent_id"],
                name=row["name"],
                description=row["description"],
                created_at=row["created_at"],
                last_seen_at=row["last_seen_at"] if row["last_seen_at"] else None,
            )
        finally:
            conn.close()

    def get_by_name(self, name: str) -> Agent | None:
        """Look up an agent by its exact name."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM agents WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                (name,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return Agent(
                agent_id=row["agent_id"],
                name=row["name"],
                description=row["description"],
                created_at=row["created_at"],
                last_seen_at=row["last_seen_at"] if row["last_seen_at"] else None,
            )
        finally:
            conn.close()

    def list(self) -> list[Agent]:
        """List all registered agents, ordered by creation time (newest first)."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM agents ORDER BY created_at DESC",
            )
            results: list[Agent] = []
            for row in cursor.fetchall():
                results.append(Agent(
                    agent_id=row["agent_id"],
                    name=row["name"],
                    description=row["description"],
                    created_at=row["created_at"],
                    last_seen_at=row["last_seen_at"] if row["last_seen_at"] else None,
                ))
            return results
        finally:
            conn.close()

    def record_execution(self, agent_id: str) -> None:
        """Update the agent's ``last_seen_at`` timestamp.

        Called by the tracer when an execution associated with this
        agent is recorded.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE agents SET last_seen_at = ? WHERE agent_id = ?",
                (now, agent_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete(self, agent_id: str) -> bool:
        """Remove an agent by ID. Returns True if deleted."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM agents WHERE agent_id = ?",
                (agent_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
