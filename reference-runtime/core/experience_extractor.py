"""
Intent OS — Experience Extractor (Blueprint Phase 2.3)

Mines the Event Store (and optionally the Evidence Store) for recurring
patterns and converts them into structured ``Experience`` records — the
foundation of the system's self-improvement learning loop.

Each extractor method targets a different dimension of execution
history: failure patterns, success strategies that emerged from retries,
cost-efficient tool/model preferences, and data-source reliability.

Design constraints:
  - Read-only against the Event / Evidence stores (never mutates source data)
  - Conservative: only creates Experiences when a pattern is backed by
    at least 3 occurrences
  - Deduplication: ``extract_all`` skips experiences whose observation
    text already exists in the Experience Store for the same agent

Usage::

    store = EventStore("path/to/store.db")
    exp_store = ExperienceStore()
    evidence = EvidenceStore()
    extractor = ExperienceExtractor(store, exp_store, evidence_store=evidence)

    results = extractor.extract_all("agent_a82f91c3")
    # -> {"failure_patterns": 3, "success_strategies": 2,
    #      "tool_preferences": 1, "data_source_reliability": 0}
"""

from __future__ import annotations

import re
import secrets
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.event_store import EventStore


# ────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────

_MIN_OCCURRENCES = 3          # minimum occurrences to create an Experience
_EXP_ID_PREFIX = "exp_"       # experience ID prefix
_EXP_ID_HEX_LEN = 12          # hex chars after prefix


# ────────────────────────────────────────────────────────────────
# Data Models
# ────────────────────────────────────────────────────────────────

@dataclass
class Experience:
    """A learned pattern extracted from execution history.

    Experiences are the system's memory of what works, what breaks,
    and what trade-offs exist.  They feed into agent decision-making
    and the Evolution Loop (SPEC-0003 Section 10).
    """

    experience_id: str
    agent_id: str
    type: str
    observation: str
    recommendation: str
    confidence: float = 0.5
    occurrence_count: int = 0
    source_data: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    # Canonical set of experience types
    VALID_TYPES: tuple[str, ...] = (
        "failure_pattern",
        "success_strategy",
        "tool_preference",
        "data_source_reliability",
    )


# ────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────

