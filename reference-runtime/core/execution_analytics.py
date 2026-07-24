"""
Intent OS — Agent Execution Analytics (Blueprint Phase 2.2)

Agent-centric analytics built on top of Event Store data.

Provides per-agent performance summaries, daily timelines, side-by-side
comparisons, anomaly detection, and model/agent aggregation.

Dual data source: queries both the ``events`` table (proxy-captured
LlmCall telemetry) and the ``execution_records`` table (executor
CapabilityInvoked records).  Results are merged so that the caller
sees a unified view of every agent execution regardless of how it was
recorded.

Usage::

    store = EventStore("path/to/store.db")
    analytics = AgentAnalytics(store)

    summary = analytics.agent_summary("agent_a82f91c3")
    timeline = analytics.agent_timeline("agent_a82f91c3", since_days=30)
    comparison = analytics.agent_compare("agent_a", "agent_b")
    anomalies = analytics.detect_anomalies(since_days=7)
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from core.event_store import EventStore


# ────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────

_ANOMALY_MULTIPLIER = 3.0        # >3x historical avg triggers alert
_MIN_BASELINE_EXECUTIONS = 5     # skip anomaly detection below this
_MAX_FAILURE_REASONS = 10
_MAX_MODELS = 50


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


def _coalesce(*values: Any) -> Any:
    """Return the first non-None, non-empty value."""
    for v in values:
        if v is not None and v != "":
            return v
    return values[-1] if values else None


def _parse_json_cell(raw: str | None) -> dict[str, Any]:
    """Safely parse a JSON cell, returning ``{}`` on failure."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


# ────────────────────────────────────────────────────────────────
# AgentAnalytics
# ────────────────────────────────────────────────────────────────

