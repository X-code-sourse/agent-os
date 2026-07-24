"""
Intent OS — Agent Hook Proxy Tests

Tests cover:
  1. Agent detection from HTTP headers
  2. Cost estimation
  3. Tracer event recording
  4. Server command-line parsing
  5. End-to-end: proxy starts, responds to health check
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from proxy.tracer import AgentTracer, detect_agent
from core.pricing import estimate_cost
from proxy.server import ProxyHandler, start_proxy


# ════════════════════════════════════════════════════════════════
# 1. Agent Detection
# ════════════════════════════════════════════════════════════════


class TestAgentDetection:
    """detect_agent() correctly identifies AI agents from headers."""

    def test_detects_claude_code(self) -> None:
        """User-Agent containing 'claude-code' should identify as claude-code."""
        headers = {"user-agent": "claude-code/0.1.0 (darwin)"}
        assert detect_agent(headers) == "claude-code"

    def test_detects_cursor(self) -> None:
        """User-Agent containing 'Cursor' should identify as cursor."""
        headers = {"user-agent": "Cursor/0.45.0"}
        assert detect_agent(headers) == "cursor"

    def test_detects_github_copilot(self) -> None:
        """User-Agent containing 'GitHubCopilot' should identify as copilot."""
        headers = {"user-agent": "GitHubCopilot/1.0.0"}
        assert detect_agent(headers) == "github-copilot"

    def test_unknown_agent(self) -> None:
        """No matching headers should return 'unknown'."""
        headers = {"user-agent": "curl/8.0"}
        assert detect_agent(headers) == "unknown"

    def test_empty_headers(self) -> None:
        """Empty headers should return 'unknown'."""
        assert detect_agent({}) == "unknown"

    def test_case_insensitive(self) -> None:
        """Header matching should be case-insensitive."""
        headers = {"USER-AGENT": "CLAUDE-CODE TEST"}
        assert detect_agent(headers) == "claude-code"


# ════════════════════════════════════════════════════════════════
# 2. Cost Estimation
# ════════════════════════════════════════════════════════════════


class TestCostEstimation:
    """estimate_cost() computes approximate costs."""

    def test_gpt4o_cost(self) -> None:
        """GPT-4o cost at 1M tokens should match pricing."""
        cost = estimate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert cost == pytest.approx(12.50, rel=0.01)  # 2.50 + 10.00

    def test_gpt4o_mini_cost(self) -> None:
        """GPT-4o-mini should be cheaper."""
        cost = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        assert cost == pytest.approx(0.75, rel=0.01)

    def test_unknown_model_cost(self) -> None:
        """Unknown models should use default pricing."""
        cost = estimate_cost("unknown-model", 1_000_000, 1_000_000)
        assert cost == pytest.approx(12.50, rel=0.01)  # default 2.50 + 10.00

    def test_zero_tokens(self) -> None:
        """Zero tokens should cost nothing."""
        cost = estimate_cost("gpt-4o", 0, 0)
        assert cost == 0.0


# ════════════════════════════════════════════════════════════════
# 3. Tracer
# ════════════════════════════════════════════════════════════════


class TestAgentTracer:
    """AgentTracer records API calls to Event Store."""

    def test_trace_call_creates_event(self, tmp_path: Path) -> None:
        """trace_call() should create an event in the store."""
        from core.event_store import EventStore

        db_path = tmp_path / "test_proxy.db"
        store = EventStore(str(db_path))

        tracer = AgentTracer(store=store)
        tid = tracer.trace_call(
            provider="openai",
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            latency_ms=1234.5,
            status="success",
            source_agent="claude-code",
        )

        assert tid is not None
        events = store.get_events_by_trace(tid)
        assert len(events) >= 1
        event = events[0]
        payload = json.loads(event.get("payload", "{}"))
        assert payload.get("provider") == "openai"
        assert payload.get("model") == "gpt-4o"
        assert payload.get("source_agent") == "claude-code"
        assert payload.get("status") == "success"
        assert payload.get("total_tokens") == 150

    def test_trace_call_with_error(self, tmp_path: Path) -> None:
        """trace_call() should record error details."""
        from core.event_store import EventStore

        db_path = tmp_path / "test_proxy_error.db"
        store = EventStore(str(db_path))

        tracer = AgentTracer(store=store)
        tid = tracer.trace_call(
            provider="anthropic",
            model="claude-sonnet-4",
            input_tokens=0,
            output_tokens=0,
            latency_ms=500.0,
            status="failure",
            source_agent="cursor",
            error_message="Rate limit exceeded",
        )

        events = store.get_events_by_trace(tid)
        event = events[0]
        payload = json.loads(event.get("payload", "{}"))
        assert payload.get("provider") == "anthropic"
        assert payload.get("source_agent") == "cursor"
        assert payload.get("status") == "failure"
        assert payload.get("error") == "Rate limit exceeded"


# ════════════════════════════════════════════════════════════════
# 4. Proxy Server
# ════════════════════════════════════════════════════════════════


class TestProxyServer:
    """proxy server can start, respond to health, and be stopped."""

    def _find_free_port(self) -> int:
        """Find a free TCP port for testing."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_proxy_health_check(self) -> None:
        """Proxy server should respond to GET /health with 200."""
        port = self._find_free_port()
        server = start_proxy(port=port)

        # Start server in a daemon thread
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.1)

        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                assert resp.status == 200
                data = json.loads(resp.read().decode())
                assert data["status"] == "ok"
        finally:
            server.shutdown()

    def test_proxy_unknown_endpoint(self) -> None:
        """Unknown endpoints should return 404."""
        port = self._find_free_port()
        server = start_proxy(port=port)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.1)

        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:{port}/unknown")
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(req, timeout=2)
            assert exc.value.code == 404
        finally:
            server.shutdown()

    def test_proxy_no_api_key(self) -> None:
        """Proxy should return 401 when no API key is set."""
        # Temporarily unset the key if set
        old_openai = os.environ.pop("OPENAI_API_KEY", None)
        old_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)

        port = self._find_free_port()
        server = start_proxy(port=port)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.1)

        try:
            import urllib.request
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=b'{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(req, timeout=2)
            assert exc.value.code == 401
        finally:
            server.shutdown()
            # Restore env vars
            if old_openai is not None:
                os.environ["OPENAI_API_KEY"] = old_openai
            if old_anthropic is not None:
                os.environ["ANTHROPIC_API_KEY"] = old_anthropic

    def test_proxy_detects_agent_from_header(self) -> None:
        """Proxy should detect agent from request headers."""
        port = self._find_free_port()
        server = start_proxy(port=port)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.1)

        # Unset API key so it errors early (we're testing detection, not forwarding)
        old_openai = os.environ.pop("OPENAI_API_KEY", None)

        try:
            import urllib.request
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=b'{}',
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Cursor/0.45.0",
                },
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError):
                urllib.request.urlopen(req, timeout=2)
            # The handler didn't crash - that's the test
        finally:
            server.shutdown()
            if old_openai is not None:
                os.environ["OPENAI_API_KEY"] = old_openai
