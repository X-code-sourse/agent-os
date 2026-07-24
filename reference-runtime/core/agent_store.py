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

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import Event, EventType

_log = logging.getLogger(__name__)


AGENT_STORE_DB = str(Path.home() / ".intent-os" / "intent.db")

CREATE_AGENTS_TABLE = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    team_id TEXT,
    capabilities TEXT NOT NULL DEFAULT '[]',
    policy_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    last_seen_at TEXT
);
"""

CREATE_TEAMS_TABLE = """
CREATE TABLE IF NOT EXISTS teams (
    team_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    org_id TEXT NOT NULL DEFAULT '',
    member_ids TEXT NOT NULL DEFAULT '[]',
    policy_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""


@dataclass
class Agent:
    """A registered AI agent identity.

    Each agent has a unique ``agent_id`` that persists across
    executions, enabling traceability, governance, and audit.

    BluePrint Layer 2 — Identity: Agent is a digital entity with
    ownership, team membership, capability grants, and a lifecycle status.
    """
    agent_id: str
    name: str
    description: str = ""
    owner: str = ""
    team_id: str | None = None
    capabilities: list[str] = field(default_factory=list)
    policy_ids: list[str] = field(default_factory=list)
    status: str = "active"       # active | paused | revoked
    created_at: str = ""
    last_seen_at: str | None = None


def _row_to_agent(row: Any) -> Agent:
    """Convert a SQLite row to an Agent instance."""
    def _json_list(raw: str) -> list[str]:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return Agent(
        agent_id=row["agent_id"],
        name=row["name"],
        description=row["description"] or "",
        owner=row["owner"] if "owner" in row.keys() else "",
        team_id=row["team_id"] if "team_id" in row.keys() else None,
        capabilities=_json_list(row["capabilities"]) if "capabilities" in row.keys() else [],
        policy_ids=_json_list(row["policy_ids"]) if "policy_ids" in row.keys() else [],
        status=row["status"] if "status" in row.keys() else "active",
        created_at=row["created_at"] or "",
        last_seen_at=row["last_seen_at"] if "last_seen_at" in row.keys() and row["last_seen_at"] else None,
    )


def _row_to_team(row: Any) -> Any:
    """Convert a SQLite row to a Team dict."""
    def _json_list(raw: str) -> list[str]:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return {
        "team_id": row["team_id"],
        "name": row["name"],
        "description": row["description"] or "",
        "owner": row["owner"] or "",
        "org_id": row["org_id"] if "org_id" in row.keys() else "",
        "member_ids": _json_list(row["member_ids"]),
        "policy_ids": _json_list(row["policy_ids"]),
        "created_at": row["created_at"] or "",
    }


def _migrate_agents_schema(conn: Any) -> None:
    """Add columns introduced in v0.4.3 if they don't already exist."""
    new_cols = [
        ("owner", "TEXT NOT NULL DEFAULT ''"),
        ("team_id", "TEXT"),
        ("capabilities", "TEXT NOT NULL DEFAULT '[]'"),
        ("policy_ids", "TEXT NOT NULL DEFAULT '[]'"),
        ("status", "TEXT NOT NULL DEFAULT 'active'"),
    ]
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(agents)")}
    for col_name, col_def in new_cols:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE agents ADD COLUMN {col_name} {col_def}")

    # Teams table migration — org_id added in v0.5.0
    team_cols = [
        ("org_id", "TEXT NOT NULL DEFAULT ''"),
    ]
    existing_teams = {row["name"] for row in conn.execute("PRAGMA table_info(teams)")}
    for col_name, col_def in team_cols:
        if col_name not in existing_teams:
            conn.execute(f"ALTER TABLE teams ADD COLUMN {col_name} {col_def}")


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

    def __init__(self, db_path: str | None = None, event_store: Any = None) -> None:
        self._db_path = str(db_path or AGENT_STORE_DB)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._event_store = event_store
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(CREATE_AGENTS_TABLE)
        conn.execute(CREATE_TEAMS_TABLE)
        # Migrate old agent tables missing v0.4.3 columns
        _migrate_agents_schema(conn)
        conn.commit()

    def _emit_event(self, payload: dict[str, Any]) -> None:
        """Emit a CAPABILITY_REGISTERED event to the event store if configured.

        Failure to emit the event never blocks the CRUD operation.
        """
        if self._event_store is None:
            return
        try:
            event = Event.create(
                event_type=EventType.CAPABILITY_REGISTERED,
                source="agent_store",
                payload=payload,
            )
            self._event_store.save_event(event)
        except Exception:
            _log.warning(
                "Failed to emit CAPABILITY_REGISTERED event for payload=%s",
                payload,
                exc_info=True,
            )

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, name: str, description: str = "", owner: str = "", team_id: str | None = None) -> Agent:
        """Register a new agent with a unique ID.

        Args:
            name: Human-readable name for the agent.
            description: Optional description of what the agent does.
            owner: Who owns this agent (user ID or email).
            team_id: Optional team this agent belongs to.

        Returns:
            The newly created Agent.
        """
        agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO agents (agent_id, name, description, owner, team_id, capabilities, policy_ids, status, created_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agent_id, name, description, owner, team_id, "[]", "[]", "active", now, now),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise AgentStoreError(f"Agent creation failed: {exc}") from exc
        finally:
            conn.close()

        agent = Agent(
            agent_id=agent_id, name=name, description=description,
            owner=owner, team_id=team_id,
            created_at=now, last_seen_at=now,
        )
        self._emit_event({
            "action": "agent_created",
            "agent_id": agent_id,
            "name": name,
            "owner": owner,
            "team_id": team_id,
        })
        return agent

    def get(self, agent_id: str) -> Agent | None:
        """Look up an agent by ID."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_agent(row)
        finally:
            conn.close()

    def get_by_name(self, name: str) -> Agent | None:
        """Look up an agent by its exact name."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM agents WHERE name = ? ORDER BY created_at DESC LIMIT 1", (name,))
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_agent(row)
        finally:
            conn.close()

    def list(self, team_id: str | None = None) -> list[Agent]:
        """List all registered agents, optionally filtered by team."""
        conn = self._get_conn()
        try:
            if team_id:
                cursor = conn.execute("SELECT * FROM agents WHERE team_id = ? ORDER BY created_at DESC", (team_id,))
            else:
                cursor = conn.execute("SELECT * FROM agents ORDER BY created_at DESC")
            return [_row_to_agent(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def update_agent(self, agent_id: str, **kwargs: Any) -> Agent | None:
        """Update agent fields. Thread-safe."""
        with self._lock:
            agent = self.get(agent_id)
            if agent is None:
                return None
            for key, val in kwargs.items():
                if hasattr(agent, key):
                    setattr(agent, key, val)
            conn = self._get_conn()
            try:
                conn.execute(
                    """UPDATE agents SET name=?, description=?, owner=?, team_id=?,
                       capabilities=?, policy_ids=?, status=?
                       WHERE agent_id=?""",
                    (agent.name, agent.description, agent.owner, agent.team_id,
                     json.dumps(agent.capabilities), json.dumps(agent.policy_ids),
                     agent.status, agent_id),
                )
                conn.commit()
            finally:
                conn.close()
        self._emit_event({
            "action": "agent_updated",
            "agent_id": agent_id,
            "fields": list(kwargs.keys()),
        })
        return agent

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
            deleted = cursor.rowcount > 0
        finally:
            conn.close()
        if deleted:
            self._emit_event({
                "action": "agent_deleted",
                "agent_id": agent_id,
            })
        return deleted

    # ── Team CRUD (BluePrint Layer 2 — multi-agent teams) ──

    def create_team(self, name: str, description: str = "", owner: str = "", org_id: str = "") -> dict[str, Any]:
        """Create a new team and return its dict representation."""
        team_id = f"team_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO teams (team_id, name, description, owner, org_id, member_ids, policy_ids, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (team_id, name, description, owner, org_id, "[]", "[]", now),
            )
            conn.commit()
        finally:
            conn.close()
        result = {"team_id": team_id, "name": name, "description": description,
                  "owner": owner, "org_id": org_id, "member_ids": [], "policy_ids": [], "created_at": now}
        self._emit_event({
            "action": "team_created",
            "team_id": team_id,
            "name": name,
            "owner": owner,
            "org_id": org_id,
        })
        return result

    def get_team(self, team_id: str) -> dict[str, Any] | None:
        """Look up a team by ID."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM teams WHERE team_id = ?", (team_id,))
            row = cursor.fetchone()
            return _row_to_team(row) if row else None
        finally:
            conn.close()

    def list_teams(self) -> list[dict[str, Any]]:
        """List all teams."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM teams ORDER BY created_at DESC")
            return [_row_to_team(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def add_team_member(self, team_id: str, agent_id: str) -> bool:
        """Add an agent to a team and update the agent's team_id. Thread-safe."""
        with self._lock:
            team = self.get_team(team_id)
            if team is None:
                return False
            if agent_id not in team["member_ids"]:
                team["member_ids"].append(agent_id)
                conn = self._get_conn()
                try:
                    conn.execute("UPDATE teams SET member_ids = ? WHERE team_id = ?",
                                 (json.dumps(team["member_ids"]), team_id))
                    conn.commit()
                finally:
                    conn.close()
            self.update_agent(agent_id, team_id=team_id)
        return True
