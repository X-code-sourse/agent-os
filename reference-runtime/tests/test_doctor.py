"""Tests for intent-os doctor command."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from commands.doctor import cmd_doctor, _get_agent_status, _summarize_failure
from core.models import EventType


def make_record(status: str = "success", **kw: Any) -> dict[str, Any]:
    """Build a fake execution record dict."""
    return {
        "manifest_name": "test_capability",
        "manifest_version": "1.0.0",
        "runtime_id": "ollama",
        "adapter": "OllamaAdapter",
        "total_latency_ms": 5432,
        "total_cost_usd": 0.0123,
        "total_tokens": 1500,
        "status": status,
        "error": None,
        **kw,
    }


def make_event(event_type: str, **kw: Any) -> dict[str, Any]:
    """Build a fake event dict."""
    return {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "runtime",
        "capability": "test_capability",
        "payload": "{}",
        **kw,
    }


class TestGetAgentStatus:
    """_get_agent_status() classifies execution records."""

    def test_success(self) -> None:
        assert _get_agent_status(make_record("success")) == "healthy"

    def test_failure(self) -> None:
        assert _get_agent_status(make_record("failure")) == "failed"

    def test_partial(self) -> None:
        assert _get_agent_status(make_record("partial")) == "partial"

    def test_none(self) -> None:
        assert _get_agent_status(None) == "unknown"

    def test_unknown_status(self) -> None:
        assert _get_agent_status(make_record("unknown")) == "unknown"


class TestSummarizeFailure:
    """_summarize_failure() analyzes failure events."""

    def test_no_events(self) -> None:
        result = _summarize_failure([], make_record("failure"))
        assert result["error_message"] is None
        assert result["failed_events"] == []

    def test_detects_failed_event(self) -> None:
        events = [make_event("TaskFailed", capability="read_file")]
        result = _summarize_failure(events, make_record("failure"))
        assert "read_file" in result["failed_events"][0]
        assert result["failed_at"] == "read_file"

    def test_error_in_payload(self) -> None:
        events = [make_event("TaskFailed", payload=json.dumps({"error_message": "timeout"}))]
        result = _summarize_failure(events, make_record("failure"))
        assert "timeout" in result["error_message"]

    def test_timeout_suggestion(self) -> None:
        result = _summarize_failure([], make_record("failure", error="Operation timed out"))
        assert "timeout" in result["suggestion"].lower()

    def test_rate_limit_suggestion(self) -> None:
        result = _summarize_failure([], make_record("failure", error="429 Too Many Requests"))
        assert "rate" in result["suggestion"].lower()

    def test_auth_suggestion(self) -> None:
        result = _summarize_failure([], make_record("failure", error="Authentication failed"))
        assert "api key" in result["suggestion"].lower()


class TestDoctorOutput:
    """cmd_doctor() produces correct output for each state."""

    def _run_doctor(self, store: Any, trace_id: str) -> str:
        """Run cmd_doctor and capture stdout."""
        import io
        import sys
        from types import SimpleNamespace

        with patch("commands.doctor.get_event_store", return_value=store):
            stdout = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = stdout
            try:
                cmd_doctor(SimpleNamespace())
            finally:
                sys.stdout = old_stdout
            return stdout.getvalue()

    def test_no_traces(self) -> None:
        """No traces should guide user to demo or proxy."""
        store = MagicMock()
        store.get_all_trace_ids.return_value = []
        output = self._run_doctor(store, "")
        assert "No agent executions found" in output
        assert "intent-os demo" in output
        assert "intent-os proxy" in output

    def test_healthy_output(self) -> None:
        """Healthy execution should show summary."""
        store = MagicMock()
        store.get_all_trace_ids.return_value = ["trace-1"]
        store.get_record.return_value = make_record("success")
        store.get_events_by_trace.return_value = [make_event("TaskCompleted")]
        output = self._run_doctor(store, "trace-1")
        assert "Healthy" in output
        assert "test_capability" in output
        assert "intent-os inspect" in output

    def test_failed_output(self) -> None:
        """Failed execution should show error and suggestion."""
        store = MagicMock()
        store.get_all_trace_ids.return_value = ["trace-1"]
        store.get_record.return_value = make_record("failure", error="Connection refused")
        store.get_events_by_trace.return_value = [make_event("TaskFailed")]
        output = self._run_doctor(store, "trace-1")
        assert "Failed" in output
        assert "Connection refused" in output
        assert "Suggestion" in output
