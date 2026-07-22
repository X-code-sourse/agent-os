"""
Intent OS — Event Store (SPEC-0003 Event System, Data Plane)

SQLite-backed persistent storage for execution events.

The Event Store is the foundation of Intent OS's observability and
learning backbone (SPEC-0003 Section 10). It provides:

  - Append-only event persistence (events are immutable)
  - Query by trace_id, event_type, time range, capability
  - Aggregation for analytics and cost model training
  - Deterministic replay of any past execution

Design constraints:
  - Event Store belongs to the Data Plane (CONSTITUTION Article II)
  - Control Plane components read from Event Store, never write directly
  - Events are immutable once written — corrections are new events
  - The store must handle high write throughput (many concurrent executions)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from core.models import Event, EventType, ExecutionRecord, ExecutionStatus
from core.recorder import ExecutionRecorder


# Schema version to support future migrations
SCHEMA_VERSION = 2

# SQL statements for table creation
CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    trace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'runtime',
    sequence INTEGER NOT NULL DEFAULT 0,
    workflow_id TEXT,
    task_id TEXT,
    capability TEXT,
    runtime TEXT,
    adapter_version TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    metrics TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_EXECUTION_RECORDS_TABLE = """
CREATE TABLE IF NOT EXISTS execution_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL UNIQUE,
    spec_version TEXT NOT NULL DEFAULT '1.0',
    manifest_name TEXT NOT NULL,
    manifest_version TEXT NOT NULL,
    runtime_id TEXT NOT NULL,
    adapter TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    input TEXT,
    output TEXT,
    status TEXT NOT NULL DEFAULT 'success',
    error TEXT,
    total_latency_ms REAL NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_events_trace_id ON events(trace_id);",
    "CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_events_capability ON events(capability);",
    "CREATE INDEX IF NOT EXISTS idx_events_workflow_id ON events(workflow_id);",
    "CREATE INDEX IF NOT EXISTS idx_records_manifest ON execution_records(manifest_name, manifest_version);",
    "CREATE INDEX IF NOT EXISTS idx_records_runtime ON execution_records(runtime_id);",
    "CREATE INDEX IF NOT EXISTS idx_records_status ON execution_records(status);",
    "CREATE INDEX IF NOT EXISTS idx_records_created ON execution_records(created_at);",
]

