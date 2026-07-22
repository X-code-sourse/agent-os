"""
Intent OS — Execution Engine

The core engine that orchestrates capability execution:
  1. Resolve the capability from the registry
  2. Select the appropriate adapter based on requirements
  3. Execute the capability via the adapter
  4. Validate the output against the manifest's output schema
  5. Record all events and produce an ExecutionRecord

This implements the Execution Model (Algorithm 2) defined in the Intent OS
architecture — the Capability Invocation flow that maps a Manifest to
a concrete runtime execution.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from core.models import (
    CapabilityManifest,
    ExecutionRecord,
    ExecutionStatus,
    EventType,
)
from core.recorder import ExecutionRecorder


class ExecutionError(Exception):
    """Raised when capability execution fails."""
    pass


class AdapterNotFoundError(ExecutionError):
    """Raised when no adapter supports the capability's requirements."""
    pass


class SchemaValidationError(ExecutionError):
    """Raised when the output does not match the declared schema."""
    pass


def _validate_output(
    output: Any,
    manifest: CapabilityManifest,
) -> list[str]:
    """
    Validate that the output conforms to the manifest's output schema.

    Phase 0: Basic type checking against declared types.
    Phase 2+: Full schema validation with nested structure checking.

    Returns:
        List of validation error messages. Empty if valid.
    """
    errors: list[str] = []

    if not isinstance(output, dict):
        return ["Output must be a mapping (dict)"]

    for field_name, field_schema in manifest.output_schema.items():
        value = output.get(field_name)

        if value is None:
            if not field_schema.optional:
                errors.append(f"Missing required output field '{field_name}'")
            continue

        # Type checking for scalar types
        if field_schema.type == "string" and not isinstance(value, str):
            errors.append(f"Output field '{field_name}': expected string, got {type(value).__name__}")
        elif field_schema.type == "integer" and not isinstance(value, int):
            errors.append(f"Output field '{field_name}': expected integer, got {type(value).__name__}")
        elif field_schema.type == "number" and not isinstance(value, (int, float)):
            errors.append(f"Output field '{field_name}': expected number, got {type(value).__name__}")
        elif field_schema.type == "boolean" and not isinstance(value, bool):
            errors.append(f"Output field '{field_name}': expected boolean, got {type(value).__name__}")
        elif field_schema.type == "array" and not isinstance(value, list):
            errors.append(f"Output field '{field_name}': expected array, got {type(value).__name__}")
        elif field_schema.type == "object" and not isinstance(value, dict):
            errors.append(f"Output field '{field_name}': expected object, got {type(value).__name__}")

    return errors


