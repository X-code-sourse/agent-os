"""
Intent OS — Executor Tests

Tests cover the Execution Engine (core/executor.py):
  1. _validate_output() — pure function for schema validation
  2. Executor adapter management (register, list, select)
  3. Executor._select_adapter() — selection logic
  4. Executor._build_execution_record() — adapter metadata extraction
  5. Executor.execute() — end-to-end execution flow via mocked adapters
  6. Error paths — no adapter, execution failure, schema mismatch

Previously the Executor was only tested indirectly through Scheduler and CLI
tests. These tests provide direct, focused coverage of the execution layer.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Ensure project root is in path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.executor import (
    Executor,
    ExecutionError,
    AdapterNotFoundError,
    SchemaValidationError,
    _validate_output,
)
from core.models import (
    CapabilityManifest,
    ExecutionRecord,
    ExecutionStatus,
    EventType,
    FieldSchema,
    MetadataSpec,
    RequirementSpec,
    SecuritySpec,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

def _make_manifest(
    name: str = "test_cap",
    version: str = "1.0.0",
    description: str = "A test capability",
    input_fields: dict[str, FieldSchema] | None = None,
    output_fields: dict[str, FieldSchema] | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        metadata=MetadataSpec(name=name, version=version, publisher="test", description=description),
        input_schema=input_fields or {"text": FieldSchema(type="string")},
        output_schema=output_fields or {"summary": FieldSchema(type="string")},
        requirements=RequirementSpec(),
        security=SecuritySpec(),
    )


def _make_adapter(
    name: str = "mock_adapter",
    version: str = "0.1.0",
    default_model: str = "mock-model",
) -> MagicMock:
    """Create a mock adapter that behaves like a real AdapterBase instance."""
    adapter = MagicMock()
    adapter.name = name
    adapter.version = version
    adapter.default_model = default_model
    adapter.execute.return_value = {"summary": "mock output"}
    return adapter


# ====================================================================
# 1. _validate_output
# ====================================================================

class TestValidateOutput:
    """Test the pure _validate_output() function (module-level)."""

    def test_valid_string_field(self):
        """String field with correct type should pass."""
        manifest = _make_manifest(output_fields={"summary": FieldSchema(type="string")})
        errors = _validate_output({"summary": "hello"}, manifest)
        assert errors == []

    def test_valid_integer_field(self):
        """Integer field with correct type should pass."""
        manifest = _make_manifest(output_fields={"count": FieldSchema(type="integer")})
        errors = _validate_output({"count": 42}, manifest)
        assert errors == []

    def test_valid_number_field(self):
        """Number field should accept both int and float."""
        manifest = _make_manifest(output_fields={"score": FieldSchema(type="number")})
        assert _validate_output({"score": 3.14}, manifest) == []
        assert _validate_output({"score": 42}, manifest) == []

    def test_valid_boolean_field(self):
        """Boolean field should only accept bool (not int 0/1)."""
        manifest = _make_manifest(output_fields={"active": FieldSchema(type="boolean")})
        assert _validate_output({"active": True}, manifest) == []
        # int is not bool in Python
        errors = _validate_output({"active": 1}, manifest)
        assert len(errors) == 1

    def test_valid_array_field(self):
        """Array field should accept list."""
        manifest = _make_manifest(output_fields={"tags": FieldSchema(type="array")})
        errors = _validate_output({"tags": ["a", "b"]}, manifest)
        assert errors == []

    def test_valid_object_field(self):
        """Object field should accept dict."""
        manifest = _make_manifest(output_fields={"meta": FieldSchema(type="object")})
        errors = _validate_output({"meta": {"key": "val"}}, manifest)
        assert errors == []

    def test_missing_required_field(self):
        """Missing required field should produce error."""
        manifest = _make_manifest(output_fields={
            "summary": FieldSchema(type="string"),
            "count": FieldSchema(type="integer"),
        })
        errors = _validate_output({"summary": "hello"}, manifest)
        assert len(errors) == 1
        assert "count" in errors[0]

    def test_optional_field_can_be_missing(self):
        """Optional field should not produce error when missing."""
        manifest = _make_manifest(output_fields={
            "summary": FieldSchema(type="string"),
            "extra": FieldSchema(type="string", optional=True),
        })
        errors = _validate_output({"summary": "hello"}, manifest)
        assert errors == []

    def test_wrong_type_string(self):
        """Non-string value for string field should error."""
        manifest = _make_manifest(output_fields={"summary": FieldSchema(type="string")})
        errors = _validate_output({"summary": 123}, manifest)
        assert len(errors) == 1
        assert "expected string" in errors[0]

    def test_wrong_type_integer(self):
        """Non-integer value for integer field should error."""
        manifest = _make_manifest(output_fields={"count": FieldSchema(type="integer")})
        errors = _validate_output({"count": "42"}, manifest)
        assert len(errors) == 1
        assert "expected integer" in errors[0]

    def test_wrong_type_array(self):
        """Non-list value for array field should error."""
        manifest = _make_manifest(output_fields={"tags": FieldSchema(type="array")})
        errors = _validate_output({"tags": "not_a_list"}, manifest)
        assert len(errors) == 1
        assert "expected array" in errors[0]

    def test_wrong_type_object(self):
        """Non-dict value for object field should error."""
        manifest = _make_manifest(output_fields={"meta": FieldSchema(type="object")})
        errors = _validate_output({"meta": "not_an_object"}, manifest)
        assert len(errors) == 1
        assert "expected object" in errors[0]

    def test_non_dict_output(self):
        """Non-dict output should produce an immediate error."""
        manifest = _make_manifest(output_fields={"x": FieldSchema(type="string")})
        errors = _validate_output("not a dict", manifest)
        assert len(errors) == 1
        assert "mapping" in errors[0] or "dict" in errors[0]

    def test_multiple_validation_errors(self):
        """Multiple invalid fields should produce multiple errors."""
        manifest = _make_manifest(output_fields={
            "summary": FieldSchema(type="string"),
            "count": FieldSchema(type="integer"),
            "active": FieldSchema(type="boolean"),
        })
        errors = _validate_output(
            {"summary": 123, "count": "not_int", "active": "not_bool"},
            manifest,
        )
        assert len(errors) == 3


# ====================================================================
# 2. Executor — Adapter Management
# ====================================================================

class TestExecutorAdapterManagement:
    """Test Executor adapter registration and listing."""

    def test_init_no_adapters(self):
        """New executor should have no adapters."""
        exe = Executor()
        assert exe.get_available_adapters() == []

    def test_register_adapter(self):
        """Registering an adapter should make it available."""
        exe = Executor()
        adapter = _make_adapter(name="test_adapter")
        exe.register_adapter("test_adapter", adapter)
        assert "test_adapter" in exe.get_available_adapters()

    def test_register_multiple_adapters(self):
        """Multiple adapters should all be registered."""
        exe = Executor()
        exe.register_adapter("a", _make_adapter("a"))
        exe.register_adapter("b", _make_adapter("b"))
        exe.register_adapter("c", _make_adapter("c"))
        assert set(exe.get_available_adapters()) == {"a", "b", "c"}

    def test_register_overwrite(self):
        """Re-registering the same name should overwrite."""
        exe = Executor()
        exe.register_adapter("x", _make_adapter("x"))
        exe.register_adapter("x", _make_adapter("x_v2"))
        assert len(exe.get_available_adapters()) == 1


# ====================================================================
# 3. Executor._select_adapter
# ====================================================================

class TestSelectAdapter:
    """Test the adapter selection logic."""

    def test_select_no_adapters_raises(self):
        """With no adapters registered, selection should raise."""
        exe = Executor()
        manifest = _make_manifest()
        with pytest.raises(AdapterNotFoundError):
            exe._select_adapter(manifest)

    def test_select_with_preferred(self):
        """Selecting a specific adapter should return it."""
        exe = Executor()
        a1 = _make_adapter("adapter_one")
        a2 = _make_adapter("adapter_two")
        exe.register_adapter("adapter_one", a1)
        exe.register_adapter("adapter_two", a2)
        result = exe._select_adapter(None, preferred="adapter_two")
        assert result == a2

    def test_select_preferred_not_found_raises(self):
        """Selecting a non-existent adapter should raise."""
        exe = Executor()
        exe.register_adapter("exists", _make_adapter("exists"))
        with pytest.raises(AdapterNotFoundError) as exc_info:
            exe._select_adapter(None, preferred="nonexistent")
        assert "nonexistent" in str(exc_info.value)

    def test_select_first_available(self):
        """Without preferred, the first registered adapter should be returned."""
        exe = Executor()
        a1 = _make_adapter("first")
        a2 = _make_adapter("second")
        exe.register_adapter("first", a1)
        exe.register_adapter("second", a2)
        result = exe._select_adapter(None, preferred=None)
        assert result == a1


# ====================================================================
# 4. Executor._build_execution_record
# ====================================================================

class TestBuildExecutionRecord:
    """Test the refactored _build_execution_record helper."""

    def test_extracts_adapter_metadata(self):
        """Adapter name, type name, and version should be extracted."""
        exe = Executor()
        recorder = MagicMock()
        manifest = _make_manifest(name="test", version="1.0.0")
        adapter = _make_adapter(name="my_adapter", version="2.0.0")
        fake_record = MagicMock()
        recorder.build_record.return_value = fake_record

        result = exe._build_execution_record(
            recorder, manifest, adapter, adapter_name="ignored",
            input_data={"text": "hello"}, output_data={"summary": "hi"},
            status=ExecutionStatus.SUCCESS, error=None,
        )

        recorder.build_record.assert_called_once_with(
            manifest_name="test",
            manifest_version="1.0.0",
            runtime_id="my_adapter",
            adapter="MagicMock",
            adapter_version="2.0.0",
            input_data={"text": "hello"},
            output_data={"summary": "hi"},
            status=ExecutionStatus.SUCCESS,
            error=None,
        )

    def test_fallback_adapter_name(self):
        """Adapter without 'name' attr should fall back to adapter_name param."""
        exe = Executor()
        recorder = MagicMock()
        manifest = _make_manifest()
        # Object with neither name nor version
        adapter = object()
        exe._build_execution_record(
            recorder, manifest, adapter, adapter_name="openai",
            input_data={}, output_data={},
            status=ExecutionStatus.SUCCESS, error=None,
        )
        call_kwargs = recorder.build_record.call_args[1]
        assert call_kwargs["runtime_id"] == "openai"

    def test_fallback_adapter_version(self):
        """Adapter without 'version' attr should default to '0.1.0'."""
        exe = Executor()
        recorder = MagicMock()
        manifest = _make_manifest()
        # Object with name but no version attribute
        class BareAdapter:
            name = "bare_adapter"
        adapter = BareAdapter()
        exe._build_execution_record(
            recorder, manifest, adapter, adapter_name=None,
            input_data={}, output_data={},
            status=ExecutionStatus.SUCCESS, error=None,
        )
        call_kwargs = recorder.build_record.call_args[1]
        assert call_kwargs["adapter_version"] == "0.1.0"

    def test_error_propagation(self):
        """Error string should be passed through to build_record."""
        exe = Executor()
        recorder = MagicMock()
        manifest = _make_manifest()
        adapter = _make_adapter()
        exe._build_execution_record(
            recorder, manifest, adapter, adapter_name=None,
            input_data={}, output_data=None,
            status=ExecutionStatus.FAILURE, error="Something broke",
        )
        call_kwargs = recorder.build_record.call_args[1]
        assert call_kwargs["status"] == ExecutionStatus.FAILURE
        assert call_kwargs["error"] == "Something broke"
        assert call_kwargs["output_data"] is None


# ====================================================================
# 5. Executor.execute — Success Paths
# ====================================================================

class TestExecuteSuccess:
    """Test successful capability execution paths."""

    def test_successful_execution_returns_record(self):
        """Happy path: execution should return an ExecutionRecord."""
        exe = Executor()
        adapter = _make_adapter(name="mock")
        adapter.execute.return_value = {"summary": "mock summary"}
        exe.register_adapter("mock", adapter)
        manifest = _make_manifest()

        record = exe.execute(manifest, {"text": "hello"})
        assert isinstance(record, ExecutionRecord)
        assert record.status == ExecutionStatus.SUCCESS

    def test_successful_execution_has_output(self):
        """Output should match adapter's returned value (minus internal fields)."""
        exe = Executor()
        adapter = _make_adapter(name="mock")
        adapter.execute.return_value = {"summary": "exact output"}
        exe.register_adapter("mock", adapter)
        manifest = _make_manifest()

        record = exe.execute(manifest, {"text": "test"})
        assert record.output == {"summary": "exact output"}

    def test_execution_strips_internal_fields(self):
        """Internal fields prefixed with _ should be stripped from recorded output."""
        exe = Executor()
        adapter = _make_adapter(name="mock")
        adapter.execute.return_value = {
            "summary": "real output",
            "_token_usage": {"input": 10, "output": 20, "total": 30},
            "_cost": 0.001,
        }
        exe.register_adapter("mock", adapter)
        manifest = _make_manifest()

        record = exe.execute(manifest, {"text": "test"})
        assert record.output == {"summary": "real output"}
        assert "_token_usage" not in record.output
        assert "_cost" not in record.output

    def test_execution_generates_events(self):
        """Execution should generate TaskStarted, CapabilityInvoked, TaskCompleted events."""
        exe = Executor()
        adapter = _make_adapter(name="mock")
        adapter.execute.return_value = {"summary": "output"}
        exe.register_adapter("mock", adapter)
        manifest = _make_manifest()
        recorder = MagicMock()

        record = exe.execute(manifest, {"text": "test"}, recorder=recorder)

        # recorder.record_started should have been called
        assert recorder.record_started.called
        assert recorder.record_invoked.called
        assert recorder.record_completed.called

    def test_execution_uses_custom_trace_id(self):
        """Custom trace_id should be used in the recorder."""
        exe = Executor()
        adapter = _make_adapter(name="mock")
        adapter.execute.return_value = {"summary": "output"}
        exe.register_adapter("mock", adapter)
        manifest = _make_manifest()
        custom_trace = str(uuid.uuid4())

        record = exe.execute(manifest, {"text": "test"}, trace_id=custom_trace)
        assert record.trace_id == custom_trace

    def test_execution_with_specific_adapter(self):
        """Specifying an adapter name should route execution to that adapter."""
        exe = Executor()
        default_adapter = _make_adapter(name="default")
        target_adapter = _make_adapter(name="target")
        exe.register_adapter("default", default_adapter)
        exe.register_adapter("target", target_adapter)
        manifest = _make_manifest()

        record = exe.execute(manifest, {"text": "test"}, adapter_name="target")
        assert record.runtime_id == "target"
        assert target_adapter.execute.called

    def test_output_schema_validation_passes(self):
        """Output matching all schema fields should produce SUCCESS."""
        exe = Executor()
        adapter = _make_adapter(name="mock")
        adapter.execute.return_value = {"summary": "valid", "key_points": ["a", "b"]}
        exe.register_adapter("mock", adapter)
        manifest = _make_manifest(output_fields={
            "summary": FieldSchema(type="string"),
            "key_points": FieldSchema(type="array", optional=True),
        })

        record = exe.execute(manifest, {"text": "test"})
        assert record.status == ExecutionStatus.SUCCESS


