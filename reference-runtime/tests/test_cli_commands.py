"""
Intent OS — CLI Command Tests

Tests cover all 11 CLI commands:
  1. validate   — Manifest validation
  2. run        — Capability execution
  3. compare    — Cross-runtime comparison
  4. list       — List adapters and capabilities
  5. registry   — Registry management
  6. event      — Event Store queries
  7. analytics  — Execution analysis
  8. workflow   — Plan and run workflows
  9. mcp-server — MCP Server management
  10. import    — Import from external formats
  11. export    — Export to external formats

All tests mock the underlying services to avoid requiring real API keys,
running servers, or touching disk. Output is captured via StringIO.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Ensure project root is in path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

# text_summarize.yaml lives inside reference-runtime/examples/
EXAMPLE_MANIFEST = str(_project_root / "examples" / "text_summarize.yaml")
EXAMPLE_WORKFLOW = str(_project_root / "examples" / "research_workflow.yaml")


class CLITestBase:
    """Base class with helpers for CLI testing."""

    @staticmethod
    def make_args(**kwargs) -> Any:
        """Build a mock argparse.Namespace from keyword arguments."""
        return type("Args", (), kwargs)()

    @staticmethod
    def run_command(cmd_func, args) -> tuple[str, str, int]:
        """Run a CLI command function with captured output and mocked sys.exit.

        Returns (stdout, stderr, exit_code).
        """
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = [0]

        def fake_exit(code=0):
            exit_code[0] = code
            raise SystemExit(code)

        with patch("sys.stdout", stdout), \
             patch("sys.stderr", stderr), \
             patch("sys.exit", fake_exit):
            try:
                cmd_func(args)
            except SystemExit:
                pass
            except Exception:
                import traceback
                stderr.write(traceback.format_exc())
                exit_code[0] = 1

        return stdout.getvalue(), stderr.getvalue(), exit_code[0]


# ====================================================================
# 1. validate
# ====================================================================

class TestValidateCommand(CLITestBase):
    """intent-os validate <manifest>"""

    def test_validate_valid_manifest(self):
        """Valid manifest should print OK."""
        from commands.validate import cmd_validate
        args = self.make_args(manifest=EXAMPLE_MANIFEST)
        out, err, code = self.run_command(cmd_validate, args)
        assert code == 0, f"err={err}"
        assert "Manifest is valid" in out

    def test_validate_missing_file(self):
        """Missing manifest file should exit with error."""
        from commands.validate import cmd_validate
        args = self.make_args(manifest="/nonexistent/manifest.yaml")
        out, err, code = self.run_command(cmd_validate, args)
        assert code == 1
        assert "File not found" in err


# ====================================================================
# 2. run
# ====================================================================

class TestRunCommand(CLITestBase):
    """intent-os run <manifest> --adapter <name> --input <json>"""

    def _run_with_mocks(self, adapter_list, execute_result=None, execute_side_effect=None):
        """Run cmd_run with mocked load_manifest and setup_executor."""
        from commands.run import cmd_run

        with patch("commands.run.load_manifest") as mock_load, \
             patch("commands.run.setup_executor") as mock_setup:
            mock_manifest = MagicMock()
            mock_manifest.id = "test@1.0.0"
            mock_manifest.name = "test"
            mock_manifest.version = "1.0.0"
            mock_load.return_value = (mock_manifest, MagicMock())

            mock_exe = MagicMock()
            mock_exe.get_available_adapters.return_value = adapter_list
            mock_exe._adapters = {a: MagicMock() for a in adapter_list}
            if execute_result is not None:
                mock_exe.execute.return_value = execute_result
            if execute_side_effect is not None:
                mock_exe.execute.side_effect = execute_side_effect
            mock_setup.return_value = mock_exe

            args = self.make_args(
                manifest="test.yaml",
                adapter=None,
                input='{"text": "hello"}',
                input_file=None,
                output=None,
                save=None,
            )
            return self.run_command(cmd_run, args)

    def test_run_no_adapters(self):
        """Run with no adapters loaded should exit with error."""
        out, err, code = self._run_with_mocks([])
        assert code == 1
        assert "No runtime adapters available" in err

    def test_run_adapter_not_found(self):
        """Requesting an unknown adapter should exit with error."""
        from commands.run import cmd_run
        with patch("commands.run.load_manifest") as mock_load, \
             patch("commands.run.setup_executor") as mock_setup:
            mock_manifest = MagicMock()
            mock_manifest.id = "test@1.0.0"
            mock_manifest.name = "test"
            mock_manifest.version = "1.0.0"
            mock_load.return_value = (mock_manifest, MagicMock())

            mock_exe = MagicMock()
            mock_exe.get_available_adapters.return_value = ["openai"]
            mock_exe._adapters = {"openai": MagicMock()}
            mock_setup.return_value = mock_exe

            args = self.make_args(
                manifest="test.yaml",
                adapter="nonexistent",
                input='{"text": "hello"}',
                input_file=None,
                output=None,
                save=None,
            )
            out, err, code = self.run_command(cmd_run, args)
            assert code == 1
            assert "not loaded" in err or "Available" in err

    def test_run_success(self):
        """Successful execution should print results."""
        from core.models import ExecutionRecord, ExecutionStatus
        mock_record = MagicMock(spec=ExecutionRecord)
        mock_record.status = ExecutionStatus.SUCCESS
        mock_record.runtime_id = "openai"
        mock_record.adapter = "OpenAIAdapter"
        mock_record.total_latency_ms = 1234
        mock_record.total_cost_usd = 0.05
        mock_record.total_tokens = 500
        mock_record.events = []
        mock_record.output = {"summary": "test output"}
        mock_record.error = None

        out, err, code = self._run_with_mocks(["openai"], execute_result=mock_record)
        assert code == 0, f"err={err}"
        assert "EXECUTION RESULT" in out or "success" in out.lower()

    def test_run_execution_failure(self):
        """Execution failure should exit with error."""
        out, err, code = self._run_with_mocks(
            ["openai"],
            execute_side_effect=RuntimeError("API call failed"),
        )
        assert code == 1


# ====================================================================
# 3. compare
# ====================================================================

class TestCompareCommand(CLITestBase):
    """intent-os compare <manifest> --input <json>"""

    def test_compare_with_two_adapters(self):
        """Compare with 2+ adapters should show comparison results."""
        from commands.compare import cmd_compare
        from core.models import ExecutionRecord, ExecutionStatus

        with patch("commands.compare.load_manifest") as mock_load, \
             patch("commands.compare.setup_executor") as mock_setup:
            mock_manifest = MagicMock()
            mock_manifest.id = "test@1.0.0"
            mock_manifest.name = "test"
            mock_manifest.version = "1.0.0"
            mock_load.return_value = (mock_manifest, MagicMock())

            mock_exe = MagicMock()
            mock_exe.get_available_adapters.return_value = ["openai", "anthropic"]

            mock_rec_a = MagicMock(spec=ExecutionRecord)
            mock_rec_a.status = ExecutionStatus.SUCCESS
            mock_rec_a.runtime_id = "openai"
            mock_rec_a.adapter = "OpenAIAdapter"
            mock_rec_a.total_latency_ms = 1000
            mock_rec_a.total_cost_usd = 0.02
            mock_rec_a.total_tokens = 200
            mock_rec_a.events = []
            mock_rec_a.manifest_name = "test"
            mock_rec_a.manifest_version = "1.0.0"
            mock_rec_a.output = {"summary": "hello"}

            mock_rec_b = MagicMock(spec=ExecutionRecord)
            mock_rec_b.status = ExecutionStatus.SUCCESS
            mock_rec_b.runtime_id = "anthropic"
            mock_rec_b.adapter = "AnthropicAdapter"
            mock_rec_b.total_latency_ms = 2000
            mock_rec_b.total_cost_usd = 0.04
            mock_rec_b.total_tokens = 300
            mock_rec_b.events = []
            mock_rec_b.manifest_name = "test"
            mock_rec_b.manifest_version = "1.0.0"
            mock_rec_b.output = {"summary": "hello"}

            mock_exe.execute.side_effect = [mock_rec_a, mock_rec_b]
            mock_setup.return_value = mock_exe

            args = self.make_args(
                manifest="test.yaml",
                input='{"text": "hello"}',
                save=None,
            )
            out, err, code = self.run_command(cmd_compare, args)
            assert code == 0, f"err={err}"

    def test_compare_single_adapter(self):
        """Compare with only 1 adapter should still execute."""
        from commands.compare import cmd_compare
        from core.models import ExecutionRecord, ExecutionStatus

        with patch("commands.compare.load_manifest") as mock_load, \
             patch("commands.compare.setup_executor") as mock_setup:
            mock_manifest = MagicMock()
            mock_manifest.id = "test@1.0.0"
            mock_manifest.name = "test"
            mock_manifest.version = "1.0.0"
            mock_load.return_value = (mock_manifest, MagicMock())

            mock_exe = MagicMock()
            mock_exe.get_available_adapters.return_value = ["openai"]

            mock_rec = MagicMock(spec=ExecutionRecord)
            mock_rec.status = ExecutionStatus.SUCCESS
            mock_rec.total_latency_ms = 1000
            mock_rec.total_cost_usd = 0.02
            mock_rec.total_tokens = 200
            mock_rec.events = []

            mock_exe.execute.return_value = mock_rec
            mock_setup.return_value = mock_exe

            args = self.make_args(
                manifest="test.yaml",
                input='{"text": "hello"}',
                save=None,
            )
            out, err, code = self.run_command(cmd_compare, args)
            assert code == 0, f"err={err}"


# ====================================================================
# 4. list
# ====================================================================

class TestListCommand(CLITestBase):
    """intent-os list"""

    def test_list_empty(self):
        """List with no adapters/capabilities should show '(none)'."""
        from commands.list import cmd_list
        with patch("commands.list.setup_executor") as mock_setup, \
             patch("commands.list.get_registry_store") as mock_reg:
            mock_exe = MagicMock()
            mock_exe.get_available_adapters.return_value = []
            mock_setup.return_value = mock_exe

            mock_registry = MagicMock()
            mock_registry.list_capabilities.return_value = []
            mock_reg.return_value = (MagicMock(), mock_registry)

            args = self.make_args()
            out, err, code = self.run_command(cmd_list, args)
            assert code == 0
            assert "(none)" in out

    def test_list_with_capabilities(self):
        """List with capabilities should show them."""
        from commands.list import cmd_list
        with patch("commands.list.setup_executor") as mock_setup, \
             patch("commands.list.get_registry_store") as mock_reg:
            mock_exe = MagicMock()
            mock_exe.get_available_adapters.return_value = ["openai"]
            mock_setup.return_value = mock_exe

            mock_registry = MagicMock()
            mock_registry.list_capabilities.return_value = [
                {"name": "web_search", "version": "1.0.0", "id": "web_search@1.0.0",
                 "publisher": "test", "description": "Search", "tags": ["search"]},
            ]
            mock_reg.return_value = (MagicMock(), mock_registry)

            args = self.make_args()
            out, err, code = self.run_command(cmd_list, args)
            assert code == 0
            assert "web_search" in out
            assert "openai" in out


# ====================================================================
# 5. registry
# ====================================================================

class TestRegistryCommand(CLITestBase):
    """intent-os registry <action>"""

    def _reg_args(self, **kw):
        return self.make_args(**kw)

    def test_registry_list_empty(self):
        """Registry list with no entries should show message."""
        from commands.registry import cmd_registry
        with patch("commands.registry.get_registry_store") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.list_capabilities.return_value = []
            mock_reg.return_value = (MagicMock(), mock_registry)
            out, err, code = self.run_command(
                cmd_registry, self._reg_args(action="list"))
            assert code == 0
            assert "No capabilities registered" in out

    def test_registry_list_with_entries(self):
        """Registry list with entries should show them."""
        from commands.registry import cmd_registry
        with patch("commands.registry.get_registry_store") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.list_capabilities.return_value = [
                {"name": "web_search", "version": "1.0.0",
                 "publisher": "test", "description": "Search the web"},
            ]
            mock_reg.return_value = (MagicMock(), mock_registry)
            out, err, code = self.run_command(
                cmd_registry, self._reg_args(action="list"))
            assert code == 0
            assert "web_search" in out

    def test_registry_get_not_found(self):
        """Registry get for unknown capability should exit with error."""
        from commands.registry import cmd_registry
        with patch("commands.registry.get_registry_store") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.get.return_value = None
            mock_reg.return_value = (MagicMock(), mock_registry)
            out, err, code = self.run_command(cmd_registry, self._reg_args(
                action="get", name="nonexistent", version=None))
            assert code == 1
            assert "not found" in out

    def test_registry_get_found(self):
        """Registry get for existing capability should show details."""
        from commands.registry import cmd_registry
        with patch("commands.registry.get_registry_store") as mock_reg:
            from core.models import CapabilityManifest, MetadataSpec, FieldSchema
            mock_manifest = CapabilityManifest(
                metadata=MetadataSpec(name="web_search", version="1.0.0",
                                      publisher="test", description="Search", tags=["web"]),
                input_schema={"query": FieldSchema(type="string")},
                output_schema={"results": FieldSchema(type="array")},
            )
            mock_registry = MagicMock()
            mock_registry.get.return_value = mock_manifest
            mock_reg.return_value = (MagicMock(), mock_registry)
            out, err, code = self.run_command(cmd_registry, self._reg_args(
                action="get", name="web_search", version=None))
            assert code == 0
            assert "web_search" in out

    def test_registry_register_success(self):
        """Registry register should succeed for a valid manifest."""
        from commands.registry import cmd_registry
        # registry.py imports parse_manifest inside the function body,
        # so we patch at the source: core.parser.parse_manifest
        with patch("core.parser.parse_manifest") as mock_parse, \
             patch("commands.registry.get_registry_store") as mock_reg, \
             patch("commands.registry.Path.exists", return_value=True):

            mock_manifest = MagicMock()
            mock_manifest.id = "test_cap@1.0.0"
            mock_manifest.name = "test_cap"
            mock_manifest.version = "1.0.0"
            mock_parse.return_value = (mock_manifest, MagicMock())

            mock_registry = MagicMock()
            mock_reg.return_value = (MagicMock(), mock_registry)

            out, err, code = self.run_command(cmd_registry, self._reg_args(
                action="register", manifest_path="test.yaml"))
            assert code == 0, f"err={err}"
            assert "Registered" in out

    def test_registry_unregister_success(self):
        """Registry unregister should succeed."""
        from commands.registry import cmd_registry
        with patch("commands.registry.get_registry_store") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.unregister.return_value = None
            mock_reg.return_value = (MagicMock(), mock_registry)
            out, err, code = self.run_command(cmd_registry, self._reg_args(
                action="unregister", name="web_search", version=None))
            assert code == 0
            assert "Unregistered" in out

    def test_registry_search_no_results(self):
        """Registry search with no matches should show message."""
        from commands.registry import cmd_registry
        with patch("commands.registry.get_registry_store") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.find_by_text.return_value = []
            mock_reg.return_value = (MagicMock(), mock_registry)
            out, err, code = self.run_command(cmd_registry, self._reg_args(
                action="search", query="nonexistent", limit=10))
            assert code == 0
            assert "No capabilities matching" in out

    def test_registry_search_with_results(self):
        """Registry search with matches should display them."""
        from commands.registry import cmd_registry
        with patch("commands.registry.get_registry_store") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.find_by_text.return_value = [
                {
                    "capability": {"name": "web_search", "version": "1.0.0",
                                   "description": "Search the web", "publisher": "test",
                                   "tags": ["search"]},
                    "score": 0.85,
                },
            ]
            mock_reg.return_value = (MagicMock(), mock_registry)
            out, err, code = self.run_command(cmd_registry, self._reg_args(
                action="search", query="web search", limit=10))
            assert code == 0
            assert "web_search" in out
            assert "0.85" in out


# ====================================================================
# 6. event
# ====================================================================

class TestEventCommand(CLITestBase):
    """intent-os event <action>"""

    def test_event_list_empty(self):
        """Event list with no records should show 0 counts."""
        from commands.event import cmd_event
        with patch("commands.event.get_event_store") as mock_store:
            mock = MagicMock()
            mock.get_event_count.return_value = 0
            mock.get_record_count.return_value = 0
            mock_store.return_value = mock
            out, err, code = self.run_command(
                cmd_event, self.make_args(action="list"))
            assert code == 0
            assert "Events: 0" in out

    def test_event_list_with_records(self):
        """Event list with records should show them."""
        from commands.event import cmd_event
        with patch("commands.event.get_event_store") as mock_store:
            mock = MagicMock()
            mock.get_event_count.return_value = 5
            mock.get_record_count.return_value = 2
            mock.get_all_trace_ids.return_value = ["trace-1", "trace-2"]
            mock.get_record.side_effect = lambda t: {
                "trace-1": {"manifest_name": "web_search", "manifest_version": "1.0.0", "status": "success"},
                "trace-2": {"manifest_name": "text_summarize", "manifest_version": "1.0.0", "status": "failure"},
            }.get(t)
            mock_store.return_value = mock
            out, err, code = self.run_command(
                cmd_event, self.make_args(action="list"))
            assert code == 0
            assert "Events: 5" in out

    def test_event_trace_not_found(self):
        """Event trace for unknown ID should show message."""
        from commands.event import cmd_event
        with patch("commands.event.get_event_store") as mock_store:
            mock = MagicMock()
            mock.get_events_by_trace.return_value = []
            mock_store.return_value = mock
            out, err, code = self.run_command(
                cmd_event, self.make_args(action="trace", trace_id="nonexistent"))
            assert code == 0
            assert "No events found" in out

    def test_event_query(self):
        """Event query with filters should work."""
        from commands.event import cmd_event
        with patch("commands.event.get_event_store") as mock_store:
            mock = MagicMock()
            mock.query_events.return_value = [
                {"timestamp": "2026-07-22T10:00:00", "event_type": "TaskStarted",
                 "capability": "web_search", "runtime": "openai"},
            ]
            mock_store.return_value = mock
            out, err, code = self.run_command(cmd_event, self.make_args(
                action="query",
                trace_id=None, event_type=None, capability=None,
                runtime=None, limit=20,
            ))
            assert code == 0
            assert "Found" in out


# ====================================================================
# 7. analytics
# ====================================================================

class TestAnalyticsCommand(CLITestBase):
    """intent-os analytics <action>"""

    def _mock_empty_store(self):
        mock_store = MagicMock()
        mock_store.get_record_count.return_value = 0
        mock_store.get_capability_stats.return_value = []
        mock_store.get_runtime_stats.return_value = []
        mock_store.get_failure_analysis.return_value = []
        mock_store.get_time_series.return_value = []
        mock_store.query_records.return_value = []
        return mock_store

    def _run_analytics(self, action, mock_store=None):
        from commands.analytics import cmd_analytics
        if mock_store is None:
            mock_store = self._mock_empty_store()
        with patch("commands.analytics.get_event_store", return_value=mock_store):
            return self.run_command(cmd_analytics, self.make_args(action=action,
                output_path=None, limit=1000))

    def test_analytics_summary_no_data(self):
        """Analytics summary with no data should still output."""
        out, err, code = self._run_analytics("summary")
        assert code == 0
        assert "Execution Summary" in out

    def test_analytics_capabilities_no_data(self):
        """Analytics capabilities with no data should show message."""
        out, err, code = self._run_analytics("capabilities")
        assert code == 0
        assert "No execution data available" in out

    def test_analytics_runtimes_no_data(self):
        """Analytics runtimes with no data should show message."""
        out, err, code = self._run_analytics("runtimes")
        assert code == 0
        assert "No execution data available" in out

    def test_analytics_failures_no_data(self):
        """Analytics failures with no data should show zeros."""
        out, err, code = self._run_analytics("failures")
        assert code == 0
        assert "Total records: 0" in out

    def test_analytics_suggestions_no_data(self):
        """Analytics suggestions with no data should show message."""
        out, err, code = self._run_analytics("suggestions")
        assert code == 0
        assert "No optimization suggestions" in out

    def test_analytics_export_no_data(self):
        """Analytics export with no data should export 0 records."""
        out, err, code = self._run_analytics("export")
        assert code == 0
        assert "Exported 0 records" in out

    def test_analytics_summary_with_data(self):
        """Analytics summary with data should show results."""
        mock_store = MagicMock()
        mock_store.get_capability_stats.return_value = [
            {"manifest_name": "web_search", "total_runs": 10,
             "success_count": 9, "failure_count": 1,
             "avg_latency_ms": 500, "avg_cost_usd": 0.01,
             "avg_tokens": 200, "success_rate": 0.9},
        ]
        mock_store.get_runtime_stats.return_value = [
            {"runtime_id": "openai", "total_runs": 5, "success_rate": 0.8,
             "avg_latency_ms": 300, "avg_cost_usd": 0.02, "avg_tokens": 150},
        ]
        mock_store.get_failure_analysis.return_value = [
            {"manifest_name": "web_search", "runtime_id": "openai",
             "failure_count": 1, "avg_latency_ms": 500},
        ]
        mock_store.get_time_series.return_value = [
            {"period": "2026-07-22", "run_count": 10,
             "success_count": 9, "failure_count": 1,
             "avg_latency_ms": 500, "avg_cost_usd": 0.01},
        ]
        mock_store.query_records.return_value = []
        mock_store.get_record_count.return_value = 10

        out, err, code = self._run_analytics("summary", mock_store=mock_store)
        assert code == 0
        assert "Execution Summary" in out


# ====================================================================
# 8. workflow
# ====================================================================

class TestWorkflowCommand(CLITestBase):
    """intent-os workflow <action>"""

    def test_workflow_plan_success(self):
        """Workflow plan with a goal should produce a plan."""
        from commands.workflow import cmd_workflow
        args = self.make_args(
            action="plan", query="research AI trends",
            simulate=False, adapter=None, input=None,
        )
        out, err, code = self.run_command(cmd_workflow, args)
        assert code == 0, f"err={err}"
        assert "Plan generated" in out

    def test_workflow_run_missing_file(self):
        """Workflow run with missing file should exit with error."""
        from commands.workflow import cmd_workflow
        args = self.make_args(
            action="run", query="/nonexistent/workflow.yaml",
            input=None, adapter=None, simulate=True,
        )
        out, err, code = self.run_command(cmd_workflow, args)
        assert code == 1
        assert "File not found" in err

    def test_workflow_run_simulated(self):
        """Workflow run with simulated executor should succeed."""
        from commands.workflow import cmd_workflow
        args = self.make_args(
            action="run", query=EXAMPLE_WORKFLOW,
            input='{"company_name": "NVIDIA", "ticker": "NVDA"}',
            adapter=None, simulate=True,
        )
        out, err, code = self.run_command(cmd_workflow, args)
        assert code == 0, f"err={err}"
        assert "Loaded workflow" in out or "Status" in out


# ====================================================================
# 9. mcp-server
# ====================================================================

class TestMCPServerCommand(CLITestBase):
    """intent-os mcp-server <action>"""

    def test_mcp_server_status(self):
        """MCP server status should show server info."""
        from commands.mcp_server import cmd_mcp_server
        args = self.make_args(
            mcp_action="status", port=8080, adapter="ollama",
            host="127.0.0.1",
        )
        out, err, code = self.run_command(cmd_mcp_server, args)
        assert code == 0, f"err={err}"
        assert "Intent OS MCP Server" in out


# ====================================================================
# 10. import
# ====================================================================

class TestImportCommand(CLITestBase):
    """intent-os import <format> <source>"""

    def test_import_openai_function_success(self):
        """Import from OpenAI function should succeed."""
        from commands.import_cmd import cmd_import
        sample_function = json.dumps({
            "name": "search_web",
            "description": "Search the web",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        })

        with patch("commands.import_cmd.Path.exists", return_value=True), \
             patch("commands.import_cmd.Path.read_text", return_value=sample_function), \
             patch("commands.import_cmd.get_registry_store") as mock_reg:
            mock_registry = MagicMock()
            mock_reg.return_value = (MagicMock(), mock_registry)

            args = self.make_args(
                format="openai-function", source="tool.json",
                output_dir="./manifests", publisher=None,
                tags=None, timeout=30,
            )
            out, err, code = self.run_command(cmd_import, args)
            assert code == 0, f"err={err}"
            assert "Imported" in out

    def test_import_unknown_format(self):
        """Import with unknown format should exit with error."""
        from commands.import_cmd import cmd_import
        with patch("commands.import_cmd.get_registry_store") as mock_reg:
            mock_reg.return_value = (MagicMock(), MagicMock())
            args = self.make_args(
                format="unknown", source="tool.json",
                output_dir="./manifests", publisher=None,
                tags=None, timeout=30,
            )
            out, err, code = self.run_command(cmd_import, args)
            assert code == 1
            assert "Unknown import format" in err


# ====================================================================
# 11. export
# ====================================================================

class TestExportCommand(CLITestBase):
    """intent-os export <format> <source>"""

    def test_export_openai_success(self):
        """Export to OpenAI format should succeed."""
        from commands.export import cmd_export
        args = self.make_args(
            format="openai", source=EXAMPLE_MANIFEST,
            output=None, as_tool=False,
        )
        out, err, code = self.run_command(cmd_export, args)
        assert code == 0, f"err={err}"
        assert len(out) > 0

    def test_export_mcp_success(self):
        """Export to MCP format should succeed."""
        from commands.export import cmd_export
        args = self.make_args(
            format="mcp", source=EXAMPLE_MANIFEST,
            output=None, as_tool=False,
        )
        out, err, code = self.run_command(cmd_export, args)
        assert code == 0, f"err={err}"
        assert len(out) > 0

    def test_export_unknown_format(self):
        """Export with unknown format should exit with error."""
        from commands.export import cmd_export
        args = self.make_args(
            format="unknown", source=EXAMPLE_MANIFEST,
            output=None, as_tool=False,
        )
        out, err, code = self.run_command(cmd_export, args)
        assert code == 1
        assert "Unknown export format" in err


# ====================================================================
# 12. quickstart
# ====================================================================

class TestQuickstartCommand(CLITestBase):
    """intent-os quickstart"""

    def test_quickstart_output(self):
        """Quickstart should display getting-started steps."""
        from commands.quickstart import cmd_quickstart
        args = self.make_args()
        out, err, code = self.run_command(cmd_quickstart, args)
        assert code == 0
        assert "Quickstart" in out
        assert "Validate" in out
        assert "Execute" in out
        assert "Ollama" in out