def _cutoff_iso(since_days: int) -> str:
    """Return an ISO-8601 timestamp *since_days* before now (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()


def _safe_round(value: float | None, ndigits: int = 4) -> float:
    """Round *value*, returning 0.0 when *value* is None."""
    if value is None:
        return 0.0
    return round(float(value), ndigits)


def _classify_error(error_text: str) -> str:
    """Map an error message to a coarse error category.

    The categories drive targeted remediation heuristics.
    """
    if not error_text:
        return "unknown"
    lower = error_text.lower()
    if "timeout" in lower or "timed out" in lower:
        return "timeout"
    if "rate" in lower and "limit" in lower:
        return "rate_limit"
    if "schema" in lower and ("mismatch" in lower or "invalid" in lower
                              or "unexpected" in lower or "validation" in lower):
        return "schema_mismatch"
    if "permission" in lower and ("denied" in lower or "forbidden" in lower
                                  or "unauthorized" in lower):
        return "permission_denied"
    if "connection" in lower or "refused" in lower or "network" in lower:
        return "connection_error"
    return "unknown"


def _heuristic_for_error_type(error_type: str, error_counts: dict[str, int]) -> str:
    """Return a concrete recommendation heuristic for a given error type."""
    heuristics = {
        "timeout": "Use smaller input contexts or split work into smaller batches "
                   "to avoid timeout. Consider increasing the timeout threshold "
                   "as a fallback.",
        "rate_limit": "Add exponential backoff with jitter between retries. "
                      "Implement a token-bucket rate limiter at the agent level "
                      "to stay within API quotas.",
        "schema_mismatch": "Validate the output against the declared schema before "
                           "returning. Add a post-processing step that coerces or "
                           "rejects malformed outputs with a structured error.",
        "permission_denied": "Request the minimum required scope at the start of "
                             "the workflow. If the operation requires elevated "
                             "privileges, surface a ReviewRequired event before "
                             "proceeding.",
        "connection_error": "Add retry logic with increasing backoff. Validate "
                            "network reachability before starting the capability. "
                            "Cache results from previous successful calls where "
                            "stale data is acceptable.",
        "unknown": "Add structured error handling around this capability call. "
                   "Log the full error payload and trace for post-mortem analysis. "
                   "Consider a fallback path or graceful degradation.",
    }
    return heuristics.get(error_type, heuristics["unknown"])


# ────────────────────────────────────────────────────────────────
# Experience Store (lightweight SQLite)
# ────────────────────────────────────────────────────────────────

CREATE_EXPERIENCES_TABLE = """
CREATE TABLE IF NOT EXISTS experiences (
    experience_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    type TEXT NOT NULL,
    observation TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    source_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_EXP_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_exp_agent_id ON experiences(agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_exp_type ON experiences(type);",
    "CREATE INDEX IF NOT EXISTS idx_exp_created ON experiences(created_at);",
]


class ExperienceStore:
    """SQLite-backed persistent store for Experience records.

    Follows the same connection pattern as other Data Plane stores.
    Each *Experience* is keyed by a unique ``experience_id`` (``exp_``
    prefix + 12 hex chars).

    Usage::

        store = ExperienceStore()
        store.save(exp)
        existing = store.find_by_observation("agent_1", "timeout errors...")
        all_exp = store.list_by_agent("agent_1", exp_type="failure_pattern")
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = str(Path.home() / ".intent-os" / "experiences.db")
        self._db_path = db_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(CREATE_EXPERIENCES_TABLE)
        for idx in CREATE_EXP_INDEXES:
            try:
                conn.execute(idx)
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    # ── CRUD ────────────────────────────────────────────────────

    def save(self, experience: Experience) -> None:
        """Persist an Experience (INSERT OR REPLACE by experience_id)."""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO experiences
                   (experience_id, agent_id, type, observation, recommendation,
                    confidence, occurrence_count, source_data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    experience.experience_id,
                    experience.agent_id,
                    experience.type,
                    experience.observation,
                    experience.recommendation,
                    experience.confidence,
                    experience.occurrence_count,
                    _safe_json_dumps(experience.source_data),
                    experience.created_at or _now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def find_by_observation(
        self, agent_id: str, observation: str
    ) -> Experience | None:
        """Return an existing Experience whose observation text matches exactly.

        Used by ``extract_all`` for deduplication.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT * FROM experiences
                   WHERE agent_id = ? AND observation = ?
                   LIMIT 1""",
                (agent_id, observation),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_experience(dict(row))
        finally:
            conn.close()

    def list_by_agent(
        self, agent_id: str, exp_type: str | None = None
    ) -> list[Experience]:
        """List all Experiences for an agent, optionally filtered by type."""
        conn = self._get_conn()
        try:
            if exp_type:
                cursor = conn.execute(
                    """SELECT * FROM experiences
                       WHERE agent_id = ? AND type = ?
                       ORDER BY created_at DESC""",
                    (agent_id, exp_type),
                )
            else:
                cursor = conn.execute(
                    """SELECT * FROM experiences
                       WHERE agent_id = ?
                       ORDER BY created_at DESC""",
                    (agent_id,),
                )
            return [_row_to_experience(dict(r)) for r in cursor.fetchall()]
        finally:
            conn.close()

    def list_all(self, exp_type: str | None = None) -> list[Experience]:
        """List all Experiences across all agents, optionally filtered by type."""
        conn = self._get_conn()
        try:
            if exp_type:
                cursor = conn.execute(
                    "SELECT * FROM experiences WHERE type = ? ORDER BY created_at DESC",
                    (exp_type,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM experiences ORDER BY created_at DESC"
                )
            return [_row_to_experience(dict(r)) for r in cursor.fetchall()]
        finally:
            conn.close()

    def delete(self, experience_id: str) -> bool:
        """Delete a single Experience by ID. Returns True if a row was removed."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM experiences WHERE experience_id = ?",
                (experience_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def count(self) -> int:
        """Total number of stored Experiences."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT COUNT(*) AS cnt FROM experiences")
            return cursor.fetchone()["cnt"]
        finally:
            conn.close()


# ────────────────────────────────────────────────────────────────
# Internal helpers
# ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json_dumps(obj: Any) -> str:
    """Serialize *obj* to JSON, falling back to ``str(obj)`` on failure."""
    import json as _json
    try:
        return _json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return str(obj)


def _row_to_experience(row: dict[str, Any]) -> Experience:
    """Convert a database row dict into an Experience instance."""
    import json as _json
    source_data_str = row.get("source_data", "{}") or "{}"
    try:
        source_data = _json.loads(source_data_str)
    except (_json.JSONDecodeError, TypeError):
        source_data = {}
    return Experience(
        experience_id=row["experience_id"],
        agent_id=row["agent_id"],
        type=row["type"],
        observation=row["observation"],
        recommendation=row["recommendation"],
        confidence=row["confidence"] or 0.5,
        occurrence_count=row["occurrence_count"] or 0,
        source_data=source_data,
        created_at=row["created_at"] or "",
    )


# ────────────────────────────────────────────────────────────────
# Experience Extractor
# ────────────────────────────────────────────────────────────────

class ExperienceExtractor:
    """Mines execution and evidence stores for actionable patterns.

    Each ``extract_*`` method returns a list of :class:`Experience`
    instances.  ``extract_all`` runs every extractor and persists
    new (non-duplicate) experiences to the *experience_store*.

    Constructor args:
        event_store: An :class:`EventStore` instance (required).
        experience_store: An :class:`ExperienceStore` instance (required).
        evidence_store: An optional :class:`EvidenceStore` instance.
            If omitted, ``extract_data_source_reliability`` returns
            an empty list gracefully.
    """

    __slots__ = ("_store", "_exp_store", "_evidence_store")

    def __init__(
        self,
        event_store: EventStore,
        experience_store: ExperienceStore,
        evidence_store: Any | None = None,
    ) -> None:
        self._store = event_store
        self._exp_store = experience_store
        self._evidence_store = evidence_store

    # ── Internal helpers ───────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Thread-local SQLite connection from the backing EventStore."""
        return self._store.get_connection()

    @staticmethod
    def _generate_experience_id() -> str:
        """Return ``exp_`` + 12 random hex characters."""
        return f"{_EXP_ID_PREFIX}{secrets.token_hex(_EXP_ID_HEX_LEN // 2)}"

    def _is_duplicate(self, agent_id: str, observation: str) -> bool:
        """Check whether an experience with the same observation already exists."""
        existing = self._exp_store.find_by_observation(agent_id, observation)
        return existing is not None

    # ────────────────────────────────────────────────────────────────
    # Extractor 1: Failure Patterns
    # ────────────────────────────────────────────────────────────────

    def extract_failure_patterns(
        self, agent_id: str, since_days: int = 30
    ) -> list[Experience]:
        """Identify recurring failure patterns for *agent_id*.

        Queries failed/partial execution records within the time window,
        groups by classified error type, and creates an Experience for
        each error type that appears at least ``_MIN_OCCURRENCES`` times.

        Recommendation heuristics:
            *timeout*          -> use smaller contexts
            *rate_limit*       -> add exponential backoff
            *schema_mismatch*  -> validate output schema
            *permission_denied* -> request minimum scope
            *connection_error* -> retry with backoff / cache results
            *unknown*          -> add structured error handling
        """
        cutoff = _cutoff_iso(since_days)
        conn = self._conn()

        rows = conn.execute(
            """SELECT error, runtime_id, manifest_name, trace_id
               FROM execution_records
               WHERE agent_id = ?
                 AND status IN ('failure', 'partial')
                 AND error IS NOT NULL
                 AND error != ''
                 AND created_at >= ?
               ORDER BY created_at DESC""",
            (agent_id, cutoff),
        ).fetchall()

        if not rows:
            return []

        # Classify errors into typed buckets
        typed: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            error_text = row["error"] or ""
            category = _classify_error(error_text)
            typed[category].append({
                "error": error_text,
                "runtime_id": row["runtime_id"],
                "manifest_name": row["manifest_name"],
                "trace_id": row["trace_id"],
            })

        experiences: list[Experience] = []
        for error_type, entries in typed.items():
            count = len(entries)
            if count < _MIN_OCCURRENCES:
                continue

            # Most frequent specific error messages for richer observation
            error_counter = Counter(e["error"] for e in entries)
            top_errors = error_counter.most_common(3)
            manifests = Counter(e["manifest_name"] for e in entries if e["manifest_name"])

            observation = (
                f"Agent {agent_id} experienced {count} failures of type "
                f"'{error_type}' in the last {since_days} days. "
                f"Top error: '{top_errors[0][0][:200]}' ({top_errors[0][1]}x). "
                f"Affected capabilities: {', '.join(m for m, _ in manifests.most_common(3))}."
            )

            recommendation = _heuristic_for_error_type(error_type, dict(error_counter))

            # Confidence scales with count and consistency
            purity = top_errors[0][1] / count if top_errors else 0.5
            confidence = min(0.95, 0.4 + 0.1 * min(count, 5) + 0.1 * purity)

            experiences.append(Experience(
                experience_id=self._generate_experience_id(),
                agent_id=agent_id,
                type="failure_pattern",
                observation=observation,
                recommendation=recommendation,
                confidence=_safe_round(confidence, 4),
                occurrence_count=count,
                source_data={
                    "error_type": error_type,
                    "top_errors": [[e, c] for e, c in top_errors],
                    "affected_capabilities": dict(manifests.most_common(5)),
                    "sample_trace_ids": [e["trace_id"] for e in entries[:5]],
                    "since_days": since_days,
                },
                created_at=_now_iso(),
            ))

        return experiences

    # ────────────────────────────────────────────────────────────────
    # Extractor 2: Success Strategies
    # ────────────────────────────────────────────────────────────────

    def extract_success_strategies(
        self, agent_id: str, since_days: int = 30
    ) -> list[Experience]:
        """Discover strategies that turned failures into successes.

        Finds execution traces where a task failed, was retried, and
        then completed successfully (the TASK_FAILED -> TASK_RETRIED
        -> TASK_COMPLETED pattern).  Groups these recoveries by capability
        and extracts what changed between the failed and successful
        attempts.

        Only creates an Experience when at least ``_MIN_OCCURRENCES``
        distinct capabilities exhibit the recovery pattern.
        """
        cutoff = _cutoff_iso(since_days)
        conn = self._conn()

        # Get all trace_ids for this agent in the time window
        trace_rows = conn.execute(
            """SELECT DISTINCT e.trace_id
               FROM events e
               JOIN execution_records er ON e.trace_id = er.trace_id
               WHERE er.agent_id = ?
                 AND e.timestamp >= ?
                 AND e.event_type IN ('TaskFailed', 'TaskRetried', 'TaskCompleted')""",
            (agent_id, cutoff),
        ).fetchall()

        if not trace_rows:
            return []

        trace_ids = [r["trace_id"] for r in trace_rows]

        # Fetch all lifecycle events for those traces
        # Use parameterised IN clause (safe: trace_ids come from the DB, not user input)
        placeholders = ",".join("?" for _ in trace_ids)
        events_rows = conn.execute(
            f"""SELECT trace_id, event_type, task_id, capability, payload, metrics, timestamp
                FROM events
                WHERE trace_id IN ({placeholders})
                  AND event_type IN ('TaskFailed', 'TaskRetried', 'TaskCompleted')
                ORDER BY trace_id, sequence ASC""",
            trace_ids,
        ).fetchall()

        # Group events by (trace_id, task_id_or_capability)
        # A "recovery" is when we see TASK_FAILED + (TASK_RETRIED or not) + TASK_COMPLETED
        trace_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in events_rows:
            trace_events[row["trace_id"]].append(dict(row))

        # Per-capability recovery tracking
        recovery_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for trace_id, events in trace_events.items():
            has_failed = any(e["event_type"] == "TaskFailed" for e in events)
            has_retried = any(e["event_type"] == "TaskRetried" for e in events)
            has_completed = any(e["event_type"] == "TaskCompleted" for e in events)

            if has_failed and (has_retried or has_completed) and has_completed:
                # Collect capabilities involved
                capabilities: set[str] = set()
                for e in events:
                    cap = e.get("capability") or e.get("task_id") or "unknown"
                    capabilities.add(cap)

                failed_events = [e for e in events if e["event_type"] == "TaskFailed"]
                completed_events = [e for e in events if e["event_type"] == "TaskCompleted"]

                for cap in capabilities:
                    recovery_map[cap].append({
                        "trace_id": trace_id,
                        "failed_count": len(failed_events),
                        "retried": has_retried,
                        "completed_count": len(completed_events),
                    })

        experiences: list[Experience] = []
        for capability, recoveries in recovery_map.items():
            count = len(recoveries)
            if count < _MIN_OCCURRENCES:
                continue

            retried_count = sum(1 for r in recoveries if r["retried"])
            sample_traces = [r["trace_id"] for r in recoveries[:5]]

            observation = (
                f"Capability '{capability}' recovered from failure {count} times "
                f"in the last {since_days} days. {retried_count}/{count} recoveries "
                f"involved an explicit retry. Sample traces: {', '.join(sample_traces[:3])}."
            )

            recommendation = (
                f"For capability '{capability}': the failure-to-success recovery "
                f"pattern succeeded {count} times. Formalize the recovery steps as "
                f"a documented retry strategy. If a retry was involved in "
                f"{retried_count}/{count} cases, ensure the retry preserves enough "
                f"context to diagnose the original failure. Consider adding a "
                f"pre-flight check before invoking this capability."
            )

            confidence = min(0.9, 0.4 + 0.1 * min(count, 5))

            experiences.append(Experience(
                experience_id=self._generate_experience_id(),
                agent_id=agent_id,
                type="success_strategy",
                observation=observation,
                recommendation=recommendation,
                confidence=_safe_round(confidence, 4),
                occurrence_count=count,
                source_data={
                    "capability": capability,
                    "recovery_count": count,
                    "retried_count": retried_count,
                    "sample_trace_ids": sample_traces,
                    "since_days": since_days,
                },
                created_at=_now_iso(),
            ))

        return experiences

    # ────────────────────────────────────────────────────────────────
    # Extractor 3: Tool / Model Preferences
    # ────────────────────────────────────────────────────────────────

    def extract_tool_preferences(
        self, agent_id: str, since_days: int = 30
    ) -> list[Experience]:
        """Compare cost and token efficiency across models for the same capability.

        For each capability (manifest_name) used by the agent, compares all
        models (runtime_id) that executed it.  When one model is at least 20%
        cheaper per execution than another for the same task, a preference
        Experience is created.

        Only creates Experiences when the comparison is backed by at least
        ``_MIN_OCCURRENCES`` executions per model.
        """
        cutoff = _cutoff_iso(since_days)
        conn = self._conn()

        # Per-capability, per-model cost roll-up
        rows = conn.execute(
            """SELECT
                 manifest_name,
                 runtime_id,
                 COUNT(*)                           AS exec_count,
                 AVG(total_cost_usd)                AS avg_cost_usd,
                 AVG(total_tokens)                  AS avg_tokens,
                 AVG(total_latency_ms)              AS avg_latency_ms,
                 SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count
               FROM execution_records
               WHERE agent_id = ?
                 AND created_at >= ?
                 AND manifest_name IS NOT NULL
                 AND manifest_name != ''
                 AND runtime_id IS NOT NULL
                 AND runtime_id != ''
               GROUP BY manifest_name, runtime_id
               ORDER BY manifest_name, avg_cost_usd ASC""",
            (agent_id, cutoff),
        ).fetchall()

        if not rows:
            return []

        # Group by capability
        by_capability: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_capability[row["manifest_name"]].append(dict(row))

        experiences: list[Experience] = []
        for capability, models in by_capability.items():
            if len(models) < 2:
                continue  # Need at least 2 models to compare

            # Sort by avg_cost ascending (cheapest first)
            models.sort(key=lambda m: m["avg_cost_usd"] or 0)

            cheapest = models[0]
            for other in models[1:]:
                cheap_cost = cheapest["avg_cost_usd"] or 0
                other_cost = other["avg_cost_usd"] or 0
                cheap_count = cheapest["exec_count"] or 0
                other_count = other["exec_count"] or 0

                if cheap_cost <= 0 or other_cost <= 0:
                    continue
                if cheap_count < _MIN_OCCURRENCES or other_count < _MIN_OCCURRENCES:
                    continue

                savings_pct = (1 - cheap_cost / other_cost) * 100
                if savings_pct < 20:
                    continue  # Not a meaningful enough difference

                # Check token efficiency too
                cheap_tok = cheapest["avg_tokens"] or 0
                other_tok = other["avg_tokens"] or 0
                token_savings_pct = (
                    (1 - cheap_tok / other_tok) * 100 if other_tok > 0 else 0
                )

                cheap_model = cheapest["runtime_id"]
                other_model = other["runtime_id"]

                observation = (
                    f"For capability '{capability}', model '{cheap_model}' "
                    f"costs {savings_pct:.0f}% less than '{other_model}' "
                    f"(avg ${cheap_cost:.4f} vs ${other_cost:.4f} per execution). "
                    f"Token savings: {token_savings_pct:.0f}%. "
                    f"Success rates: {cheap_model}={_safe_round(cheapest['success_count'] / max(cheap_count, 1), 2)}, "
                    f"{other_model}={_safe_round(other['success_count'] / max(other_count, 1), 2)}."
                )

                recommendation = (
                    f"Prefer model '{cheap_model}' over '{other_model}' for "
                    f"capability '{capability}'. It delivers comparable results "
                    f"at {savings_pct:.0f}% lower cost. "
                    f"Re-evaluate if the success-rate gap exceeds 5%."
                )

                confidence = min(0.9, 0.4 + 0.05 * min(savings_pct, 10))

                experiences.append(Experience(
                    experience_id=self._generate_experience_id(),
                    agent_id=agent_id,
                    type="tool_preference",
                    observation=observation,
                    recommendation=recommendation,
                    confidence=_safe_round(confidence, 4),
                    occurrence_count=min(cheap_count, other_count),
                    source_data={
                        "capability": capability,
                        "preferred_model": cheap_model,
                        "alternative_model": other_model,
                        "cost_savings_pct": _safe_round(savings_pct, 1),
                        "token_savings_pct": _safe_round(token_savings_pct, 1),
                        "cheap_avg_cost": _safe_round(cheap_cost, 6),
                        "other_avg_cost": _safe_round(other_cost, 6),
                        "cheap_exec_count": cheap_count,
                        "other_exec_count": other_count,
                        "since_days": since_days,
                    },
                    created_at=_now_iso(),
                ))

        return experiences

    # ────────────────────────────────────────────────────────────────
    # Extractor 4: Data Source Reliability
    # ────────────────────────────────────────────────────────────────

    def extract_data_source_reliability(
        self, agent_id: str, since_days: int = 30
    ) -> list[Experience]:
        """Flag data sources whose evidence confidence is below threshold.

        Queries the Evidence Store for all evidence records related to
        executions by *agent_id*, groups by ``source_ref``, and flags
        sources whose average confidence falls below 0.6 (on a 0.0–1.0
        scale).

        Gracefully returns an empty list when no evidence store is
        available or no evidence data exists for the agent.
        """
        if self._evidence_store is None:
            return []

        cutoff = _cutoff_iso(since_days)

        # Evidence records have an execution_id that links to trace_id.
        # We need to intersect: evidence where execution_id matches a
        # trace_id from execution_records for this agent.
        conn = self._conn()
        agent_traces = conn.execute(
            """SELECT trace_id FROM execution_records
               WHERE agent_id = ?
                 AND created_at >= ?""",
            (agent_id, cutoff),
        ).fetchall()

        if not agent_traces:
            return []

        trace_id_set = {r["trace_id"] for r in agent_traces}

        # Query the Evidence Store for all records
        evidence_conn = self._evidence_store._get_conn()
        try:
            evidence_rows = evidence_conn.execute(
                """SELECT evidence_id, execution_id, claim, source_ref,
                          confidence, source_type, verified
                   FROM evidence
                   ORDER BY created_at DESC"""
            ).fetchall()
        finally:
            evidence_conn.close()

        # Filter to evidence tied to this agent's traces
        agent_evidence = [
            dict(r) for r in evidence_rows
            if r["execution_id"] in trace_id_set
        ]

        if not agent_evidence:
            return []

        # Group by source_ref
        by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ev in agent_evidence:
            source_ref = ev.get("source_ref") or "unknown_source"
            by_source[source_ref].append(ev)

        experiences: list[Experience] = []
        for source_ref, entries in by_source.items():
            count = len(entries)
            if count < _MIN_OCCURRENCES:
                continue

            confidences = [e["confidence"] for e in entries if e["confidence"] is not None]
            if not confidences:
                continue

            avg_confidence = sum(confidences) / len(confidences)
            if avg_confidence >= 0.6:
                continue  # Only flag low-confidence sources

            verified_count = sum(1 for e in entries if e.get("verified"))

            observation = (
                f"Data source '{source_ref}' has low average confidence "
                f"({avg_confidence:.2f}) across {count} evidence records "
                f"in the last {since_days} days. "
                f"Only {verified_count}/{count} records have been verified."
            )

            recommendation = (
                f"Cross-verify data from source '{source_ref}' with at least "
                f"one alternative source before relying on it for decisions. "
                f"Consider running a calibration check: compare recent outputs "
                f"from this source against a trusted ground-truth dataset."
            )

            confidence = min(0.85, 0.5 + 0.1 * min(count, 5))

            experiences.append(Experience(
                experience_id=self._generate_experience_id(),
                agent_id=agent_id,
                type="data_source_reliability",
                observation=observation,
                recommendation=recommendation,
                confidence=_safe_round(confidence, 4),
                occurrence_count=count,
                source_data={
                    "source_ref": source_ref,
                    "avg_confidence": _safe_round(avg_confidence, 4),
                    "evidence_count": count,
                    "verified_count": verified_count,
                    "sample_evidence_ids": [e["evidence_id"] for e in entries[:5]],
                    "since_days": since_days,
                },
                created_at=_now_iso(),
            ))

        return experiences

    # ────────────────────────────────────────────────────────────────
    # Extractor 5: Run All + Persist
    # ────────────────────────────────────────────────────────────────

    def extract_all(
        self, agent_id: str, since_days: int = 30
    ) -> dict[str, int]:
        """Run all four extractors and persist new Experiences.

        Deduplication: an Experience is skipped if one with the same
        ``agent_id`` and ``observation`` text already exists in the
        Experience Store.

        Returns a dict mapping each experience type to the count of
        *new* experiences that were saved::

            {
              "failure_patterns": 3,
              "success_strategies": 1,
              "tool_preferences": 2,
              "data_source_reliability": 0,
            }
        """
        all_experiences: list[Experience] = []

        # Collect from each extractor
        all_experiences.extend(
            self.extract_failure_patterns(agent_id, since_days=since_days)
        )
        all_experiences.extend(
            self.extract_success_strategies(agent_id, since_days=since_days)
        )
        all_experiences.extend(
            self.extract_tool_preferences(agent_id, since_days=since_days)
        )
        all_experiences.extend(
            self.extract_data_source_reliability(agent_id, since_days=since_days)
        )

        # Deduplicate and persist
        counts: dict[str, int] = defaultdict(int)
        for exp in all_experiences:
            if self._is_duplicate(agent_id, exp.observation):
                continue
            self._exp_store.save(exp)
            # Map type to counter key
            key_map = {
                "failure_pattern": "failure_patterns",
                "success_strategy": "success_strategies",
                "tool_preference": "tool_preferences",
                "data_source_reliability": "data_source_reliability",
            }
            counts[key_map.get(exp.type, exp.type)] += 1

        return {
            "failure_patterns": counts.get("failure_patterns", 0),
            "success_strategies": counts.get("success_strategies", 0),
            "tool_preferences": counts.get("tool_preferences", 0),
            "data_source_reliability": counts.get("data_source_reliability", 0),
        }
