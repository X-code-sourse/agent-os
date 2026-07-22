"""Intent OS — Agent Hook Proxy Server.

A lightweight HTTP proxy that intercepts OpenAI and Anthropic API calls
from AI coding agents (Claude Code, Cursor, Copilot, etc.) and records
every call to the Intent OS Event Store.

Usage:
    from proxy.server import start_proxy
    start_proxy(port=8377)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Any

from proxy.tracer import AgentTracer, detect_agent
from proxy.guard import ToolCallGuard


# ── Upstream API URLs ──

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


def _get_api_key(provider: str) -> str | None:
    """Read the API key for a provider from environment variables."""
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY")
    elif provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY")
    return None


def _forward_request(
    url: str,
    body: bytes,
    api_key: str,
    content_type: str,
    timeout: int = 300,
) -> tuple[int, dict[str, list[str]], bytes]:
    """Forward a request to the real API and return (status, headers, body)."""
    headers = {
        "Content-Type": content_type,
        "Authorization": f"Bearer {api_key}",
    }
    # Anthropic uses x-api-key header
    if "anthropic" in url:
        headers["x-api-key"] = api_key
        headers.pop("Authorization", None)

    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read()
            resp_headers = dict(resp.headers.items())
            return resp.status, resp_headers, resp_body
    except urllib.error.HTTPError as exc:
        error_body = exc.read()
        return exc.code, dict(exc.headers.items()), error_body


def _extract_openai_usage(response_body: dict[str, Any]) -> dict[str, int]:
    """Extract token usage from an OpenAI response."""
    usage = response_body.get("usage", {})
    if isinstance(usage, dict):
        return {
            "input": usage.get("prompt_tokens", 0),
            "output": usage.get("completion_tokens", 0),
        }
    return {"input": 0, "output": 0}


def _extract_anthropic_usage(response_body: dict[str, Any]) -> dict[str, int]:
    """Extract token usage from an Anthropic response."""
    usage = response_body.get("usage", {})
    if isinstance(usage, dict):
        return {
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
        }
    return {"input": 0, "output": 0}


def _get_model_from_request(body: dict[str, Any]) -> str:
    """Extract the model name from the request body."""
    return str(body.get("model", body.get("model_name", "unknown")))


class ProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler that proxies LLM API calls and records them."""

    # Class-level tracer and guard shared across all requests (lazy init)
    _tracer: AgentTracer | None = None
    _guard: ToolCallGuard | None = None

    @classmethod
    def _get_tracer(cls) -> AgentTracer:
        if cls._tracer is None:
            cls._tracer = AgentTracer()
        return cls._tracer

    @classmethod
    def _get_guard(cls) -> ToolCallGuard | None:
        return cls._guard

    @classmethod
    def enable_guard(cls) -> None:
        """Enable the Tool Call Guard for this handler."""
        if cls._guard is None:
            cls._guard = ToolCallGuard()

    def do_POST(self) -> None:
        """Handle POST requests — proxy to OpenAI or Anthropic."""
        start_time = time.monotonic()
        path = self.path.rstrip("/")

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        content_type = self.headers.get("Content-Type", "application/json")

        # Determine which provider to forward to
        provider = None
        if path == "/v1/chat/completions" or path == "/openai/v1/chat/completions":
            provider = "openai"
            upstream = OPENAI_API_URL
        elif path == "/v1/messages" or path == "/anthropic/v1/messages":
            provider = "anthropic"
            upstream = ANTHROPIC_API_URL
        else:
            self._send_error(404, f"Unknown endpoint: {path}")
            return

        api_key = _get_api_key(provider)
        if not api_key:
            self._send_error(
                401,
                f"No API key found for {provider}. "
                f"Set the {provider.upper()}_API_KEY environment variable.",
            )
            return

        # Parse request body for model info and agent detection
        request_body: dict[str, Any] = {}
        try:
            request_body = json.loads(body) if body else {}
        except json.JSONDecodeError:
            pass

        model = _get_model_from_request(request_body)
        agent = detect_agent(dict(self.headers))

        # Forward the request to the real API
        status_code, resp_headers, resp_body = _forward_request(
            upstream, body, api_key, content_type
        )
        elapsed_ms = (time.monotonic() - start_time) * 1000

        # Parse response for token usage
        response_body: dict[str, Any] = {}
        input_tokens = 0
        output_tokens = 0
        error_message = None

        try:
            response_body = json.loads(resp_body) if resp_body else {}
            if provider == "openai":
                usage = _extract_openai_usage(response_body)
            else:
                usage = _extract_anthropic_usage(response_body)
            input_tokens = usage["input"]
            output_tokens = usage["output"]
        except (json.JSONDecodeError, KeyError):
            pass

        if status_code >= 400:
            error_detail = response_body.get("error", {}).get("message", str(resp_body[:200]))
            error_message = str(error_detail)

        # Record the call
        status = "success" if status_code < 400 else "failure"
        tracer = self._get_tracer()
        tracer.trace_call(
            provider=provider or "unknown",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
            status=status,
            source_agent=agent,
            endpoint=path,
            error_message=error_message,
        )

        # Optional: Tool Call Guard inspection
        guard = self._get_guard()
        if guard is not None and status_code < 400 and response_body:
            try:
                if provider == "openai":
                    results = guard.inspect_openai_response(response_body, tracer.trace_id)
                else:
                    results = guard.inspect_anthropic_response(response_body, tracer.trace_id)
                for r in results:
                    if r.get("decision") in ("deny", "require_review"):
                        print(f"  [GUARD] {r['decision']}: tool={r['tool']} risk={r['risk']} rationale={r['rationale']}")
                    if r.get("sensitive_data_found"):
                        for sf in r["sensitive_data_found"]:
                            print(f"  [GUARD] Sensitive data: {sf['type']}")
            except Exception:
                pass  # Guard is optional — never block the response due to guard errors

        # Return the response to the client
        self.send_response(status_code)
        # Forward response headers
        for key, value in resp_headers.items():
            key_lower = key.lower()
            # Skip transfer-encoding and connection headers that might confuse the client
            if key_lower in ("transfer-encoding", "connection", "content-length"):
                continue
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(resp_body)))
        self.send_header("X-Intent-OS-Proxy", "true")
        self.end_headers()
        self.wfile.write(resp_body)

    def do_GET(self) -> None:
        """Handle health check."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        else:
            self._send_error(404, f"Unknown endpoint: {self.path}")

    def _send_error(self, code: int, message: str) -> None:
        """Send an error response."""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        body = json.dumps({"error": {"message": message}}).encode()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP server logs — we record everything via tracer."""
        pass


class ThreadedProxyServer(ThreadingMixIn, HTTPServer):
    """HTTP server that handles each request in a separate thread."""
    allow_reuse_address = True
    daemon_threads = True


def start_proxy(port: int = 8377, host: str = "127.0.0.1", use_guard: bool = False) -> ThreadedProxyServer:
    """Start the agent hook proxy server.

    Args:
        port: Port to listen on (default 8377).
        host: Host to bind to (default 127.0.0.1).
        use_guard: Enable optional Tool Call Guard.

    Returns:
        The HTTP server instance (call .serve_forever() to run).
    """
    if use_guard:
        ProxyHandler.enable_guard()
        print("  [GUARD] Tool Call Guard enabled — inspecting tool call safety.")
        print()
    server = ThreadedProxyServer((host, port), ProxyHandler)
    # Onboarding instructions are printed by commands/proxy.py
    return server