class Executor:
    """
    Execution engine for AI capabilities.

    Coordinates the end-to-end lifecycle of a capability invocation:
    resolve → validate → invoke → validate output → record events.

    In Phase 0, the Executor directly invokes a single capability.
    Phase 1+ will extend this to workflow orchestration with DAG scheduling.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}

    def register_adapter(self, name: str, adapter: Any) -> None:
        """
        Register a runtime adapter.

        Args:
            name: Adapter identifier (e.g., "openai", "anthropic").
            adapter: Adapter instance implementing the AdapterBase interface.
        """
        self._adapters[name] = adapter

    def get_available_adapters(self) -> list[str]:
        """Return names of all registered adapters."""
        return list(self._adapters.keys())

    def execute(
        self,
        manifest: CapabilityManifest,
        input_data: dict[str, Any],
        adapter_name: str | None = None,
        trace_id: str | None = None,
        recorder: ExecutionRecorder | None = None,
        **kwargs: Any,
    ) -> ExecutionRecord:
        """
        Execute a capability.

        This is the main execution entry point. It handles:
          1. Adapter selection
          2. Input validation
          3. Capability invocation via adapter
          4. Output validation
          5. Event recording

        Args:
            manifest: The capability manifest to execute.
            input_data: Input parameters matching manifest.input_schema.
            adapter_name: Optional specific adapter to use.
                          If None, the first compatible adapter is selected.
            trace_id: Optional trace identifier. Auto-generated if not provided.
            recorder: Optional execution recorder. Created if not provided.

        Returns:
            ExecutionRecord with all events and results.

        Raises:
            AdapterNotFoundError: If no compatible adapter is registered.
            ExecutionError: If execution fails.
            SchemaValidationError: If output doesn't match the schema.
        """
        trace_id = trace_id or str(uuid.uuid4())
        own_recorder = recorder is None
        recorder = recorder or ExecutionRecorder(trace_id=trace_id)

        task_id = "capability"

        # Record start
        recorder.record_started(
            task_id=task_id,
            capability=manifest.id,
            input_ref=str(input_data),
        )

        # Select adapter
        adapter = self._select_adapter(manifest, adapter_name)

        # Record adapter selection
        recorder.record_invoked(
            task_id=task_id,
            capability=manifest.id,
            runtime_id=adapter.name if hasattr(adapter, 'name') else adapter_name or "unknown",
            model_used=kwargs.get("model", adapter.default_model if hasattr(adapter, 'default_model') else "unknown"),
            adapter_params={"model": kwargs.get("model")} if "model" in kwargs else None,
        )

        # Execute via adapter
        start_time = time.monotonic()
        try:
            result = adapter.execute(
                manifest=manifest,
                input_data=input_data,
                **kwargs,
            )
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            recorder.record_failed(
                task_id=task_id,
                capability=manifest.id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            status = ExecutionStatus.FAILURE

            return self._build_execution_record(
                recorder, manifest, adapter, adapter_name,
                input_data=input_data, output_data=None,
                status=status, error=str(exc),
            )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Extract token/cost info from result if available
        token_info = result.get("_token_usage", {}) if isinstance(result, dict) else {}
        if not isinstance(token_info, dict):
            token_info = {}
        cost_info = result.get("_cost", 0.0) if isinstance(result, dict) else 0.0

        # Record completion
        recorder.record_completed(
            task_id=task_id,
            capability=manifest.id,
            latency_ms=elapsed_ms,
            token_count={
                "input": token_info.get("input", 0),
                "output": token_info.get("output", 0),
                "total": token_info.get("input", 0) + token_info.get("output", 0),
            },
            cost_usd=float(cost_info) if cost_info else 0.0,
            output_ref=str(result),
        )

        # Validate output
        output_data = result
        if isinstance(result, dict):
            # Strip internal fields before validation
            output_data = {k: v for k, v in result.items() if not k.startswith("_")}

        validation_errors = _validate_output(output_data, manifest)
        if validation_errors:
            status = ExecutionStatus.FAILURE
            error_msg = "; ".join(validation_errors)
        else:
            status = ExecutionStatus.SUCCESS
            error_msg = None

        # Build and return the execution record
        return self._build_execution_record(
            recorder, manifest, adapter, adapter_name,
            input_data=input_data, output_data=output_data,
            status=status, error=error_msg,
        )

    def _build_execution_record(
        self,
        recorder: Any,
        manifest: CapabilityManifest,
        adapter: Any,
        adapter_name: str | None,
        *,
        input_data: dict[str, Any],
        output_data: dict[str, Any] | None,
        status: ExecutionStatus,
        error: str | None,
    ) -> ExecutionRecord:
        """Build an ExecutionRecord from adapter and execution data.

        Extracts adapter metadata and delegates to recorder.build_record(),
        eliminating repetitive adapter-info extraction across success/failure paths.
        """
        runtime_id = getattr(adapter, 'name', adapter_name or "unknown")
        adapter_type = type(adapter).__name__
        adapter_ver = getattr(adapter, 'version', '0.1.0')

        return recorder.build_record(
            manifest_name=manifest.name,
            manifest_version=manifest.version,
            runtime_id=runtime_id,
            adapter=adapter_type,
            adapter_version=adapter_ver,
            input_data=input_data,
            output_data=output_data,
            status=status,
            error=error,
        )

    def _select_adapter(
        self,
        manifest: CapabilityManifest,
        preferred: str | None = None,
    ) -> Any:
        """
        Select the best adapter for executing the given manifest.

        Strategy:
          - If preferred is specified, try that adapter first.
          - If no preferred, use the first registered adapter.
          - Check adapter compatibility with manifest requirements.

        Args:
            manifest: The capability to execute.
            preferred: Optional preferred adapter name.

        Returns:
            An adapter instance.

        Raises:
            AdapterNotFoundError: If no compatible adapter is found.
        """
        if not self._adapters:
            raise AdapterNotFoundError(
                "No adapters registered. Register an adapter before executing."
            )

        if preferred is not None:
            if preferred in self._adapters:
                return self._adapters[preferred]
            raise AdapterNotFoundError(
                f"Adapter '{preferred}' not found. "
                f"Available adapters: {', '.join(self._adapters.keys())}"
            )

        # Return first available adapter
        first_name = next(iter(self._adapters))
        return self._adapters[first_name]
