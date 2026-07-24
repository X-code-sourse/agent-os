"""
Intent OS — MCP Server (Model Context Protocol)

Exposes registered Intent OS capabilities as MCP tools that any MCP-compatible
client (Claude Desktop, etc.) can discover and invoke.

Protocol: JSON-RPC 2.0 over SSE (Server-Sent Events)
Endpoints:
  GET  /sse       — SSE event stream (MCP transport)
  POST /messages  — JSON-RPC message input (MCP transport)

MCP Methods:
  tools/list      — Returns all registered Capability Manifests as MCP tools
  tools/call      — Invokes a capability via the Intent OS Executor

This implements the complementary relationship between Intent OS and MCP:
  MCP standardizes Connection (AI ↔ Tool)
  Intent OS standardizes Execution (Capability → Workflow → Event)
  Intent OS Runtime can consume MCP servers as Capability Providers
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from core.executor import Executor
from core.models import ExecutionStatus
from core.parser import parse_manifest
from core.registry import CapabilityRegistry

logger = logging.getLogger("intent-os.mcp")


# ──────────────────────────────────────────────
# JSON-RPC helpers
# ──────────────────────────────────────────────

def jsonrpc_error(code: int, message: str, id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def jsonrpc_result(result: Any, id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id, "result": result}


# ──────────────────────────────────────────────
# Manifest → MCP Tool conversion
# ──────────────────────────────────────────────

def _manifest_to_mcp_tool(manifest: Any) -> dict[str, Any]:
    """Convert a CapabilityManifest to an MCP tool definition.

    MCP tool format:
    {
      "name": "tool_name",
      "description": "...",
      "inputSchema": {
        "type": "object",
        "properties": { ... },
        "required": [...]
      }
    }
    """
    type_map = {
        "string": "string", "integer": "integer", "number": "number",
        "boolean": "boolean", "array": "array", "object": "object",
        "any": "string",
    }

    properties = {}
    required = []

    for field_name, field in manifest.input_schema.items():
        prop: dict[str, Any] = {"type": type_map.get(field.type, "string")}
        if field.description:
            prop["description"] = field.description
        if field.type == "string" and field.enum:
            prop["enum"] = field.enum
        if not field.optional:
            required.append(field_name)
        properties[field_name] = prop

    return {
        "name": manifest.name,
        "description": manifest.metadata.description or "",
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


# ──────────────────────────────────────────────
# MCP Server — SSE Transport
# ──────────────────────────────────────────────

class MCPServer:
    """
    Intent OS MCP Server with SSE transport.

    Uses JSON-RPC 2.0 over Server-Sent Events per the MCP specification.
    Clients connect to /sse and send messages via POST to /messages.

    The server loads capabilities from the Intent OS Capability Registry
    and exposes them as MCP tools.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        adapter: str = "ollama",
    ) -> None:
        self.host = host
        self.port = port
        self.adapter = adapter
        self._httpd: HTTPServer | None = None
        self._running = False

        # Setup executor and registry
        self._setup_runtime()

    def _setup_runtime(self) -> None:
        """Initialize the Executor and Registry."""
        self.executor = Executor()
        self.registry = CapabilityRegistry(db_path=str(
            Path.home() / ".intent-os" / "store.db"
        ))
        self._register_builtin_adapters()

    def _register_builtin_adapters(self) -> None:
        """Register available runtime adapters."""
        adapters = []

        try:
            from adapters.ollama_adapter import OllamaAdapter
            try:
                import urllib.request
                req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
                resp = urllib.request.urlopen(req, timeout=1)
                if resp.status == 200:
                    adapters.append(OllamaAdapter())
                    logger.info("Ollama adapter loaded")
            except Exception:
                logger.debug("Ollama not available")
        except ImportError:
            pass

        try:
            from adapters.openai_adapter import OpenAIAdapter
            if os.environ.get("OPENAI_API_KEY"):
                adapters.append(OpenAIAdapter())
                logger.info("OpenAI adapter loaded")
        except ImportError:
            pass

        try:
            from adapters.openrouter_adapter import OpenRouterAdapter
            if os.environ.get("OPENROUTER_API_KEY"):
                adapters.append(OpenRouterAdapter())
                logger.info("OpenRouter adapter loaded")
        except ImportError:
            pass

        for adapter in adapters:
            self.executor.register_adapter(adapter.name, adapter)

        if not adapters:
            logger.warning("No runtime adapters available. Install ollama or set OPENAI_API_KEY.")

    def _handle_tools_list(self, msg_id: Any) -> dict[str, Any]:
        """Handle MCP tools/list request.

        Returns all registered capabilities as MCP tool definitions.
        """
        capabilities = self.registry.list_capabilities()
        tools = []

        for cap_info in capabilities:
            manifest = self.registry.get(cap_info["name"], cap_info["version"])
            if manifest:
                tools.append(_manifest_to_mcp_tool(manifest))

        return jsonrpc_result({"tools": tools}, id=msg_id)

    def _handle_tools_call(self, params: dict[str, Any], msg_id: Any) -> dict[str, Any]:
        """Handle MCP tools/call request.

        Executes the named capability with the provided arguments
        via the Intent OS Executor.
        """
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        if not name:
            return jsonrpc_error(-32602, "Missing required parameter: 'name'", id=msg_id)

        # Look up the capability in the registry
        manifest = self.registry.get(name)
        if manifest is None:
            return jsonrpc_error(-32602, f"Unknown capability: '{name}'", id=msg_id)

        # Determine which adapter to use
        adapter_name = self.adapter

        # Execute
        try:
            record = self.executor.execute(
                manifest=manifest,
                input_data=arguments,
                adapter_name=adapter_name,
            )
        except Exception as exc:
            logger.error(f"Execution failed: {exc}")
            return jsonrpc_error(-32603, f"Execution failed: {exc}", id=msg_id)

        if record.status != ExecutionStatus.SUCCESS:
            error_msg = record.error or "Execution returned non-success status"
            return jsonrpc_error(-32603, error_msg, id=msg_id)

        # Track usage on the marketplace entry (BluePrint Layer 6)
        self.registry.record_usage(manifest.id)

        # Strip internal fields from output
        output = record.output
        if isinstance(output, dict):
            output = {k: v for k, v in output.items() if not k.startswith("_")}

        return jsonrpc_result({"content": [{"type": "text", "text": json.dumps(output, indent=2, default=str)}]}, id=msg_id)

    def _process_message(self, body: dict[str, Any]) -> dict[str, Any]:
        """Process a JSON-RPC message and return a response."""
        msg_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params", {})

        if method == "tools/list":
            return self._handle_tools_list(msg_id)
        elif method == "tools/call":
            return self._handle_tools_call(params, msg_id)
        else:
            return jsonrpc_error(-32601, f"Method not found: '{method}'", id=msg_id)

    def status(self) -> dict[str, Any]:
        """Return server status info."""
        caps = self.registry.list_capabilities()
        tools = []
        for cap_info in caps:
            manifest = self.registry.get(cap_info["name"], cap_info["version"])
            if manifest:
                tools.append({
                    "name": manifest.name,
                    "description": manifest.metadata.description or "",
                    "adapter": self.adapter,
                })
        return {
            "host": self.host,
            "port": self.port,
            "transport": "sse",
            "default_adapter": self.adapter,
            "sse_path": "/sse",
            "messages_path": "/messages",
            "capability_count": len(tools),
            "capabilities": tools,
            "running": self._running,
        }

    def run(self) -> None:
        """Start the MCP Server (blocking)."""
        server = _MCPServerHandler.create(
            host=self.host,
            port=self.port,
            mcp_server=self,
        )
        self._httpd = server
        self._running = True
        logger.info(f"MCP Server listening on {self.host}:{self.port}")
        logger.info(f"  SSE endpoint: http://{self.host}:{self.port}/sse")
        logger.info(f"  Messages:     POST http://{self.host}:{self.port}/messages")
        logger.info(f"  Adapter: {self.adapter}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            server.server_close()
            logger.info("MCP Server stopped.")

    def stop(self) -> None:
        """Stop the MCP Server."""
        if self._httpd:
            self._httpd.shutdown()


# ──────────────────────────────────────────────
# HTTP Handler (SSE Transport)
# ──────────────────────────────────────────────

class _MCPServerHandler(BaseHTTPRequestHandler):
    """HTTP handler for MCP SSE transport.

    GET  /sse       — SSE stream (client connects here)
    POST /messages  — Receive JSON-RPC messages from client
    """

    _mcp_server: MCPServer | None = None
    _message_queue: queue.Queue = queue.Queue()
    _clients: list[threading.Event] = []

    @classmethod
    def create(cls, host: str, port: int, mcp_server: MCPServer) -> HTTPServer:
        cls._mcp_server = mcp_server
        server = HTTPServer((host, port), cls)
        return server

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug(format % args)

    def _send_sse(self, event: str, data: str) -> None:
        """Send an SSE event."""
        self.wfile.write(f"event: {event}\n".encode())
        self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    def do_GET(self) -> None:
        """Handle GET /sse — SSE stream."""
        if self.path != "/sse":
            self.send_response(404)
            self.end_headers()
            return

        # SSE connection setup
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        # Generate a session ID and send the endpoint event
        session_id = str(uuid.uuid4())
        self._send_sse("endpoint", json.dumps({"endpoint": f"/messages?sessionId={session_id}"}))

        # Send an initial 'tools/list' response
        mcp = self._mcp_server
        if mcp:
            result = mcp._handle_tools_list(None)
            self._send_sse("message", json.dumps(result))

        # Keep the connection open and listen for incoming messages
        client_event = threading.Event()
        self._clients.append(client_event)

        try:
            # Poll for messages to send back to this client
            while not client_event.is_set():
                try:
                    msg = self._message_queue.get(timeout=1)
                    self._send_sse("message", json.dumps(msg))
                except queue.Empty:
                    continue
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if client_event in self._clients:
                self._clients.remove(client_event)

    def do_POST(self) -> None:
        """Handle POST /messages — JSON-RPC messages from client."""
        if self.path.startswith("/messages"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                message = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send_json_response(jsonrpc_error(-32700, f"Parse error: {exc}"))
                return

            # Process the message
            mcp = self._mcp_server
            if mcp is None:
                self._send_json_response(jsonrpc_error(-32000, "Server not initialized"))
                return

            response = mcp._process_message(message)

            # If the message has an id, send the response back
            if message.get("id") is not None:
                self._send_json_response(response)

            # Also push to SSE queue for connected clients
            self._message_queue.put(response)
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json_response(self, data: dict[str, Any]) -> None:
        """Send a JSON-RPC response directly via HTTP."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
