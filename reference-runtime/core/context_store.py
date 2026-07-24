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
    expires_at TEXT,
    version INTEGER NOT NULL DEFAULT 1
);
"""

CREATE_VERSIONS = """
CREATE TABLE IF NOT EXISTS context_versions (
    context_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%Sf','now')),
    PRIMARY KEY (context_id, version)
);
"""

MIGRATE_VERSION_COLUMN = """
ALTER TABLE execution_contexts ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
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
        conn.execute(CREATE_VERSIONS)

        # Migration: add version column if missing from existing tables
        try:
            cursor = conn.execute(
                "PRAGMA table_info(execution_contexts)"
            )
            columns = {row["name"] for row in cursor.fetchall()}
            if "version" not in columns:
                conn.execute(MIGRATE_VERSION_COLUMN)
        except sqlite3.OperationalError:
            pass

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
        """Create a new execution context.

        If parent_context_id is set, inherits constraints and variables
        from the parent (child values win on conflict).
        """
        ctx_id = f"ctx_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        child_constraints = constraints or []
        child_vars = variables or {}

        # ── Context Inheritance ──
        parent: dict[str, Any] | None = None
        if parent_context_id is not None:
            parent = self.get(parent_context_id)

        if parent is not None:
            merged_constraints, merged_vars = self._merge_contexts(parent, {
                "constraints": child_constraints,
                "variables": child_vars,
            })
            final_constraints = merged_constraints
            final_vars = merged_vars
        else:
            final_constraints = child_constraints
            final_vars = child_vars

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO execution_contexts
                   (context_id, name, goal, constraints, task_scope,
                    variables, parent_context_id, created_by, created_at, expires_at, version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ctx_id, name, goal,
                 _json_dumps(final_constraints), task_scope,
                 _json_dumps(final_vars), parent_context_id,
                 created_by, now, expires_at, 1),
            )
            # Save initial snapshot to context_versions
            ctx_dict = {
                "context_id": ctx_id, "name": name, "goal": goal,
                "constraints": final_constraints, "task_scope": task_scope,
                "variables": final_vars, "parent_context_id": parent_context_id,
                "created_by": created_by, "created_at": now, "expires_at": expires_at,
                "version": 1,
            }
            conn.execute(
                """INSERT INTO context_versions
                   (context_id, version, snapshot, reason, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (ctx_id, 1, _json_dumps(ctx_dict), "Context created",
                 now),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ContextStoreError(f"Context creation failed: {exc}") from exc
        finally:
            conn.close()
        return ctx_dict

    @staticmethod
    def _merge_contexts(
        parent: dict[str, Any], child: dict[str, Any]
    ) -> tuple[list[str], dict[str, Any]]:
        """Merge parent's constraints/variables into child's.

        Returns (merged_constraints, merged_variables).

        - constraints: union of parent's + child's, deduplicated (same string).
          Preserves order: parent's first, then child's (excluding duplicates).
        - variables: parent's as defaults, child's override on key conflict.
        """
        # Merge constraints — deduplicate, parent order first
        parent_constraints: list[str] = list(parent.get("constraints", []) or [])
        child_constraints: list[str] = list(child.get("constraints", []) or [])
        seen: set[str] = set()
        merged_constraints: list[str] = []
        for c in parent_constraints:
            if c not in seen:
                seen.add(c)
                merged_constraints.append(c)
        for c in child_constraints:
            if c not in seen:
                seen.add(c)
                merged_constraints.append(c)

        # Merge variables — parent defaults, child wins
        parent_vars: dict[str, Any] = dict(parent.get("variables", {}) or {})
        child_vars: dict[str, Any] = dict(child.get("variables", {}) or {})
        merged_vars: dict[str, Any] = {**parent_vars, **child_vars}

        return merged_constraints, merged_vars

    def get_inheritance_chain(self, context_id: str) -> list[dict[str, Any]]:
        """Walk parent_context_id links and return the chain from root to child.

        Returns a list of context dicts ordered from the rootmost ancestor
        (no parent) down to the given context.  Returns a single-element
        list [child] when the context has no parent.
        """
        chain: list[dict[str, Any]] = []
        current_id: str | None = context_id
        visited: set[str] = set()

        while current_id is not None:
            if current_id in visited:
                # Cycle detected — stop walking
                break
            visited.add(current_id)
            ctx = self.get(current_id)
            if ctx is None:
                break
            chain.append(ctx)
            current_id = ctx.get("parent_context_id")

        chain.reverse()  # root ancestor → child
        return chain

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
            conn.execute("DELETE FROM context_versions WHERE context_id = ?", (context_id,))
            cursor = conn.execute("DELETE FROM execution_contexts WHERE context_id = ?", (context_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ── Context Versioning ──

    def bump_version(self, context_id: str, reason: str = "") -> int:
        """Increment the version number, save a snapshot, and return the new version.

        Args:
            context_id: The context to version-bump.
            reason: Why the version is being bumped.

        Returns:
            The new version number.

        Raises:
            ContextStoreError: If the context does not exist.
        """
        conn = self._get_conn()
        try:
            # Fetch current context with version
            cursor = conn.execute(
                "SELECT * FROM execution_contexts WHERE context_id = ?",
                (context_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ContextStoreError(f"Context not found: {context_id}")

            current_version = row["version"]
            new_version = current_version + 1
            now = datetime.now(timezone.utc).isoformat()

            # Build snapshot from current row
            ctx_dict = _row_to_context(row)
            ctx_dict["version"] = new_version

            # Update version in execution_contexts
            conn.execute(
                "UPDATE execution_contexts SET version = ? WHERE context_id = ?",
                (new_version, context_id),
            )

            # Save snapshot to context_versions
            conn.execute(
                """INSERT OR REPLACE INTO context_versions
                   (context_id, version, snapshot, reason, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (context_id, new_version, _json_dumps(ctx_dict),
                 reason or "", now),
            )

            conn.commit()
            return new_version
        finally:
            conn.close()

    def get_history(self, context_id: str) -> list[dict[str, Any]]:
        """Return version history for a context, newest first.

        Args:
            context_id: The context to look up.

        Returns:
            A list of {version, reason, created_at} dicts.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT version, reason, created_at
                   FROM context_versions
                   WHERE context_id = ?
                   ORDER BY version DESC""",
                (context_id,),
            )
            return [
                {
                    "version": row["version"],
                    "reason": row["reason"] or "",
                    "created_at": row["created_at"] or "",
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def get_version(self, context_id: str, version: int) -> dict[str, Any] | None:
        """Return the context snapshot at a specific version.

        Args:
            context_id: The context to look up.
            version: The version number to retrieve.

        Returns:
            The context dict as it was at that version, or None.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT snapshot FROM context_versions
                   WHERE context_id = ? AND version = ?""",
                (context_id, version),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _json_loads(row["snapshot"])
        finally:
            conn.close()

    def update(
        self,
        context_id: str,
        *,
        name: str | None = None,
        goal: str | None = None,
        constraints: list[str] | None = None,
        task_scope: str | None = None,
        variables: dict[str, Any] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """Update fields on an existing context and bump the version.

        Only the fields provided (not None) are updated; the rest stay
        unchanged.  A snapshot is saved to context_versions automatically.

        Args:
            context_id: The context to update.
            name: New name (or None to keep current).
            goal: New goal (or None to keep current).
            constraints: New constraints (or None to keep current).
            task_scope: New scope (or None to keep current).
            variables: New variables (or None to keep current).
            reason: Why the context is being updated.

        Returns:
            The updated context dict (current state).

        Raises:
            ContextStoreError: If the context does not exist.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM execution_contexts WHERE context_id = ?",
                (context_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ContextStoreError(f"Context not found: {context_id}")

            current = _row_to_context(row)
            current_version = current["version"]
            new_version = current_version + 1
            now = datetime.now(timezone.utc).isoformat()

            updated_name = name if name is not None else current["name"]
            updated_goal = goal if goal is not None else current["goal"]
            updated_constraints = constraints if constraints is not None else current["constraints"]
            updated_scope = task_scope if task_scope is not None else current["task_scope"]
            updated_vars = variables if variables is not None else current["variables"]

            conn.execute(
                """UPDATE execution_contexts SET
                   name = ?, goal = ?, constraints = ?, task_scope = ?,
                   variables = ?, version = ?
                   WHERE context_id = ?""",
                (updated_name, updated_goal, _json_dumps(updated_constraints),
                 updated_scope, _json_dumps(updated_vars), new_version,
                 context_id),
            )

            ctx_dict = {
                "context_id": context_id, "name": updated_name,
                "goal": updated_goal, "constraints": updated_constraints,
                "task_scope": updated_scope, "variables": updated_vars,
                "parent_context_id": current["parent_context_id"],
                "created_by": current["created_by"],
                "created_at": current["created_at"],
                "expires_at": current["expires_at"],
                "version": new_version,
            }
            conn.execute(
                """INSERT INTO context_versions
                   (context_id, version, snapshot, reason, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (context_id, new_version, _json_dumps(ctx_dict),
                 reason or "", now),
            )

            conn.commit()
            return ctx_dict
        finally:
            conn.close()

    def diff(
        self,
        context_id_a: str,
        context_id_b: str | None = None,
        version_a: int | None = None,
        version_b: int | None = None,
    ) -> dict[str, Any]:
        """Compare two contexts or two versions of the same context.

        Usage:
            store.diff("ctx_a", "ctx_b")           # two different contexts
            store.diff("ctx_a", version_a=1, version_b=3)   # versions of same ctx
            store.diff("ctx_a")                    # current vs previous version

        Args:
            context_id_a: Primary context ID.
            context_id_b: Secondary context ID.  If None, compares two
                versions within context_id_a.
            version_a: Specific version for side A (None = current).
            version_b: Specific version for side B (None = current).

        Returns:
            A diff dict:
                {
                    "context_a": {id, version, name},
                    "context_b": {id, version, name} | null,
                    "constraints_added": [...],
                    "constraints_removed": [...],
                    "variables_added": [...],
                    "variables_removed": [...],
                    "variables_changed": [...],
                    "goal_changed": bool,
                    "scope_changed": bool,
                    "identical": bool,
                    "single_version": bool    # only when context_b is null
                }
        """
        ctx_a: dict[str, Any] | None = None
        ver_a: str = "current"
        ctx_b: dict[str, Any] | None = None
        ver_b: str = "current"

        # ── Resolve side A ──
        if version_a is not None:
            ctx_a = self.get_version(context_id_a, version_a)
            if ctx_a is None:
                raise ContextStoreError(
                    f"Version {version_a} not found for context {context_id_a}"
                )
            ver_a = str(version_a)
        else:
            ctx_a = self.get(context_id_a)
            if ctx_a is None:
                raise ContextStoreError(f"Context not found: {context_id_a}")
            ver_a = str(ctx_a.get("version", "current"))

        # ── Resolve side B ──
        if context_id_b is not None:
            # Two different contexts
            if version_b is not None:
                ctx_b = self.get_version(context_id_b, version_b)
                if ctx_b is None:
                    raise ContextStoreError(
                        f"Version {version_b} not found for context {context_id_b}"
                    )
                ver_b = str(version_b)
            else:
                ctx_b = self.get(context_id_b)
                if ctx_b is None:
                    raise ContextStoreError(f"Context not found: {context_id_b}")
                ver_b = str(ctx_b.get("version", "current"))
        elif version_b is not None:
            # Same context, explicit version B
            ctx_b = self.get_version(context_id_a, version_b)
            if ctx_b is None:
                raise ContextStoreError(
                    f"Version {version_b} not found for context {context_id_a}"
                )
            ver_b = str(version_b)
        else:
            # Same context, no versions specified → current vs previous
            current_ver = ctx_a.get("version", 1)
            if isinstance(current_ver, int) and current_ver > 1:
                ctx_b = self.get_version(context_id_a, current_ver - 1)
                if ctx_b is not None:
                    ver_b = str(current_ver - 1)
                else:
                    # Fallback: use get_history to find previous
                    history = self.get_history(context_id_a)
                    if len(history) > 1:
                        ctx_b = self.get_version(context_id_a, history[1]["version"])
                        if ctx_b is not None:
                            ver_b = str(history[1]["version"])

            if ctx_b is None:
                return {
                    "context_a": {
                        "id": ctx_a["context_id"],
                        "version": ver_a,
                        "name": ctx_a["name"],
                    },
                    "context_b": None,
                    "constraints_added": [],
                    "constraints_removed": [],
                    "variables_added": [],
                    "variables_removed": [],
                    "variables_changed": [],
                    "goal_changed": False,
                    "scope_changed": False,
                    "identical": True,
                    "single_version": True,
                }

        ctx_a["_version"] = ver_a
        ctx_b["_version"] = ver_b
        return self._compute_diff(ctx_a, ctx_b)

    def _compute_diff(
        self, ctx_a: dict[str, Any], ctx_b: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute field-level diff between two context dicts."""
        constraints_a: list[str] = list(ctx_a.get("constraints", []) or [])
        constraints_b: list[str] = list(ctx_b.get("constraints", []) or [])
        set_a = set(constraints_a)
        set_b = set(constraints_b)

        vars_a: dict[str, Any] = dict(ctx_a.get("variables", {}) or {})
        vars_b: dict[str, Any] = dict(ctx_b.get("variables", {}) or {})
        keys_a = set(vars_a.keys())
        keys_b = set(vars_b.keys())

        constraints_added = sorted(set_a - set_b)
        constraints_removed = sorted(set_b - set_a)

        variables_added = sorted(keys_a - keys_b)
        variables_removed = sorted(keys_b - keys_a)
        variables_changed = sorted(
            k for k in (keys_a & keys_b) if vars_a[k] != vars_b[k]
        )

        goal_changed = ctx_a.get("goal") != ctx_b.get("goal")
        scope_changed = ctx_a.get("task_scope") != ctx_b.get("task_scope")

        identical = (
            not constraints_added
            and not constraints_removed
            and not variables_added
            and not variables_removed
            and not variables_changed
            and not goal_changed
            and not scope_changed
        )

        return {
            "context_a": {
                "id": ctx_a["context_id"],
                "version": ctx_a.get("_version", "current"),
                "name": ctx_a["name"],
            },
            "context_b": {
                "id": ctx_b["context_id"],
                "version": ctx_b.get("_version", "current"),
                "name": ctx_b["name"],
            },
            "constraints_added": constraints_added,
            "constraints_removed": constraints_removed,
            "variables_added": variables_added,
            "variables_removed": variables_removed,
            "variables_changed": variables_changed,
            "goal_changed": goal_changed,
            "scope_changed": scope_changed,
            "identical": identical,
        }

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
        "version": row["version"] if "version" in row.keys() else 1,
    }
