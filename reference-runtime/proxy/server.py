"""Intent OS — Agent Hook Proxy Server.

A lightweight HTTP proxy that intercepts OpenAI and Anthropic API calls
from AI coding agents (Claude Code, Cursor, Copilot, etc.) and records
every call to the Intent OS Event Store.

Usage:
    from proxy.server import start_proxy
    start_proxy(port=8377)
"""
from __future__ import annotations

import http.client
import json
import os
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import urlparse

from proxy.tracer import AgentTracer, detect_agent
from proxy.guard import ToolCallGuard


# ── Upstream API URLs ──

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# ── Streaming byte → token estimator (rough: ~3.5 chars per token) ──

_BYTES_PER_TOKEN = 3.5


def _estimate_tokens_from_bytes(byte_count: int) -> int:
    """Rough token estimate from raw byte count (for streaming responses)."""
    return max(1, int(byte_count / _BYTES_PER_TOKEN))


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


def _is_streaming_request(body: dict[str, Any]) -> bool:
    """Return True when the request body asks for SSE streaming."""
    return bool(body.get("stream", False))


def _forward_stream_setup(
    url: str,
    body: bytes,
    api_key: str,
    content_type: str,
    timeout: int = 300,
) -> tuple[int, dict[str, str], http.client.HTTPSConnection, http.client.HTTPResponse]:
    """Open a streaming connection to the upstream API.

    Returns ``(status, headers, conn, response)`` — the **caller** is
    responsible for forwarding the status + headers to the client, then
    reading chunks from *response* and writing them to the client socket.
    """
    parsed = urlparse(url)
    port = 443 if parsed.port is None else parsed.port

    conn = http.client.HTTPSConnection(parsed.netloc, port, timeout=timeout)

    req_headers: dict[str, str] = {"Content-Type": content_type}
    if "anthropic" in url:
        req_headers["x-api-key"] = api_key
    else:
        req_headers["Authorization"] = f"Bearer {api_key}"

    conn.request("POST", parsed.path or "/", body=body, headers=req_headers)
    resp = conn.getresponse()
    resp_headers: dict[str, str] = dict(resp.getheaders())
    return resp.status, resp_headers, conn, resp


class ProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler that proxies LLM API calls and records them."""

    # Class-level tracer, guard, agent_id, and context_id shared across all requests
    _tracer: AgentTracer | None = None
    _guard: ToolCallGuard | None = None
    _agent_id: str | None = None
    _context_id: str | None = None

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

    @classmethod
    def set_agent_id(cls, agent_id: str | None) -> None:
        """Set the agent ID to associate with all captured traces."""
        cls._agent_id = agent_id

    @classmethod
    def set_context_id(cls, context_id: str | None) -> None:
        """Set the execution context ID to associate with all captured traces."""
        cls._context_id = context_id

    def do_POST(self) -> None:
        """Handle POST requests — proxy to OpenAI or Anthropic."""
        start_time = time.monotonic()
        path = self.path.rstrip("/")

        # Read request body — parse Content-Length defensively
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_error(400, "Invalid Content-Length header")
            return

        # Reject oversized request bodies (50 MB limit)
        MAX_BODY_SIZE = 50 * 1024 * 1024  # 50 MB
        if content_length > MAX_BODY_SIZE:
            self._send_error(413, "Request body too large (max 50 MB)")
            return

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

        # ── Phase C: Inject agent context into the LLM request ──
        if self._agent_id and request_body:
            try:
                from core.context_injector import build_injection_prompt
                prompt = build_injection_prompt(self._agent_id)
                if prompt:
                    if provider == "openai":
                        msgs = request_body.get("messages", [])
                        msgs.insert(0, {"role": "system", "content": prompt})
                        request_body["messages"] = msgs
                    elif provider == "anthropic":
                        existing = request_body.get("system", "")
                        new_system = f"{existing}\n\n{prompt}" if existing else prompt
                        request_body["system"] = new_system
                    body = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
            except Exception:
                pass  # Injection failure never blocks the request
        # ═══════════════════════════════════════════════════════

        model = _get_model_from_request(request_body)
        agent = detect_agent(dict(self.headers))

        # ── Streaming path: forward chunks in real-time ──
        if _is_streaming_request(request_body):
            status_code, resp_headers, upstream_conn, upstream_resp = _forward_stream_setup(
                upstream, body, api_key, content_type
            )

            # Forward HTTP status + headers to the client
            self.send_response(status_code)
            for key, value in resp_headers.items():
                key_lower = key.lower()
                if key_lower in ("transfer-encoding", "connection", "content-length"):
                    continue
                self.send_header(key, value)
            self.send_header("X-Intent-OS-Proxy", "true")
            self.end_headers()

            # Stream body chunks from upstream → client
            total_bytes = 0
            while True:
                chunk = upstream_resp.read(8192)
                if not chunk:
                    break
                total_bytes += len(chunk)
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
            upstream_conn.close()

            elapsed_ms = (time.monotonic() - start_time) * 1000

            # Estimate tokens from byte count (streaming gives us no usage object)
            estimated_tokens = _estimate_tokens_from_bytes(total_bytes)
            input_tokens = estimated_tokens // 3
            output_tokens = estimated_tokens - input_tokens

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
                agent_id=self._agent_id,
                context_id=self._context_id,
            )
            return

        # ── Non-streaming path: buffer full response ──
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
            agent_id=self._agent_id,
            context_id=self._context_id,
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


def start_proxy(port: int = 8377, host: str = "127.0.0.1", use_guard: bool = False, agent_id: str | None = None, context_id: str | None = None) -> ThreadedProxyServer:
    """Start the agent hook proxy server.

    Args:
        port: Port to listen on (default 8377).
        host: Host to bind to (default 127.0.0.1).
        use_guard: Enable optional Tool Call Guard.
        agent_id: Registered agent ID for execution tracking.
        context_id: Execution context ID to associate with captured traces.

    Returns:
        The HTTP server instance (call .serve_forever() to run).
    """
    if use_guard:
        ProxyHandler.enable_guard()
        print("  [GUARD] Tool Call Guard enabled — inspecting tool call safety.")
        print()
    if agent_id:
        ProxyHandler.set_agent_id(agent_id)
    if context_id:
        ProxyHandler.set_context_id(context_id)
    server = ThreadedProxyServer((host, port), ProxyHandler)
    # Onboarding instructions are printed by commands/proxy.py
    return server