class AgentAnalytics:
    """
    Agent-focused execution analytics engine.

    Wraps an :class:`EventStore` and provides per-agent metrics,
    daily timelines, pair-wise comparison, anomaly detection, and
    model/agent roll-ups.

    All public methods are read-only — they never mutate the store.
    """

    __slots__ = ("_store",)

    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store

    # ── Internal helpers ──────────────────────────────────────

    def _conn(self):
        """Thread-local SQLite connection from the backing EventStore."""
        return self._store.get_connection()

    # ──────────────────────────────────────────────────────────
    # Agent Summary
    # ──────────────────────────────────────────────────────────

    def agent_summary(self, agent_id: str) -> dict[str, Any]:
        """
        Full-dimensional summary for a single agent.

        Returns a dict with keys:

        * **agent_id** — echo of the requested ID
        * **success_rate** — float 0.0–1.0
        * **avg_latency_ms** — mean latency in milliseconds
        * **total_cost_usd** — cumulative USD cost
        * **total_tokens** — cumulative token count
        * **total_executions** — number of execution records
        * **failure_count** — number of failed/partial records
        * **top_failure_reasons** — list of ``{error, count}``
        * **models_used** — distinct model/runtime IDs seen
        * **first_seen / last_seen** — ISO timestamps
        """
        conn = self._conn()

        # ── execution_records roll-up ─────────────────────────
        row = conn.execute(
            """SELECT
                 COUNT(*)                          AS total_executions,
                 SUM(CASE WHEN status = 'success'  THEN 1 ELSE 0 END) AS success_count,
                 SUM(CASE WHEN status = 'failure'  THEN 1 ELSE 0 END) AS failure_count,
                 SUM(CASE WHEN status = 'partial'  THEN 1 ELSE 0 END) AS partial_count,
                 AVG(total_latency_ms)             AS avg_latency_ms,
                 COALESCE(SUM(total_cost_usd), 0)  AS total_cost_usd,
                 COALESCE(SUM(total_tokens), 0)    AS total_tokens,
                 MIN(created_at)                   AS first_seen,
                 MAX(created_at)                   AS last_seen
               FROM execution_records
               WHERE agent_id = ?""",
            (agent_id,),
        ).fetchone()

        # ── Augment with proxy event data ─────────────────────
        proxy = conn.execute(
            """SELECT
                 COUNT(*)                          AS proxy_calls,
                 COALESCE(SUM(CAST(
                   json_extract(payload, '$.total_tokens') AS REAL)), 0) AS proxy_tokens,
                 COALESCE(SUM(CAST(
                   json_extract(payload, '$.cost_usd') AS REAL)), 0)    AS proxy_cost
               FROM events
               WHERE source = 'proxy'
                 AND json_extract(payload, '$.source_agent') = ?""",
            (agent_id,),
        ).fetchone()

        total_executions = (row["total_executions"] or 0) + (proxy["proxy_calls"] or 0)
        success_count = row["success_count"] or 0
        failure_count = (row["failure_count"] or 0) + (row["partial_count"] or 0)

        # Merge cost / tokens from both sources
        total_cost = (row["total_cost_usd"] or 0) + (proxy["proxy_cost"] or 0)
        total_tokens = int((row["total_tokens"] or 0) + (proxy["proxy_tokens"] or 0))

        # Compute success rate on everything we can score
        success_rate = (success_count / max(total_executions, 1))

        # Latency is only available on execution_records
        avg_latency = _safe_round(row["avg_latency_ms"], 1)

        # ── Top failure reasons (from execution_records) ──────
        fail_rows = conn.execute(
            """SELECT error, COUNT(*) AS cnt
               FROM execution_records
               WHERE agent_id = ?
                 AND status IN ('failure', 'partial')
                 AND error IS NOT NULL
                 AND error != ''
               GROUP BY error
               ORDER BY cnt DESC
               LIMIT ?""",
            (agent_id, _MAX_FAILURE_REASONS),
        ).fetchall()

        top_failure_reasons: list[dict[str, Any]] = [
            {"error": r["error"], "count": r["cnt"]} for r in fail_rows
        ]

        # Also extract failure reasons from proxy-event errors
        proxy_fails = conn.execute(
            """SELECT json_extract(payload, '$.error') AS error,
                      COUNT(*) AS cnt
               FROM events
               WHERE source = 'proxy'
                 AND json_extract(payload, '$.source_agent') = ?
                 AND json_extract(payload, '$.status') = 'failure'
                 AND json_extract(payload, '$.error') IS NOT NULL
               GROUP BY error
               ORDER BY cnt DESC
               LIMIT ?""",
            (agent_id, _MAX_FAILURE_REASONS),
        ).fetchall()

        for r in proxy_fails:
            if r["error"]:
                top_failure_reasons.append(
                    {"error": r["error"], "count": r["cnt"]}
                )
        top_failure_reasons.sort(key=lambda x: -x["count"])
        top_failure_reasons = top_failure_reasons[:_MAX_FAILURE_REASONS]

        # ── Models used ───────────────────────────────────────
        exec_models = conn.execute(
            """SELECT DISTINCT runtime_id
               FROM execution_records
               WHERE agent_id = ?
                 AND runtime_id IS NOT NULL
                 AND runtime_id != ''
               LIMIT ?""",
            (agent_id, _MAX_MODELS),
        ).fetchall()

        proxy_models = conn.execute(
            """SELECT DISTINCT json_extract(payload, '$.model') AS model
               FROM events
               WHERE source = 'proxy'
                 AND json_extract(payload, '$.source_agent') = ?
                 AND json_extract(payload, '$.model') IS NOT NULL
                 AND json_extract(payload, '$.model') != ''
               LIMIT ?""",
            (agent_id, _MAX_MODELS),
        ).fetchall()

        models_used: list[str] = sorted(
            {r["runtime_id"] for r in exec_models if r["runtime_id"]}
            | {r["model"] for r in proxy_models if r["model"]}
        )

        return {
            "agent_id": agent_id,
            "success_rate": _safe_round(success_rate, 4),
            "avg_latency_ms": avg_latency,
            "total_cost_usd": _safe_round(total_cost, 4),
            "total_tokens": total_tokens,
            "total_executions": total_executions,
            "failure_count": failure_count,
            "top_failure_reasons": top_failure_reasons,
            "models_used": models_used,
            "first_seen": row["first_seen"] or None,
            "last_seen": row["last_seen"] or None,
        }

    # ──────────────────────────────────────────────────────────
    # Agent Timeline
    # ──────────────────────────────────────────────────────────

    def agent_timeline(
        self,
        agent_id: str,
        since_days: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Daily execution buckets for *agent_id*.

        Each bucket:

        * **date** — ``YYYY-MM-DD``
        * **executions** — total count
        * **success** — successful count
        * **failure** — failed count (includes partial)
        * **cost_usd** — total cost for the day
        * **avg_latency_ms** — mean latency for the day
        * **tokens** — total tokens consumed
        """
        cutoff = _cutoff_iso(since_days)
        conn = self._conn()

        rows = conn.execute(
            """SELECT
                 DATE(created_at)         AS date,
                 COUNT(*)                 AS executions,
                 SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
                 SUM(CASE WHEN status IN ('failure', 'partial')
                          THEN 1 ELSE 0 END) AS failure,
                 COALESCE(SUM(total_cost_usd), 0) AS cost_usd,
                 AVG(total_latency_ms)    AS avg_latency_ms,
                 COALESCE(SUM(total_tokens), 0) AS tokens
               FROM execution_records
               WHERE agent_id = ?
                 AND created_at >= ?
               GROUP BY DATE(created_at)
               ORDER BY date ASC""",
            (agent_id, cutoff),
        ).fetchall()

        # Merge proxy events into the same date buckets
        proxy_rows = conn.execute(
            """SELECT
                 DATE(timestamp)          AS date,
                 COUNT(*)                 AS proxy_calls,
                 COALESCE(SUM(CAST(json_extract(payload, '$.cost_usd') AS REAL)), 0) AS proxy_cost,
                 COALESCE(SUM(CAST(json_extract(payload, '$.total_tokens') AS REAL)), 0) AS proxy_tokens,
                 SUM(CASE WHEN json_extract(payload, '$.status') = 'failure'
                          THEN 1 ELSE 0 END) AS proxy_failures
               FROM events
               WHERE source = 'proxy'
                 AND json_extract(payload, '$.source_agent') = ?
                 AND timestamp >= ?
               GROUP BY DATE(timestamp)
               ORDER BY date ASC""",
            (agent_id, cutoff),
        ).fetchall()

        # Index proxy data by date for merging
        proxy_by_date: dict[str, dict[str, Any]] = {
            r["date"]: r for r in proxy_rows
        }

        timeline: list[dict[str, Any]] = []
        for row in rows:
            date_str = row["date"]
            pd = proxy_by_date.pop(date_str, None)
            proxy_calls = pd["proxy_calls"] if pd else 0
            proxy_cost = pd["proxy_cost"] if pd else 0
            proxy_tokens = int(pd["proxy_tokens"] or 0) if pd else 0
            proxy_fails = pd["proxy_failures"] if pd else 0

            timeline.append({
                "date": date_str,
                "executions": (row["executions"] or 0) + proxy_calls,
                "success": (row["success"] or 0) + (proxy_calls - proxy_fails),
                "failure": (row["failure"] or 0) + proxy_fails,
                "cost_usd": _safe_round((row["cost_usd"] or 0) + proxy_cost, 4),
                "avg_latency_ms": _safe_round(row["avg_latency_ms"], 1),
                "tokens": int(row["tokens"] or 0) + proxy_tokens,
            })

        # Any proxy-only dates that had no execution_records
        for date_str, pd in sorted(proxy_by_date.items()):
            proxy_calls = pd["proxy_calls"] or 0
            timeline.append({
                "date": date_str,
                "executions": proxy_calls,
                "success": proxy_calls - (pd["proxy_failures"] or 0),
                "failure": pd["proxy_failures"] or 0,
                "cost_usd": _safe_round(pd["proxy_cost"], 4),
                "avg_latency_ms": 0.0,
                "tokens": int(pd["proxy_tokens"] or 0),
            })

        # Re-sort after merging proxy-only dates
        timeline.sort(key=lambda b: b["date"])
        return timeline

    # ──────────────────────────────────────────────────────────
    # Agent Comparison
    # ──────────────────────────────────────────────────────────

    def agent_compare(self, agent_id_a: str, agent_id_b: str) -> dict[str, Any]:
        """
        Side-by-side comparison of two agents.

        Returns::

            {
              "agent_a": { ... agent_summary(agent_id_a) ... },
              "agent_b": { ... agent_summary(agent_id_b) ... },
              "delta": {
                "success_rate_diff": ...,
                "avg_latency_ratio": ...,
                "cost_diff_usd": ...,
                "winner": "agent_a" | "agent_b" | "tie"
              }
            }
        """
        summary_a = self.agent_summary(agent_id_a)
        summary_b = self.agent_summary(agent_id_b)

        # Compute deltas
        sr_diff = _safe_round(
            summary_a["success_rate"] - summary_b["success_rate"], 4
        )

        lat_a = summary_a["avg_latency_ms"]
        lat_b = summary_b["avg_latency_ms"]
        lat_ratio = _safe_round(lat_a / max(lat_b, 0.001), 2)

        cost_diff = _safe_round(
            summary_a["total_cost_usd"] - summary_b["total_cost_usd"], 4
        )

        # Simple composite winner heuristic
        score_a = 0
        score_b = 0
        if summary_a["success_rate"] > summary_b["success_rate"]:
            score_a += 1
        elif summary_b["success_rate"] > summary_a["success_rate"]:
            score_b += 1
        if lat_a < lat_b:
            score_a += 1
        elif lat_b < lat_a:
            score_b += 1
        if summary_a["total_cost_usd"] < summary_b["total_cost_usd"]:
            score_a += 1
        elif summary_b["total_cost_usd"] < summary_a["total_cost_usd"]:
            score_b += 1

        if score_a > score_b:
            winner = "agent_a"
        elif score_b > score_a:
            winner = "agent_b"
        else:
            winner = "tie"

        return {
            "agent_a": summary_a,
            "agent_b": summary_b,
            "delta": {
                "success_rate_diff": sr_diff,
                "avg_latency_ratio": lat_ratio,
                "cost_diff_usd": cost_diff,
                "winner": winner,
                "score_a": score_a,
                "score_b": score_b,
            },
        }

    # ──────────────────────────────────────────────────────────
    # Anomaly Detection
    # ──────────────────────────────────────────────────────────

    def detect_anomalies(self, since_days: int = 7) -> list[dict[str, Any]]:
        """
        Scan recent executions for metric spikes.

        Baseline is computed from all data **older** than *since_days*.
        Any execution in the recent window whose cost, latency, or
        token count exceeds **3x** the historical average is flagged.

        Returns a list of anomaly dicts::

            {
              "trace_id": str,
              "agent_name": str,
              "anomaly_type": "cost_spike" | "latency_spike" | "token_spike",
              "value": float,
              "baseline_avg": float,
              "threshold": float,
              "ratio": float,
              "detail": str,
              "timestamp": str,
            }

        Agents with fewer than ``_MIN_BASELINE_EXECUTIONS`` historical
        runs are excluded from anomaly detection (no meaningful baseline).
        """
        cutoff = _cutoff_iso(since_days)
        conn = self._conn()

        # ── Historical baselines (everything BEFORE the window) ──
        baselines = conn.execute(
            """SELECT
                 AVG(total_cost_usd)     AS avg_cost,
                 AVG(total_latency_ms)   AS avg_latency,
                 AVG(total_tokens)       AS avg_tokens,
                 COUNT(*)                AS baseline_count
               FROM execution_records
               WHERE created_at < ?""",
            (cutoff,),
        ).fetchone()

        baseline_cost = baselines["avg_cost"] or 0.0
        baseline_lat = baselines["avg_latency"] or 0.0
        baseline_tok = baselines["avg_tokens"] or 0.0
        baseline_count = baselines["baseline_count"] or 0

        anomalies: list[dict[str, Any]] = []

        if baseline_count < _MIN_BASELINE_EXECUTIONS:
            # Not enough history — scan with per-agent baselines
            return self._detect_anomalies_per_agent(cutoff, since_days)

        # ── Global thresholds ─────────────────────────────────
        cost_threshold = baseline_cost * _ANOMALY_MULTIPLIER
        lat_threshold = baseline_lat * _ANOMALY_MULTIPLIER
        tok_threshold = baseline_tok * _ANOMALY_MULTIPLIER

        # ── Recent execution_records ──────────────────────────
        rows = conn.execute(
            """SELECT
                 trace_id,
                 COALESCE(agent_name, agent_id, 'unknown') AS agent_name,
                 total_cost_usd,
                 total_latency_ms,
                 total_tokens,
                 status,
                 created_at
               FROM execution_records
               WHERE created_at >= ?
               ORDER BY created_at DESC""",
            (cutoff,),
        ).fetchall()

        for row in rows:
            cost = row["total_cost_usd"] or 0.0
            lat = row["total_latency_ms"] or 0.0
            tok = row["total_tokens"] or 0.0

            if cost > cost_threshold and baseline_cost > 0:
                ratio = cost / max(baseline_cost, 0.0001)
                anomalies.append({
                    "trace_id": row["trace_id"],
                    "agent_name": row["agent_name"],
                    "anomaly_type": "cost_spike",
                    "value": _safe_round(cost, 4),
                    "baseline_avg": _safe_round(baseline_cost, 4),
                    "threshold": _safe_round(cost_threshold, 4),
                    "ratio": _safe_round(ratio, 2),
                    "detail": (
                        f"Cost ${cost:.4f} is {ratio:.1f}x the historical "
                        f"average of ${baseline_cost:.4f}"
                    ),
                    "timestamp": row["created_at"],
                })

            if lat > lat_threshold and baseline_lat > 0:
                ratio = lat / max(baseline_lat, 0.0001)
                anomalies.append({
                    "trace_id": row["trace_id"],
                    "agent_name": row["agent_name"],
                    "anomaly_type": "latency_spike",
                    "value": _safe_round(lat, 1),
                    "baseline_avg": _safe_round(baseline_lat, 1),
                    "threshold": _safe_round(lat_threshold, 1),
                    "ratio": _safe_round(ratio, 2),
                    "detail": (
                        f"Latency {lat:.0f}ms is {ratio:.1f}x the historical "
                        f"average of {baseline_lat:.0f}ms"
                    ),
                    "timestamp": row["created_at"],
                })

            if tok > tok_threshold and baseline_tok > 0:
                ratio = tok / max(baseline_tok, 0.0001)
                anomalies.append({
                    "trace_id": row["trace_id"],
                    "agent_name": row["agent_name"],
                    "anomaly_type": "token_spike",
                    "value": int(tok),
                    "baseline_avg": _safe_round(baseline_tok, 0),
                    "threshold": _safe_round(tok_threshold, 0),
                    "ratio": _safe_round(ratio, 2),
                    "detail": (
                        f"Token count {int(tok)} is {ratio:.1f}x the historical "
                        f"average of {int(baseline_tok)}"
                    ),
                    "timestamp": row["created_at"],
                })

        # Also scan proxy events for cost / token anomalies
        proxy_rows = conn.execute(
            """SELECT
                 trace_id,
                 json_extract(payload, '$.source_agent') AS agent_name,
                 CAST(json_extract(payload, '$.cost_usd') AS REAL) AS cost_usd,
                 CAST(json_extract(payload, '$.total_tokens') AS REAL) AS total_tokens,
                 timestamp
               FROM events
               WHERE source = 'proxy'
                 AND timestamp >= ?
               ORDER BY timestamp DESC""",
            (cutoff,),
        ).fetchall()

        for row in proxy_rows:
            cost = row["cost_usd"] or 0.0
            tok = row["total_tokens"] or 0.0
            agent = row["agent_name"] or "unknown"

            if cost > cost_threshold and baseline_cost > 0:
                ratio = cost / max(baseline_cost, 0.0001)
                anomalies.append({
                    "trace_id": row["trace_id"],
                    "agent_name": agent,
                    "anomaly_type": "cost_spike",
                    "value": _safe_round(cost, 4),
                    "baseline_avg": _safe_round(baseline_cost, 4),
                    "threshold": _safe_round(cost_threshold, 4),
                    "ratio": _safe_round(ratio, 2),
                    "detail": (
                        f"Proxy call cost ${cost:.4f} is {ratio:.1f}x the "
                        f"historical average of ${baseline_cost:.4f}"
                    ),
                    "timestamp": row["timestamp"],
                })

            if tok > tok_threshold and baseline_tok > 0:
                ratio = tok / max(baseline_tok, 0.0001)
                anomalies.append({
                    "trace_id": row["trace_id"],
                    "agent_name": agent,
                    "anomaly_type": "token_spike",
                    "value": int(tok),
                    "baseline_avg": _safe_round(baseline_tok, 0),
                    "threshold": _safe_round(tok_threshold, 0),
                    "ratio": _safe_round(ratio, 2),
                    "detail": (
                        f"Proxy call tokens {int(tok)} is {ratio:.1f}x the "
                        f"historical average of {int(baseline_tok)}"
                    ),
                    "timestamp": row["timestamp"],
                })

        # Sort by ratio descending (most anomalous first)
        anomalies.sort(key=lambda a: -a["ratio"])
        return anomalies

    def _detect_anomalies_per_agent(
        self,
        cutoff: str,
        since_days: int,
    ) -> list[dict[str, Any]]:
        """
        Fallback anomaly detection when global baseline is too thin.

        Computes per-agent baselines from all historical data, then
        checks recent executions against each agent's own baseline.
        """
        conn = self._conn()
        anomalies: list[dict[str, Any]] = []

        # Get all agent_ids that have any history
        agents = conn.execute(
            """SELECT DISTINCT
                 COALESCE(agent_id, 'unknown') AS agent_id
               FROM execution_records
               WHERE agent_id IS NOT NULL AND agent_id != ''"""
        ).fetchall()

        for agent_row in agents:
            agent_id = agent_row["agent_id"]

            # Historical baseline for this agent
            hist = conn.execute(
                """SELECT
                     AVG(total_cost_usd)     AS avg_cost,
                     AVG(total_latency_ms)   AS avg_latency,
                     AVG(total_tokens)       AS avg_tokens,
                     COUNT(*)                AS cnt
                   FROM execution_records
                   WHERE agent_id = ?
                     AND created_at < ?""",
                (agent_id, cutoff),
            ).fetchone()

            if (hist["cnt"] or 0) < _MIN_BASELINE_EXECUTIONS:
                continue

            base_c = hist["avg_cost"] or 0.0
            base_l = hist["avg_latency"] or 0.0
            base_t = hist["avg_tokens"] or 0.0

            recent = conn.execute(
                """SELECT
                     trace_id,
                     COALESCE(agent_name, agent_id) AS agent_name,
                     total_cost_usd,
                     total_latency_ms,
                     total_tokens,
                     created_at
                   FROM execution_records
                   WHERE agent_id = ?
                     AND created_at >= ?
                   ORDER BY created_at DESC""",
                (agent_id, cutoff),
            ).fetchall()

            for row in recent:
                cost = row["total_cost_usd"] or 0.0
                lat = row["total_latency_ms"] or 0.0
                tok = row["total_tokens"] or 0.0

                if cost > base_c * _ANOMALY_MULTIPLIER and base_c > 0:
                    ratio = cost / max(base_c, 0.0001)
                    anomalies.append({
                        "trace_id": row["trace_id"],
                        "agent_name": row["agent_name"],
                        "anomaly_type": "cost_spike",
                        "value": _safe_round(cost, 4),
                        "baseline_avg": _safe_round(base_c, 4),
                        "threshold": _safe_round(base_c * _ANOMALY_MULTIPLIER, 4),
                        "ratio": _safe_round(ratio, 2),
                        "detail": (
                            f"[{row['agent_name']}] Cost ${cost:.4f} is "
                            f"{ratio:.1f}x agent historical avg ${base_c:.4f}"
                        ),
                        "timestamp": row["created_at"],
                    })

                if lat > base_l * _ANOMALY_MULTIPLIER and base_l > 0:
                    ratio = lat / max(base_l, 0.0001)
                    anomalies.append({
                        "trace_id": row["trace_id"],
                        "agent_name": row["agent_name"],
                        "anomaly_type": "latency_spike",
                        "value": _safe_round(lat, 1),
                        "baseline_avg": _safe_round(base_l, 1),
                        "threshold": _safe_round(base_l * _ANOMALY_MULTIPLIER, 1),
                        "ratio": _safe_round(ratio, 2),
                        "detail": (
                            f"[{row['agent_name']}] Latency {lat:.0f}ms is "
                            f"{ratio:.1f}x agent historical avg {base_l:.0f}ms"
                        ),
                        "timestamp": row["created_at"],
                    })

                if tok > base_t * _ANOMALY_MULTIPLIER and base_t > 0:
                    ratio = tok / max(base_t, 0.0001)
                    anomalies.append({
                        "trace_id": row["trace_id"],
                        "agent_name": row["agent_name"],
                        "anomaly_type": "token_spike",
                        "value": int(tok),
                        "baseline_avg": _safe_round(base_t, 0),
                        "threshold": _safe_round(base_t * _ANOMALY_MULTIPLIER, 0),
                        "ratio": _safe_round(ratio, 2),
                        "detail": (
                            f"[{row['agent_name']}] Tokens {int(tok)} is "
                            f"{ratio:.1f}x agent historical avg {int(base_t)}"
                        ),
                        "timestamp": row["created_at"],
                    })

        anomalies.sort(key=lambda a: -a["ratio"])
        return anomalies

    # ──────────────────────────────────────────────────────────
    # Aggregate by Model
    # ──────────────────────────────────────────────────────────

    def aggregate_by_model(self, since_days: int = 30) -> list[dict[str, Any]]:
        """
        Roll-up execution stats grouped by model (runtime_id).

        Each entry::

            {
              "model": str,
              "total_executions": int,
              "success_count": int,
              "failure_count": int,
              "success_rate": float,
              "avg_latency_ms": float,
              "total_cost_usd": float,
              "total_tokens": int,
              "unique_agents": int,
            }

        Merges data from both ``execution_records`` (runtime_id) and
        proxy ``events`` (payload.model).
        """
        cutoff = _cutoff_iso(since_days)
        conn = self._conn()

        # ── execution_records by runtime_id ────────────────────
        exec_rows = conn.execute(
            """SELECT
                 runtime_id AS model,
                 COUNT(*)                                AS total_executions,
                 SUM(CASE WHEN status = 'success'  THEN 1 ELSE 0 END) AS success_count,
                 SUM(CASE WHEN status IN ('failure', 'partial')
                          THEN 1 ELSE 0 END)             AS failure_count,
                 AVG(total_latency_ms)                   AS avg_latency_ms,
                 COALESCE(SUM(total_cost_usd), 0)        AS total_cost_usd,
                 COALESCE(SUM(total_tokens), 0)          AS total_tokens,
                 COUNT(DISTINCT agent_id)                AS unique_agents
               FROM execution_records
               WHERE created_at >= ?
                 AND runtime_id IS NOT NULL
                 AND runtime_id != ''
               GROUP BY runtime_id""",
            (cutoff,),
        ).fetchall()

        # ── proxy events by model ─────────────────────────────
        proxy_rows = conn.execute(
            """SELECT
                 json_extract(payload, '$.model')        AS model,
                 COUNT(*)                                AS proxy_calls,
                 COALESCE(SUM(CAST(json_extract(payload, '$.cost_usd') AS REAL)), 0) AS proxy_cost,
                 COALESCE(SUM(CAST(json_extract(payload, '$.total_tokens') AS REAL)), 0) AS proxy_tokens,
                 SUM(CASE WHEN json_extract(payload, '$.status') = 'failure'
                          THEN 1 ELSE 0 END)             AS proxy_failures,
                 COUNT(DISTINCT json_extract(payload, '$.source_agent')) AS proxy_agents
               FROM events
               WHERE source = 'proxy'
                 AND timestamp >= ?
                 AND json_extract(payload, '$.model') IS NOT NULL
                 AND json_extract(payload, '$.model') != ''
               GROUP BY json_extract(payload, '$.model')""",
            (cutoff,),
        ).fetchall()

        # ── Merge ──────────────────────────────────────────────
        proxy_by_model: dict[str, dict[str, Any]] = {
            r["model"]: r for r in proxy_rows if r["model"]
        }

        aggregated: list[dict[str, Any]] = []
        for row in exec_rows:
            model = row["model"]
            pd = proxy_by_model.pop(model, None)
            pc = pd["proxy_calls"] if pd else 0
            p_cost = pd["proxy_cost"] if pd else 0.0
            p_tok = int(pd["proxy_tokens"] or 0) if pd else 0
            p_fail = pd["proxy_failures"] if pd else 0
            p_agents = int(pd["proxy_agents"] or 0) if pd else 0

            total = (row["total_executions"] or 0) + pc
            successes = (row["success_count"] or 0) + (pc - p_fail)
            failures = (row["failure_count"] or 0) + p_fail

            aggregated.append({
                "model": model,
                "total_executions": total,
                "success_count": successes,
                "failure_count": failures,
                "success_rate": _safe_round(successes / max(total, 1), 4),
                "avg_latency_ms": _safe_round(row["avg_latency_ms"], 1),
                "total_cost_usd": _safe_round(
                    (row["total_cost_usd"] or 0) + p_cost, 4
                ),
                "total_tokens": int(row["total_tokens"] or 0) + p_tok,
                "unique_agents": max(
                    row["unique_agents"] or 0, p_agents
                ),
            })

        # Models that only appear in proxy events
        for model, pd in proxy_by_model.items():
            pc = pd["proxy_calls"] or 0
            p_fail = pd["proxy_failures"] or 0
            aggregated.append({
                "model": model,
                "total_executions": pc,
                "success_count": pc - p_fail,
                "failure_count": p_fail,
                "success_rate": _safe_round((pc - p_fail) / max(pc, 1), 4),
                "avg_latency_ms": 0.0,
                "total_cost_usd": _safe_round(pd["proxy_cost"], 4),
                "total_tokens": int(pd["proxy_tokens"] or 0),
                "unique_agents": int(pd["proxy_agents"] or 0),
            })

        aggregated.sort(key=lambda m: -m["total_executions"])
        return aggregated

    # ──────────────────────────────────────────────────────────
    # Aggregate by Agent
    # ──────────────────────────────────────────────────────────

    def aggregate_by_agent(self, since_days: int = 30) -> list[dict[str, Any]]:
        """
        Roll-up execution stats grouped by agent.

        Each entry::

            {
              "agent_id": str,
              "agent_name": str,
              "total_executions": int,
              "success_count": int,
              "failure_count": int,
              "success_rate": float,
              "avg_latency_ms": float,
              "total_cost_usd": float,
              "total_tokens": int,
              "unique_models": int,
              "last_seen": str,
            }

        Merges both ``execution_records`` and proxy ``events``.
        """
        cutoff = _cutoff_iso(since_days)
        conn = self._conn()

        # ── execution_records by agent ────────────────────────
        exec_rows = conn.execute(
            """SELECT
                 COALESCE(agent_id, 'unknown')          AS agent_id,
                 MAX(COALESCE(agent_name, agent_id, 'unknown')) AS agent_name,
                 COUNT(*)                                AS total_executions,
                 SUM(CASE WHEN status = 'success'  THEN 1 ELSE 0 END) AS success_count,
                 SUM(CASE WHEN status IN ('failure', 'partial')
                          THEN 1 ELSE 0 END)             AS failure_count,
                 AVG(total_latency_ms)                   AS avg_latency_ms,
                 COALESCE(SUM(total_cost_usd), 0)        AS total_cost_usd,
                 COALESCE(SUM(total_tokens), 0)          AS total_tokens,
                 COUNT(DISTINCT runtime_id)               AS unique_models,
                 MAX(created_at)                         AS last_seen
               FROM execution_records
               WHERE created_at >= ?
               GROUP BY COALESCE(agent_id, 'unknown')""",
            (cutoff,),
        ).fetchall()

        # ── proxy events by source_agent ──────────────────────
        proxy_rows = conn.execute(
            """SELECT
                 COALESCE(json_extract(payload, '$.source_agent'), 'unknown') AS agent_key,
                 COUNT(*)                                AS proxy_calls,
                 COALESCE(SUM(CAST(json_extract(payload, '$.cost_usd') AS REAL)), 0) AS proxy_cost,
                 COALESCE(SUM(CAST(json_extract(payload, '$.total_tokens') AS REAL)), 0) AS proxy_tokens,
                 SUM(CASE WHEN json_extract(payload, '$.status') = 'failure'
                          THEN 1 ELSE 0 END)             AS proxy_failures,
                 COUNT(DISTINCT json_extract(payload, '$.model')) AS proxy_models,
                 MAX(timestamp)                          AS proxy_last_seen
               FROM events
               WHERE source = 'proxy'
                 AND timestamp >= ?
               GROUP BY COALESCE(json_extract(payload, '$.source_agent'), 'unknown')""",
            (cutoff,),
        ).fetchall()

        # ── Merge ──────────────────────────────────────────────
        proxy_by_agent: dict[str, dict[str, Any]] = {
            r["agent_key"]: r for r in proxy_rows
        }

        aggregated: list[dict[str, Any]] = []
        for row in exec_rows:
            aid = row["agent_id"]
            pd = proxy_by_agent.pop(aid, None)
            pc = pd["proxy_calls"] if pd else 0
            p_cost = pd["proxy_cost"] if pd else 0.0
            p_tok = int(pd["proxy_tokens"] or 0) if pd else 0
            p_fail = pd["proxy_failures"] if pd else 0
            p_models = int(pd["proxy_models"] or 0) if pd else 0
            p_seen = pd["proxy_last_seen"] if pd else None

            total = (row["total_executions"] or 0) + pc
            successes = (row["success_count"] or 0) + (pc - p_fail)
            failures = (row["failure_count"] or 0) + p_fail

            # Latest timestamp across both sources
            last_seen = row["last_seen"]
            if p_seen and (not last_seen or p_seen > last_seen):
                last_seen = p_seen

            aggregated.append({
                "agent_id": aid,
                "agent_name": row["agent_name"] or aid,
                "total_executions": total,
                "success_count": successes,
                "failure_count": failures,
                "success_rate": _safe_round(successes / max(total, 1), 4),
                "avg_latency_ms": _safe_round(row["avg_latency_ms"], 1),
                "total_cost_usd": _safe_round(
                    (row["total_cost_usd"] or 0) + p_cost, 4
                ),
                "total_tokens": int(row["total_tokens"] or 0) + p_tok,
                "unique_models": max(
                    row["unique_models"] or 0, p_models
                ),
                "last_seen": last_seen or None,
            })

        # Agents that only appear in proxy events
        for agent_key, pd in proxy_by_agent.items():
            pc = pd["proxy_calls"] or 0
            p_fail = pd["proxy_failures"] or 0
            aggregated.append({
                "agent_id": agent_key,
                "agent_name": agent_key,
                "total_executions": pc,
                "success_count": pc - p_fail,
                "failure_count": p_fail,
                "success_rate": _safe_round((pc - p_fail) / max(pc, 1), 4),
                "avg_latency_ms": 0.0,
                "total_cost_usd": _safe_round(pd["proxy_cost"], 4),
                "total_tokens": int(pd["proxy_tokens"] or 0),
                "unique_models": int(pd["proxy_models"] or 0),
                "last_seen": pd["proxy_last_seen"],
            })

        aggregated.sort(key=lambda a: -a["total_executions"])
        return aggregated

    # ──────────────────────────────────────────────────────────
    # Convenience: full agent report
    # ──────────────────────────────────────────────────────────

    def agent_full_report(self, agent_id: str, since_days: int = 30) -> dict[str, Any]:
        """
        Single-call convenience that bundles the three most-useful
        views for a dashboard: summary, timeline, and the agent's
        rank among peers.

        Returns::

            {
              "summary": { ... agent_summary ... },
              "timeline": [ ... agent_timeline ... ],
              "rank": int | None,
              "total_agents": int,
            }
        """
        summary = self.agent_summary(agent_id)
        timeline = self.agent_timeline(agent_id, since_days=since_days)

        # Determine rank by total_executions within the agent pool
        all_agents = self.aggregate_by_agent(since_days=since_days)
        total_agents = len(all_agents)
        rank: int | None = None
        for idx, entry in enumerate(all_agents, start=1):
            if entry["agent_id"] == agent_id:
                rank = idx
                break

        return {
            "summary": summary,
            "timeline": timeline,
            "rank": rank,
            "total_agents": total_agents,
        }