# ====================================================================
# 6. Executor.execute — Error Paths
# ====================================================================

class TestExecuteErrors:
    """Test capability execution error handling."""

    def test_no_adapters_raises(self):
        """With no adapters, execute should raise AdapterNotFoundError."""
        exe = Executor()
        manifest = _make_manifest()
        with pytest.raises(AdapterNotFoundError):
            exe.execute(manifest, {"text": "test"})

    def test_adapter_execution_failure(self):
        """When adapter.execute() raises, the record should show FAILURE."""
        exe = Executor()
        adapter = _make_adapter(name="faulty")
        adapter.execute.side_effect = RuntimeError("API failure")
        exe.register_adapter("faulty", adapter)
        manifest = _make_manifest()

        record = exe.execute(manifest, {"text": "test"})
        assert record.status == ExecutionStatus.FAILURE
        assert "API failure" in (record.error or "")

    def test_adapter_execution_failure_records_failed_event(self):
        """Adapter failure should trigger record_failed."""
        exe = Executor()
        adapter = _make_adapter(name="faulty")
        adapter.execute.side_effect = RuntimeError("crash")
        exe.register_adapter("faulty", adapter)
        manifest = _make_manifest()
        recorder = MagicMock()

        exe.execute(manifest, {"text": "test"}, recorder=recorder)
        assert recorder.record_failed.called

    def test_output_validation_failure(self):
        """Output not matching schema should produce FAILURE status."""
        exe = Executor()
        adapter = _make_adapter(name="mock")
        adapter.execute.return_value = {"wrong_field": "should be summary"}
        exe.register_adapter("mock", adapter)
        manifest = _make_manifest(output_fields={"summary": FieldSchema(type="string")})

        record = exe.execute(manifest, {"text": "test"})
        assert record.status == ExecutionStatus.FAILURE
        assert record.error is not None

    def test_output_validation_failure_message(self):
        """Validation errors should be joined into the error message."""
        exe = Executor()
        adapter = _make_adapter(name="mock")
        adapter.execute.return_value = {"summary": 42, "count": "not_int"}
        exe.register_adapter("mock", adapter)
        manifest = _make_manifest(output_fields={
            "summary": FieldSchema(type="string"),
            "count": FieldSchema(type="integer"),
        })

        record = exe.execute(manifest, {"text": "test"})
        assert record.status == ExecutionStatus.FAILURE
        assert "expected string" in (record.error or "")
        assert "expected integer" in (record.error or "")

    def test_unknown_adapter_name_raises(self):
        """Requesting an unregistered adapter should raise AdapterNotFoundError."""
        exe = Executor()
        exe.register_adapter("openai", _make_adapter("openai"))
        manifest = _make_manifest()
        with pytest.raises(AdapterNotFoundError) as exc_info:
            exe.execute(manifest, {"text": "test"}, adapter_name="nonexistent")
        assert "nonexistent" in str(exc_info.value)

    def test_adapter_info_in_failure_record(self):
        """Even on failure, the record should identify which adapter was used."""
        exe = Executor()
        adapter = _make_adapter(name="crashy")
        adapter.execute.side_effect = RuntimeError("fail")
        exe.register_adapter("crashy", adapter)
        manifest = _make_manifest()

        record = exe.execute(manifest, {"text": "test"})
        assert record.adapter == "MagicMock"
        assert record.runtime_id == "crashy"

    def test_non_dict_adapter_output_still_validated(self):
        """Adapter returning non-dict should produce validation error."""
        exe = Executor()
        adapter = _make_adapter(name="mock")
        adapter.execute.return_value = "just a string"
        exe.register_adapter("mock", adapter)
        manifest = _make_manifest()

        record = exe.execute(manifest, {"text": "test"})
        # Non-dict output fails _validate_output → FAILURE status
        assert record.status == ExecutionStatus.FAILURE