CREATE_META_TABLE = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CREATE_TASK_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS task_state (
    trace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL DEFAULT '',
    field_name TEXT NOT NULL,
    field_value TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (trace_id, task_id, field_name)
);
"""


class EventStoreError(Exception):
    """Raised when Event Store operations fail."""
    pass


class EventStore:
    """
    Persistent, append-only Event Store backed by SQLite.

    Thread-safe for concurrent reads and writes. Part of the Data Plane.

    Usage:
        store = EventStore("path/to/store.db")

        # Record execution events
        store.save_event(event)

        # Query past executions
        records = store.query_records(
            manifest_name="text_summarize",
            limit=10,
        )

        # Replay a past execution
        events = store.get_events_by_trace("some-trace-id")
    """

    def __init__(self, db_path: str | Path = "intent_os_store.db") -> None:
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._lock = threading.Lock()

        # Initialize database
        with self._lock:
            self._init_db()

    # ── Connection Management ──

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self._db_path),
                timeout=30,
                check_same_thread=False,
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn.execute("PRAGMA synchronous=NORMAL;")
        return self._local.conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()
        conn.execute(CREATE_EVENTS_TABLE)
        conn.execute(CREATE_EXECUTION_RECORDS_TABLE)
        conn.execute(CREATE_TASK_STATE_TABLE)
        conn.execute(CREATE_META_TABLE)
        for idx in CREATE_INDEXES:
            try:
                conn.execute(idx)
            except sqlite3.OperationalError:
                pass  # Index already exists — idempotent init

        # Set schema version
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    # ── Event Writing ──

    def save_event(self, event: Event) -> int:
        """
        Persist a single event to the store (append-only).

        Args:
            event: The Event to persist.

        Returns:
            The row ID of the inserted event.

        Raises:
            EventStoreError: If the event already exists.
        """
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO events (
                    event_id, trace_id, event_type, timestamp, source,
                    sequence, workflow_id, task_id, capability,
                    runtime, adapter_version, payload, metrics
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.trace_id,
                    event.event_type.value,
                    event.timestamp.isoformat(),
                    event.source,
                    event.sequence,
                    event.workflow_id,
                    event.task_id,
                    event.capability,
                    event.runtime,
                    event.adapter_version,
                    json.dumps(event.payload or {}, default=str),
                    json.dumps(event.metrics or {}, default=str),
                ),
            )
            conn.commit()
            cursor = conn.execute("SELECT last_insert_rowid()")
            return cursor.fetchone()[0] or 0
        except sqlite3.IntegrityError:
            raise EventStoreError(
                f"Event '{event.event_id}' already exists in store"
            )

    def save_events_batch(self, events: list[Event]) -> int:
        """
        Persist multiple events in a single transaction.

        Args:
            events: List of Events to persist.

        Returns:
            Number of events persisted.
        """
        conn = self._get_conn()
        count = 0
        for event in events:
            try:
                conn.execute(
                    """INSERT INTO events (
                        event_id, trace_id, event_type, timestamp, source,
                        sequence, workflow_id, task_id, capability,
                        runtime, adapter_version, payload, metrics
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.event_id,
                        event.trace_id,
                        event.event_type.value,
                        event.timestamp.isoformat(),
                        event.source,
                        event.sequence,
                        event.workflow_id,
                        event.task_id,
                        event.capability,
                        event.runtime,
                        event.adapter_version,
                        json.dumps(event.payload or {}, default=str),
                        json.dumps(event.metrics or {}, default=str),
                    ),
                )
                count += 1
            except sqlite3.IntegrityError:
                pass  # Skip duplicates
        conn.commit()
        return count

    def save_execution_record(self, record: ExecutionRecord) -> None:
        """
        Persist an ExecutionRecord to the store.

        Args:
            record: The ExecutionRecord to persist.
        """
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO execution_records (
                    trace_id, spec_version, manifest_name, manifest_version,
                    runtime_id, adapter, adapter_version, input, output,
                    status, error, total_latency_ms, total_cost_usd, total_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.trace_id,
                    record.spec_version,
                    record.manifest_name,
                    record.manifest_version,
                    record.runtime_id,
                    record.adapter,
                    record.adapter_version,
                    json.dumps(record.input, default=str) if record.input else None,
                    json.dumps(record.output, default=str) if record.output else None,
                    record.status.value,
                    record.error,
                    record.total_latency_ms,
                    record.total_cost_usd,
                    record.total_tokens,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass  # Already exists, update instead

    # ── Event Reading ──

    def get_events_by_trace(self, trace_id: str) -> list[dict[str, Any]]:
        """
        Retrieve all events for a given trace, in sequence order.

        Args:
            trace_id: The execution trace identifier.

        Returns:
            List of event dicts ordered by sequence number.
        """
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT * FROM events WHERE trace_id = ? ORDER BY sequence ASC""",
            (trace_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_events_by_type(
        self,
        event_type: str | EventType,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Retrieve events by type.

        Args:
            event_type: Event type string or EventType enum.
            limit: Maximum number of events to return.
            offset: Number of events to skip.

        Returns:
            List of event dicts.
        """
        if isinstance(event_type, EventType):
            event_type = event_type.value

        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT * FROM events WHERE event_type = ?
               ORDER BY timestamp DESC LIMIT ? OFFSET ?""",
            (event_type, limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_events_by_time_range(
        self,
        start: str | datetime,
        end: str | datetime,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Retrieve events within a time range.

        Args:
            start: ISO format datetime string or datetime object.
            end: ISO format datetime string or datetime object.
            limit: Maximum number of events.

        Returns:
            List of event dicts.
        """
        if isinstance(start, datetime):
            start = start.isoformat()
        if isinstance(end, datetime):
            end = end.isoformat()

        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT * FROM events
               WHERE timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp DESC LIMIT ?""",
            (start, end, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_events_by_capability(
        self,
        capability: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve events for a specific capability."""
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT * FROM events WHERE capability = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (capability, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_events(
        self,
        trace_id: str | None = None,
        event_type: str | None = None,
        capability: str | None = None,
        workflow_id: str | None = None,
        runtime: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Flexible event query with multiple filters.

        Args:
            trace_id: Filter by execution trace.
            event_type: Filter by event type.
            capability: Filter by capability name@version.
            workflow_id: Filter by workflow.
            runtime: Filter by runtime.
            start_time: ISO format start time.
            end_time: ISO format end time.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of matching event dicts.
        """
        conditions = []
        params: list[Any] = []

        if trace_id:
            conditions.append("trace_id = ?")
            params.append(trace_id)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if capability:
            conditions.append("capability = ?")
            params.append(capability)
        if workflow_id:
            conditions.append("workflow_id = ?")
            params.append(workflow_id)
        if runtime:
            conditions.append("runtime = ?")
            params.append(runtime)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM events WHERE {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self._get_conn()
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    # ── Execution Record Reading ──

    def get_record(self, trace_id: str) -> dict[str, Any] | None:
        """Get a single execution record by trace_id."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM execution_records WHERE trace_id = ?",
            (trace_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def query_records(
        self,
        manifest_name: str | None = None,
        runtime_id: str | None = None,
        status: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Query execution records with filters.

        Args:
            manifest_name: Filter by capability name.
            runtime_id: Filter by runtime.
            status: Filter by status (success/failure/partial).
            start_time: ISO format start time.
            end_time: ISO format end time.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of matching record dicts.
        """
        conditions = []
        params: list[Any] = []

        if manifest_name:
            conditions.append("manifest_name = ?")
            params.append(manifest_name)
        if runtime_id:
            conditions.append("runtime_id = ?")
            params.append(runtime_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if start_time:
            conditions.append("created_at >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("created_at <= ?")
            params.append(end_time)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM execution_records WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self._get_conn()
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    # ── Task State (Data Plane storage for Scheduler) ──

    def save_task_state(
        self,
        trace_id: str,
        task_id: str,
        field_name: str,
        field_value: str,
        workflow_id: str = "",
    ) -> None:
        """Persist a single task state field to the Data Plane.

        This is how the Scheduler satisfies R1 (Control Plane owns no
        state) — instead of holding ``_task_outputs`` in memory, the
        Scheduler writes each field as a row in the ``task_state`` table.
        """
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO task_state
               (trace_id, task_id, workflow_id, field_name, field_value, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (trace_id, task_id, workflow_id, field_name, json.dumps(field_value)),
        )
        conn.commit()

    def save_task_output(
        self,
        trace_id: str,
        task_id: str,
        output: dict[str, Any],
        workflow_id: str = "",
    ) -> None:
        """Convenience: save a task's output dict as the ``output`` field."""
        self.save_task_state(trace_id, task_id, "output", output, workflow_id)

    def save_task_error(
        self,
        trace_id: str,
        task_id: str,
        error: str,
        workflow_id: str = "",
    ) -> None:
        """Convenience: save a task's error as the ``error`` field."""
        self.save_task_state(trace_id, task_id, "error", error, workflow_id)

    def get_task_state(
        self,
        trace_id: str,
        task_id: str,
        field_name: str,
    ) -> Any:
        """Read a single task state field from the Data Plane."""
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT field_value FROM task_state
               WHERE trace_id = ? AND task_id = ? AND field_name = ?""",
            (trace_id, task_id, field_name),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["field_value"])
        except (json.JSONDecodeError, TypeError):
            return row["field_value"]

    def get_all_task_outputs(self, trace_id: str) -> dict[str, Any]:
        """Read all task outputs for a trace (used by Scheduler for condition evaluation)."""
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT task_id, field_value FROM task_state
               WHERE trace_id = ? AND field_name = 'output'""",
            (trace_id,),
        )
        result: dict[str, Any] = {}
        for row in cursor.fetchall():
            try:
                result[row["task_id"]] = json.loads(row["field_value"])
            except (json.JSONDecodeError, TypeError):
                result[row["task_id"]] = row["field_value"]
        return result

    def get_all_task_errors(self, trace_id: str) -> dict[str, str]:
        """Read all task errors for a trace."""
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT task_id, field_value FROM task_state
               WHERE trace_id = ? AND field_name = 'error'""",
            (trace_id,),
        )
        result: dict[str, str] = {}
        for row in cursor.fetchall():
            try:
                val = json.loads(row["field_value"])
                result[row["task_id"]] = str(val)
            except (json.JSONDecodeError, TypeError):
                result[row["task_id"]] = str(row["field_value"])
        return result

    def delete_task_state(self, trace_id: str) -> None:
        """Clean up task state for a trace when it's no longer needed."""
        conn = self._get_conn()
        conn.execute("DELETE FROM task_state WHERE trace_id = ?", (trace_id,))
        conn.commit()

    # ── Legacy query interface ──

    def get_all_trace_ids(self) -> list[str]:
        """List all trace IDs in the store."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT DISTINCT trace_id FROM execution_records ORDER BY created_at DESC"
        )
        return [row["trace_id"] for row in cursor.fetchall()]

    # ── Aggregation ──

    def get_event_count(self) -> int:
        """Total number of events in the store."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) as count FROM events")
        return cursor.fetchone()["count"]

    def get_record_count(self) -> int:
        """Total number of execution records."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) as count FROM execution_records")
        return cursor.fetchone()["count"]

    def get_capability_stats(self) -> list[dict[str, Any]]:
        """
        Get execution statistics grouped by capability.

        Returns:
            List of dicts with: manifest_name, total_runs, success_count,
            failure_count, avg_latency, avg_cost, success_rate.
        """
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT
                manifest_name,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN status = 'failure' THEN 1 ELSE 0 END) as failure_count,
                AVG(total_latency_ms) as avg_latency_ms,
                AVG(total_cost_usd) as avg_cost_usd,
                AVG(total_tokens) as avg_tokens,
                ROUND(CAST(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS REAL)
                    / MAX(COUNT(*), 1), 4) as success_rate
            FROM execution_records
            GROUP BY manifest_name
            ORDER BY total_runs DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_runtime_stats(self) -> list[dict[str, Any]]:
        """
        Get execution statistics grouped by runtime.

        Returns:
            List of dicts with: runtime_id, total_runs, avg_latency, avg_cost.
        """
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT
                runtime_id,
                COUNT(*) as total_runs,
                AVG(total_latency_ms) as avg_latency_ms,
                AVG(total_cost_usd) as avg_cost_usd,
                AVG(total_tokens) as avg_tokens,
                ROUND(CAST(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS REAL)
                    / MAX(COUNT(*), 1), 4) as success_rate
            FROM execution_records
            GROUP BY runtime_id
            ORDER BY total_runs DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_time_series(
        self,
        interval: str = "hour",
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get execution counts over time.

        Args:
            interval: Grouping interval ('hour', 'day', 'week').
            since: ISO format start time (default: 7 days ago).

        Returns:
            List of dicts with: period, run_count, success_count, failure_count.
        """
        if since is None:
            since = datetime.now(timezone.utc).isoformat()

        interval_map = {
            "hour": "%Y-%m-%dT%H:00:00",
            "day": "%Y-%m-%d",
            "week": "%Y-%W",
        }
        format_str = interval_map.get(interval, "%Y-%m-%d")

        conn = self._get_conn()
        cursor = conn.execute(f"""
            SELECT
                strftime('{format_str}', created_at) as period,
                COUNT(*) as run_count,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN status = 'failure' THEN 1 ELSE 0 END) as failure_count,
                AVG(total_latency_ms) as avg_latency_ms,
                AVG(total_cost_usd) as avg_cost_usd
            FROM execution_records
            WHERE created_at >= COALESCE(?, created_at)
            GROUP BY period
            ORDER BY period ASC
        """, (since,))
        return [dict(row) for row in cursor.fetchall()]

    def get_failure_analysis(self) -> list[dict[str, Any]]:
        """
        Analyze failure patterns across all executions.

        Returns:
            List of dicts with common failure patterns.
        """
        conn = self._get_conn()
        # Get failed records grouped by error type (extracted from error message)
        cursor = conn.execute("""
            SELECT
                manifest_name,
                runtime_id,
                COUNT(*) as failure_count,
                AVG(total_latency_ms) as avg_latency_ms
            FROM execution_records
            WHERE status IN ('failure', 'partial')
            GROUP BY manifest_name, runtime_id
            ORDER BY failure_count DESC
            LIMIT 20
        """)
        return [dict(row) for row in cursor.fetchall()]

    def delete_old_records(self, before: str) -> int:
        """
        Delete records older than a given timestamp.

        Args:
            before: ISO format timestamp.

        Returns:
            Number of deleted records.
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM execution_records WHERE created_at < ?",
            (before,),
        )
        deleted = cursor.rowcount
        conn.commit()
        return deleted
