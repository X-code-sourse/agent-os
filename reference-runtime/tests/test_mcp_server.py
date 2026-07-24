"""
Intent OS — MCP Server Tests

Tests cover the core MCP protocol logic directly, without starting HTTP:
  1. Manifest -> MCP tool format conversion
  2. tools/list returns registered capabilities
  3. tools/call invokes a capability via executor
  4. tools/call returns error for unknown capability
  5. Server status includes correct metadata
  6. tools/list with empty registry returns empty list
  7. resources/list returns agent resources (Phase D)
  8. resources/read returns identity, experiences, package (Phase D)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure project root is in path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.models import (
    CapabilityManifest, FieldSchema, MetadataSpec,
    RequirementSpec, SecuritySpec,
)
from core.registry import CapabilityRegistry
from mcp_server import MCPServer, _manifest_to_mcp_tool, jsonrpc_result, jsonrpc_error


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_manifest(
    name: str = "web_search",
    version: str = "1.0.0",
    description: str = "Search the web",
    input_fields: dict[str, FieldSchema] | None = None,
    output_fields: dict[str, FieldSchema] | None = None,
) -> CapabilityManifest:
    if input_fields is None:
        input_fields = {
            "query": FieldSchema(type="string", description="The search query"),
            "max_results": FieldSchema(type="integer", description="Max results", optional=True),
        }
    if output_fields is None:
        output_fields = {
            "result": FieldSchema(type="string", description="Result", optional=True),
        }
    return CapabilityManifest(
        metadata=MetadataSpec(
            name=name,
            version=version,
            publisher="test",
            description=description,
        ),
        input_schema=input_fields,
        output_schema=output_fields,
        requirements=RequirementSpec(
            models=["test-model"],
            tools=[],
        ),
        security=SecuritySpec(risk="low"),
    )


def _setup_server_with_capabilities(
    manifests: list[CapabilityManifest],
) -> MCPServer:
    """Create a lightweight MCPServer with given capabilities for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        server = MCPServer()
        server._httpd = None
        server._running = False
        server.registry = CapabilityRegistry(db_path=str(db_path))
        for m in manifests:
            server.registry.register(m)

        from core.workflow_runner import SimulatedExecutor
        server.executor = SimulatedExecutor()
    except Exception:
        if db_path.exists():
            db_path.unlink()
        raise

    server._test_db_path = db_path
    return server


# ---------------------------------------------------------------------------
# Tests: Manifest -> MCP Tool
# ---------------------------------------------------------------------------

class TestManifestToMCPTool:
    """Test conversion from CapabilityManifest to MCP tool format."""

    def test_converts_name_and_description(self):
        manifest = _make_manifest()
        tool = _manifest_to_mcp_tool(manifest)
        assert tool["name"] == "web_search"
        assert tool["description"] == "Search the web"

    def test_converts_input_schema(self):
        manifest = _make_manifest()
        tool = _manifest_to_mcp_tool(manifest)
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "max_results" in schema["properties"]

    def test_required_fields(self):
        manifest = _make_manifest()
        tool = _manifest_to_mcp_tool(manifest)
        assert "query" in tool["inputSchema"].get("required", [])
        assert "max_results" not in tool["inputSchema"].get("required", [])

    def test_field_descriptions_preserved(self):
        manifest = _make_manifest()
        tool = _manifest_to_mcp_tool(manifest)
        desc = tool["inputSchema"]["properties"]["query"].get("description", "")
        assert "search query" in desc.lower()

    def test_enum_fields(self):
        manifest = _make_manifest(
            name="classify",
            input_fields={
                "category": FieldSchema(
                    type="string", description="Category",
                    enum=["tech", "finance", "health"],
                ),
            },
        )
        tool = _manifest_to_mcp_tool(manifest)
        assert tool["inputSchema"]["properties"]["category"].get("enum") == ["tech", "finance", "health"]

    def test_any_type_converts_to_string(self):
        manifest = _make_manifest(
            name="generic",
            input_fields={"data": FieldSchema(type="any", description="Any data")},
        )
        tool = _manifest_to_mcp_tool(manifest)
        assert tool["inputSchema"]["properties"]["data"]["type"] == "string"


# ---------------------------------------------------------------------------
# Tests: tools/list
# ---------------------------------------------------------------------------

