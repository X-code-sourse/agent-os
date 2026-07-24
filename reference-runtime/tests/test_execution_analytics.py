"""
Tests for AgentAnalytics — agent-centric execution analytics engine.

Uses a real :memory: SQLite database behind a mock EventStore to test
the full analytics query path end-to-end.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.execution_analytics import AgentAnalytics


# ── Helpers ──


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ── Fixtures ──


@pytest.fixture
def mock_event_store():
    """Create a mock EventStore with a real :memory: SQLite database
    and pre-created execution_records + events tables."""

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    # Create execution_records table
    conn.execute("""
        CREATE TABLE execution_records (
            trace_id TEXT PRIMARY KEY,
            agent_id TEXT,
            agent_name TEXT,
            context_id TEXT,
            manifest_name TEXT,
            runtime_id TEXT,
            status TEXT,
            total_latency_ms REAL,
            total_cost_usd REAL,
            total_tokens INTEGER,
            error TEXT,
            created_at TEXT
        )
    """)

    # Create events table (for proxy data)
    conn.execute("""
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            trace_id TEXT,
            event_type TEXT,
            task_id TEXT,
            capability TEXT,
            payload TEXT,
            metrics TEXT,
            source TEXT,
            sequence INTEGER,
            timestamp TEXT
        )
    """)

    # Build mock
    mock = MagicMock()
    mock.get_connection.return_value = conn

    return mock, conn


def _insert_execution(conn, **kwargs):
    """Insert a row into execution_records."""
    defaults = {
        "trace_id": "trace_001",
        "agent_id": "agent_abc",
        "agent_name": "Test Agent",
        "context_id": "ctx_001",
        "manifest_name": "test_capability",
        "runtime_id": "openai",
        "status": "success",
        "total_latency_ms": 500.0,
        "total_cost_usd": 0.05,
        "total_tokens": 1000,
        "error": None,
        "created_at": _now_iso(),
    }
    defaults.update(kwargs)
    conn.execute(
        """INSERT OR REPLACE INTO execution_records
           (trace_id, agent_id, agent_name, context_id, manifest_name,
            runtime_id, status, total_latency_ms, total_cost_usd,
            total_tokens, error, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            defaults["trace_id"], defaults["agent_id"], defaults["agent_name"],
            defaults["context_id"], defaults["manifest_name"],
            defaults["runtime_id"], defaults["status"],
            defaults["total_latency_ms"], defaults["total_cost_usd"],
            defaults["total_tokens"], defaults["error"],
            defaults["created_at"],
        ),
    )
    conn.commit()