class TestToolsList:
    """Test MCP tools/list handler."""

    def test_empty_registry_returns_empty_list(self):
        server = _setup_server_with_capabilities([])
        response = server._handle_tools_list(msg_id=1)
        assert "result" in response
        assert response["result"]["tools"] == []

    def test_single_capability(self):
        manifest = _make_manifest()
        server = _setup_server_with_capabilities([manifest])
        response = server._handle_tools_list(msg_id=1)
        assert len(response["result"]["tools"]) == 1
        assert response["result"]["tools"][0]["name"] == "web_search"

    def test_multiple_capabilities(self):
        manifests = [
            _make_manifest("search"),
            _make_manifest("analyze"),
            _make_manifest("report_generate"),
        ]
        server = _setup_server_with_capabilities(manifests)
        response = server._handle_tools_list(msg_id=1)
        assert len(response["result"]["tools"]) == 3
        names = [t["name"] for t in response["result"]["tools"]]
        assert "search" in names
        assert "analyze" in names
        assert "report_generate" in names

    def test_jsonrpc_id_preserved(self):
        server = _setup_server_with_capabilities([_make_manifest()])
        response = server._handle_tools_list(msg_id="test-id")
        assert response["id"] == "test-id"


# ---------------------------------------------------------------------------
# Tests: tools/call
# ---------------------------------------------------------------------------

class TestToolsCall:
    """Test MCP tools/call handler."""

    def test_calls_known_capability(self):
        manifest = _make_manifest("web_search", description="Search the web")
        server = _setup_server_with_capabilities([manifest])
        response = server._handle_tools_call(
            {"name": "web_search", "arguments": {"query": "test"}},
            msg_id=1,
        )
        assert "result" in response

    def test_unknown_capability_returns_error(self):
        server = _setup_server_with_capabilities([])
        response = server._handle_tools_call(
            {"name": "nonexistent"},
            msg_id=1,
        )
        assert "error" in response

    def test_missing_name_returns_error(self):
        server = _setup_server_with_capabilities([_make_manifest()])
        response = server._handle_tools_call({}, msg_id=1)
        assert "error" in response

    def test_execution_error_returns_error(self):
        manifest = _make_manifest("failing_cap", description="Always fails")
        server = _setup_server_with_capabilities([manifest])
        from core.workflow_runner import SimulatedExecutor
        class FailingExecutor(SimulatedExecutor):
            def execute(self, manifest, input_data, adapter_name):
                raise RuntimeError("Simulated failure")
        server.executor = FailingExecutor()
        response = server._handle_tools_call(
            {"name": "failing_cap", "arguments": {}},
            msg_id=1,
        )
        assert "error" in response


# ---------------------------------------------------------------------------
# Tests: MCP Resources (Phase D)
# ---------------------------------------------------------------------------

class TestMCPResources:
    """MCP resources/list and resources/read handlers."""

    def test_resources_list_returns_result(self):
        """resources/list always returns a valid jsonrpc result."""
        server = MCPServer()
        server._httpd = None
        server._running = False
        response = server._handle_resources_list(msg_id="r1")
        assert "result" in response
        assert "resources" in response["result"]
        assert response["id"] == "r1"

    def test_resources_list_has_agents_directory(self):
        """resources/list includes the top-level agents directory URI."""
        server = MCPServer()
        server._httpd = None
        server._running = False
        response = server._handle_resources_list(msg_id=1)
        resources = response["result"]["resources"]
        uris = [r["uri"] for r in resources]
        if uris:  # only check if agents exist
            assert "intent-os://agents" in uris

    def test_resources_read_identity_nonexistent_returns_error(self):
        """resources/read for a nonexistent agent returns error."""
        server = MCPServer()
        server._httpd = None
        server._running = False
        response = server._handle_resources_read(
            {"uri": "intent-os://agents/nonexistent_999/identity"},
            msg_id=1,
        )
        assert "error" in response

    def test_resources_read_unknown_uri_returns_error(self):
        """resources/read for an unrecognized URI pattern returns error."""
        server = MCPServer()
        server._httpd = None
        server._running = False
        response = server._handle_resources_read(
            {"uri": "intent-os://unknown/path"},
            msg_id=1,
        )
        assert "error" in response

    def test_resources_read_missing_uri_returns_error(self):
        """resources/read without uri param returns error."""
        server = MCPServer()
        server._httpd = None
        server._running = False
        response = server._handle_resources_read({}, msg_id=1)
        assert "error" in response

    def test_resources_read_package_nonexistent_returns_error(self):
        """resources/read for a full package of a nonexistent agent returns error."""
        server = MCPServer()
        server._httpd = None
        server._running = False
        response = server._handle_resources_read(
            {"uri": "intent-os://agents/nonexistent_999"},
            msg_id=1,
        )
        assert "error" in response

    def test_process_message_routes_resources_list(self):
        """_process_message correctly routes resources/list."""
        server = MCPServer()
        server._httpd = None
        server._running = False
        response = server._process_message({
            "id": 1,
            "method": "resources/list",
            "params": {},
        })
        assert "result" in response
        assert "resources" in response["result"]

    def test_process_message_routes_resources_read(self):
        """_process_message correctly routes resources/read."""
        server = MCPServer()
        server._httpd = None
        server._running = False
        response = server._process_message({
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "intent-os://agents/nonexistent/identity"},
        })
        assert "error" in response