def _insert_proxy_event(conn, **kwargs):
    """Insert a row into events table simulating a proxy event."""
    import json
    defaults = {
        "event_id": "evt_001",
        "trace_id": "trace_p001",
        "event_type": "TaskCompleted",
        "task_id": "task_001",
        "capability": "test_capability",
        "payload": json.dumps({
            "source_agent": "agent_abc",
            "model": "claude-opus",
            "cost_usd": 0.03,
            "total_tokens": 800,
            "status": "success",
        }),
        "metrics": "{}",
        "source": "proxy",
        "sequence": 1,
        "timestamp": _now_iso(),
    }
    defaults.update(kwargs)
    import json as _json
    conn.execute(
        """INSERT OR REPLACE INTO events
           (event_id, trace_id, event_type, task_id, capability,
            payload, metrics, source, sequence, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            defaults["event_id"], defaults["trace_id"],
            defaults["event_type"], defaults["task_id"],
            defaults["capability"], defaults["payload"],
            defaults["metrics"], defaults["source"],
            defaults["sequence"], defaults["timestamp"],
        ),
    )
    conn.commit()


# ── Tests ──


class TestAgentAnalytics:
    """Tests for AgentAnalytics on mock event store."""

    def test_agent_summary_returns_expected_keys(self, mock_event_store):
        """agent_summary() returns a dict with all expected keys."""
        mock, conn = mock_event_store
        _insert_execution(conn, trace_id="t1", agent_id="agent_abc",
                          status="success", total_latency_ms=400.0,
                          total_cost_usd=0.04, total_tokens=500)

        analytics = AgentAnalytics(mock)
        summary = analytics.agent_summary("agent_abc")

        expected_keys = {
            "agent_id", "success_rate", "avg_latency_ms",
            "total_cost_usd", "total_tokens", "total_executions",
            "failure_count", "top_failure_reasons", "models_used",
            "first_seen", "last_seen",
        }
        assert set(summary.keys()) == expected_keys
        assert summary["agent_id"] == "agent_abc"
        assert summary["total_executions"] == 1
        assert summary["success_rate"] == 1.0
        assert summary["avg_latency_ms"] == 400.0
        assert summary["total_cost_usd"] == 0.04
        assert summary["total_tokens"] == 500
        assert summary["failure_count"] == 0

    def test_agent_summary_with_failures(self, mock_event_store):
        """agent_summary() correctly counts failures and success_rate."""
        mock, conn = mock_event_store
        _insert_execution(conn, trace_id="t1", agent_id="agent_fail",
                          status="success")
        _insert_execution(conn, trace_id="t2", agent_id="agent_fail",
                          status="failure", error="timeout")
        _insert_execution(conn, trace_id="t3", agent_id="agent_fail",
                          status="failure", error="timeout")

        analytics = AgentAnalytics(mock)
        summary = analytics.agent_summary("agent_fail")

        assert summary["total_executions"] == 3
        assert summary["success_rate"] == pytest.approx(1.0 / 3.0, rel=0.01)
        assert summary["failure_count"] == 2
        assert len(summary["top_failure_reasons"]) == 1
        assert summary["top_failure_reasons"][0]["error"] == "timeout"
        assert summary["top_failure_reasons"][0]["count"] == 2

    def test_agent_summary_with_proxy_events(self, mock_event_store):
        """agent_summary() merges data from proxy events table."""
        mock, conn = mock_event_store
        _insert_execution(conn, trace_id="t1", agent_id="agent_proxy",
                          total_cost_usd=0.05, total_tokens=500)
        _insert_proxy_event(conn, event_id="pe1", trace_id="tp1",
                           payload='{"source_agent":"agent_proxy","model":"claude","cost_usd":0.03,"total_tokens":300,"status":"success"}')

        analytics = AgentAnalytics(mock)
        summary = analytics.agent_summary("agent_proxy")

        assert summary["total_executions"] == 2  # 1 exec + 1 proxy
        assert summary["total_cost_usd"] == 0.08  # 0.05 + 0.03
        assert summary["total_tokens"] == 800     # 500 + 300

    def test_agent_timeline_daily_bucketing(self, mock_event_store):
        """agent_timeline() groups executions into daily buckets."""
        mock, conn = mock_event_store
        dt1 = _days_ago_iso(5)
        dt2 = _days_ago_iso(2)
        _insert_execution(conn, trace_id="t1", agent_id="agent_tl",
                          created_at=dt1, total_cost_usd=0.1, total_latency_ms=300)
        _insert_execution(conn, trace_id="t2", agent_id="agent_tl",
                          created_at=dt2, total_cost_usd=0.2, total_latency_ms=700)

        analytics = AgentAnalytics(mock)
        timeline = analytics.agent_timeline("agent_tl", since_days=30)

        assert len(timeline) == 2
        # Each bucket should have expected keys
        for bucket in timeline:
            assert "date" in bucket
            assert "executions" in bucket
            assert "success" in bucket
            assert "failure" in bucket
            assert "cost_usd" in bucket
            assert "avg_latency_ms" in bucket
            assert "tokens" in bucket

        # Dates should be sorted ascending
        assert timeline[0]["date"] <= timeline[1]["date"]

    def test_agent_compare_delta_computation(self, mock_event_store):
        """agent_compare() computes deltas and picks a winner."""
        mock, conn = mock_event_store
        # Agent A: high success, low latency, low cost
        _insert_execution(conn, trace_id="ta1", agent_id="agent_win",
                          status="success", total_latency_ms=100,
                          total_cost_usd=0.01, total_tokens=200)
        _insert_execution(conn, trace_id="ta2", agent_id="agent_win",
                          status="success", total_latency_ms=150,
                          total_cost_usd=0.02, total_tokens=300)
        # Agent B: low success, high latency, high cost
        _insert_execution(conn, trace_id="tb1", agent_id="agent_lose",
                          status="failure", total_latency_ms=800,
                          total_cost_usd=0.10, total_tokens=1000)
        _insert_execution(conn, trace_id="tb2", agent_id="agent_lose",
                          status="success", total_latency_ms=600,
                          total_cost_usd=0.08, total_tokens=900)

        analytics = AgentAnalytics(mock)
        comparison = analytics.agent_compare("agent_win", "agent_lose")

        assert "agent_a" in comparison
        assert "agent_b" in comparison
        assert "delta" in comparison
        delta = comparison["delta"]
        assert "success_rate_diff" in delta
        assert "avg_latency_ratio" in delta
        assert "cost_diff_usd" in delta
        assert "winner" in delta
        assert delta["winner"] in ("agent_a", "agent_b", "tie")
        # agent_win should win: better success rate, lower latency, lower cost
        assert delta["winner"] == "agent_a"

    def test_agent_compare_tie(self, mock_event_store):
        """agent_compare() returns 'tie' when agents have identical metrics."""
        mock, conn = mock_event_store
        _insert_execution(conn, trace_id="tt1", agent_id="agent_tie1",
                          status="success", total_latency_ms=300,
                          total_cost_usd=0.05)
        _insert_execution(conn, trace_id="tt2", agent_id="agent_tie2",
                          status="success", total_latency_ms=300,
                          total_cost_usd=0.05)

        analytics = AgentAnalytics(mock)
        comparison = analytics.agent_compare("agent_tie1", "agent_tie2")
        assert comparison["delta"]["winner"] == "tie"

    def test_detect_anomalies_flags_outliers(self, mock_event_store):
        """detect_anomalies() flags executions exceeding 3x the historical baseline."""
        mock, conn = mock_event_store

        # Sufficient historical baseline (older than 7 days)
        for i in range(5):
            _insert_execution(
                conn,
                trace_id=f"hist_{i}",
                agent_id="agent_ano",
                total_cost_usd=0.05,
                total_latency_ms=300.0,
                total_tokens=500,
                created_at=_days_ago_iso(30),  # old enough
            )

        # Recent execution with cost spike (0.20 > 3 * 0.05 = 0.15)
        _insert_execution(
            conn,
            trace_id="spike_001",
            agent_id="agent_ano",
            total_cost_usd=0.20,
            total_latency_ms=2000.0,
            total_tokens=3000,
            created_at=_days_ago_iso(3),  # recent
        )

        analytics = AgentAnalytics(mock)
        anomalies = analytics.detect_anomalies(since_days=7)

        assert len(anomalies) > 0
        # At least a cost spike should be detected
        assert any(a["anomaly_type"] == "cost_spike" for a in anomalies)
        assert any(a["anomaly_type"] == "latency_spike" for a in anomalies)
        assert any(a["anomaly_type"] == "token_spike" for a in anomalies)

        # Verify anomaly structure
        for a in anomalies:
            assert "trace_id" in a
            assert "agent_name" in a
            assert "anomaly_type" in a
            assert "value" in a
            assert "baseline_avg" in a
            assert "threshold" in a
            assert "ratio" in a
            assert "detail" in a
            assert "timestamp" in a

    def test_detect_anomalies_insufficient_baseline(self, mock_event_store):
        """detect_anomalies() falls back to per-agent baseline when global is thin."""
        mock, conn = mock_event_store

        # Insufficient global baseline (< 5 old records)
        _insert_execution(conn, trace_id="old_1", agent_id="agent_pa",
                          total_cost_usd=0.05, created_at=_days_ago_iso(30))

        # But the agent itself has 5+ records historically
        for i in range(6):
            _insert_execution(conn, trace_id=f"pa_hist_{i}", agent_id="agent_pa",
                              total_cost_usd=0.03, created_at=_days_ago_iso(30))

        # Recent spike
        _insert_execution(conn, trace_id="pa_spike", agent_id="agent_pa",
                          total_cost_usd=1.0, created_at=_days_ago_iso(1))

        analytics = AgentAnalytics(mock)
        anomalies = analytics.detect_anomalies(since_days=7)

        # Should still detect the spike via per-agent fallback
        assert len(anomalies) > 0

    def test_aggregate_by_model_groups_correctly(self, mock_event_store):
        """aggregate_by_model() groups executions by runtime_id."""
        mock, conn = mock_event_store
        _insert_execution(conn, trace_id="m1", runtime_id="openai",
                          total_cost_usd=0.05, total_tokens=500,
                          total_latency_ms=300, status="success")
        _insert_execution(conn, trace_id="m2", runtime_id="openai",
                          total_cost_usd=0.07, total_tokens=600,
                          total_latency_ms=400, status="success")
        _insert_execution(conn, trace_id="m3", runtime_id="claude",
                          total_cost_usd=0.10, total_tokens=400,
                          total_latency_ms=200, status="success")

        analytics = AgentAnalytics(mock)
        models = analytics.aggregate_by_model(since_days=30)

        assert len(models) >= 2
        by_name = {m["model"]: m for m in models}
        assert "openai" in by_name
        assert "claude" in by_name
        assert by_name["openai"]["total_executions"] == 2
        assert by_name["claude"]["total_executions"] == 1

        for m in models:
            assert "model" in m
            assert "total_executions" in m
            assert "success_count" in m
            assert "failure_count" in m
            assert "success_rate" in m
            assert "avg_latency_ms" in m
            assert "total_cost_usd" in m
            assert "total_tokens" in m
            assert "unique_agents" in m

    def test_aggregate_by_agent_groups_correctly(self, mock_event_store):
        """aggregate_by_agent() groups executions by agent."""
        mock, conn = mock_event_store
        _insert_execution(conn, trace_id="a1", agent_id="agent_agg_a",
                          agent_name="Agent A", runtime_id="openai",
                          total_cost_usd=0.05, total_latency_ms=300)
        _insert_execution(conn, trace_id="a2", agent_id="agent_agg_a",
                          agent_name="Agent A", runtime_id="claude",
                          total_cost_usd=0.10, total_latency_ms=200)
        _insert_execution(conn, trace_id="a3", agent_id="agent_agg_b",
                          agent_name="Agent B", runtime_id="openai",
                          total_cost_usd=0.03, total_latency_ms=500)

        analytics = AgentAnalytics(mock)
        agents = analytics.aggregate_by_agent(since_days=30)

        assert len(agents) >= 2
        by_id = {a["agent_id"]: a for a in agents}
        assert "agent_agg_a" in by_id
        assert "agent_agg_b" in by_id
        assert by_id["agent_agg_a"]["total_executions"] == 2
        assert by_id["agent_agg_b"]["total_executions"] == 1
        assert by_id["agent_agg_a"]["unique_models"] >= 1

        for a in agents:
            assert "agent_id" in a
            assert "agent_name" in a
            assert "total_executions" in a
            assert "success_count" in a
            assert "failure_count" in a
            assert "success_rate" in a
            assert "avg_latency_ms" in a
            assert "total_cost_usd" in a
            assert "total_tokens" in a
            assert "unique_models" in a
            assert "last_seen" in a

    def test_empty_data_handled_gracefully(self, mock_event_store):
        """All analytics methods return sensible results when the store is empty."""
        mock, conn = mock_event_store
        analytics = AgentAnalytics(mock)

        # summary
        summary = analytics.agent_summary("nonexistent_agent")
        assert summary["total_executions"] == 0
        assert summary["success_rate"] == 0.0
        assert summary["total_cost_usd"] == 0.0
        assert summary["total_tokens"] == 0
        assert summary["failure_count"] == 0
        assert summary["top_failure_reasons"] == []
        assert summary["models_used"] == []

        # timeline
        timeline = analytics.agent_timeline("nonexistent_agent")
        assert timeline == []

        # anomalies
        anomalies = analytics.detect_anomalies(since_days=7)
        assert anomalies == []

        # aggregate by model
        models = analytics.aggregate_by_model(since_days=30)
        assert models == []

        # aggregate by agent
        agents = analytics.aggregate_by_agent(since_days=30)
        assert agents == []

    def test_agent_full_report(self, mock_event_store):
        """agent_full_report() bundles summary, timeline, and rank."""
        mock, conn = mock_event_store
        _insert_execution(conn, trace_id="fr1", agent_id="agent_fr",
                          total_cost_usd=0.05, status="success")

        analytics = AgentAnalytics(mock)
        report = analytics.agent_full_report("agent_fr", since_days=30)

        assert "summary" in report
        assert "timeline" in report
        assert "rank" in report
        assert "total_agents" in report
        assert report["summary"]["agent_id"] == "agent_fr"
        assert report["total_agents"] >= 1
