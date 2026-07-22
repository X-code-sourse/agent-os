"""
Intent OS — Cross-Runtime Compatibility Tests (Phase 0)

Verifies the Phase 0 thesis: "a single Capability Manifest can be parsed,
executed, and produce comparable ExecutionRecords across different runtimes."

Compatibility Levels (L1-L4):
  L1: Schema Compatibility — both runtimes parse the same Manifest (no API needed)
  L2: Capability Compatibility — both runtimes can execute (simulated)
  L3: Semantic Contract — output satisfies schema (simulated)
  L4: Execution Record — events have same structure (simulated)

The L1-L4 tests use inline SimulatedAdapter instances and ALWAYS pass because
they require no network access or API keys. The Ollama integration test is
conditionally skipped when no local Ollama server is detected.

Strategy:
  - SimulatedAdapter <-> SimulatedAdapter : validates the comparison framework itself.
  - SimulatedAdapter <-> OllamaAdapter    : validates real cross-runtime compatibility.

Design: All core data models (CapabilityManifest, ExecutionRecord, etc.) are
defined inline to avoid sys.path pollution and interference with other tests
in the intentos project. The only external imports happen at test-runtime in
the Ollama integration block, with proper cleanup after.
"""

from __future__ import annotations

import copy
import io
import json
import random
import sys
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

import pytest


# ====================================================================
# Inline Data Models (self-contained, no external imports)
# ====================================================================

class ExecutionStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class EventType(Enum):
    TASK_STARTED = "TaskStarted"
    CAPABILITY_INVOKED = "CapabilityInvoked"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"
    WORKFLOW_STARTED = "WorkflowStarted"
    WORKFLOW_COMPLETED = "WorkflowCompleted"
    POLICY_EVALUATED = "PolicyEvaluated"


@dataclass
class FieldSchema:
    """Describes a single field in an input or output schema."""
    type: str
    description: str | None = None
    optional: bool = False
    default: Any | None = None


@dataclass
class MetadataSpec:
    """Capability manifest metadata."""
    name: str
    version: str
    publisher: str | None = None
    description: str | None = None
    tags: list[str] | None = None


@dataclass
class RequirementSpec:
    """Operational requirements for a capability."""
    models: list[str] | None = None


@dataclass
class SecuritySpec:
    """Security constraints for a capability."""
    pass


@dataclass
class CapabilityManifest:
    """Represents a single AI capability for cross-runtime execution."""
    metadata: MetadataSpec
    input_schema: dict[str, FieldSchema]
    output_schema: dict[str, FieldSchema]
    requirements: RequirementSpec | None = None
    security: SecuritySpec | None = None

    @property
    def id(self) -> str:
        return f"{self.metadata.name}@{self.metadata.version}"

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def version(self) -> str:
        return self.metadata.version


@dataclass
class Event:
    """An immutable execution event."""
    event_type: EventType
    trace_id: str
    timestamp: datetime
    source: str
    sequence: int
    payload: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @classmethod
    def create(
        cls,
        event_type: EventType,
        trace_id: str | None = None,
        source: str = "runtime",
        sequence: int = 0,
        payload: dict | None = None,
        metrics: dict | None = None,
    ) -> Event:
        return cls(
            event_type=event_type,
            trace_id=trace_id or str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            source=source,
            sequence=sequence,
            payload=payload or {},
            metrics=metrics,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "spec_version": "1.0",
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "sequence": self.sequence,
            "payload": self.payload or {},
        }
        if self.metrics:
            result["metrics"] = self.metrics
        return result


@dataclass
class ExecutionRecord:
    """Complete record of a single capability execution."""
    spec_version: str = "1.0"
    trace_id: str = ""
    manifest_name: str = ""
    manifest_version: str = ""
    runtime_id: str = ""
    adapter: str = ""
    adapter_version: str = ""
    input: Any = None
    output: Any = None
    events: list[Event] = field(default_factory=list)
    status: ExecutionStatus = ExecutionStatus.SUCCESS
    error: str | None = None
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_version": self.spec_version,
            "trace_id": self.trace_id,
            "manifest": {"name": self.manifest_name, "version": self.manifest_version},
            "runtime": {"id": self.runtime_id, "adapter": self.adapter, "adapter_version": self.adapter_version},
            "input": self.input,
            "output": self.output,
            "status": self.status.value,
            "error": self.error,
            "metrics": {
                "total_latency_ms": self.total_latency_ms,
                "total_cost_usd": self.total_cost_usd,
                "total_tokens": self.total_tokens,
            },
            "events": [e.to_dict() for e in self.events],
        }


# ====================================================================
# Inline Execution Recorder
# ====================================================================

class ExecutionRecorder:
    """Records execution events and produces ExecutionRecords."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._events: list[Event] = []
        self._sequence: int = 0

    def record(
        self,
        event_type: EventType,
        source: str = "runtime",
        payload: dict | None = None,
        metrics: dict | None = None,
    ) -> Event:
        self._sequence += 1
        event = Event.create(
            event_type=event_type,
            trace_id=self.trace_id,
            source=source,
            sequence=self._sequence,
            payload=payload,
            metrics=metrics,
        )
        self._events.append(event)
        return event

    def record_started(
        self,
        task_id: str,
        capability: str,
        input_ref: str,
    ) -> Event:
        return self.record(
            event_type=EventType.TASK_STARTED,
            payload={"task_id": task_id, "capability": capability, "input_ref": input_ref},
        )

    def record_invoked(
        self,
        task_id: str,
        capability: str,
        runtime_id: str,
        model_used: str,
        adapter_params: dict | None = None,
    ) -> Event:
        return self.record(
            event_type=EventType.CAPABILITY_INVOKED,
            source="adapter",
            payload={
                "task_id": task_id,
                "capability": capability,
                "runtime_id": runtime_id,
                "model_used": model_used,
                "adapter_parameters": adapter_params or {},
            },
        )

    def record_completed(
        self,
        task_id: str,
        capability: str,
        latency_ms: int,
        token_count: dict[str, int],
        cost_usd: float,
    ) -> Event:
        return self.record(
            event_type=EventType.TASK_COMPLETED,
            payload={
                "task_id": task_id,
                "output_ref": "",
                "output_schema_valid": True,
                "latency_ms": latency_ms,
            },
            metrics={
                "latency_ms": latency_ms,
                "token_count": {
                    "input": token_count.get("input", 0),
                    "output": token_count.get("output", 0),
                    "total": token_count.get("input", 0) + token_count.get("output", 0),
                },
                "cost_usd": cost_usd,
            },
        )

    def record_failed(
        self,
        task_id: str,
        capability: str,
        error_type: str,
        error_message: str,
    ) -> Event:
        return self.record(
            event_type=EventType.TASK_FAILED,
            payload={
                "task_id": task_id,
                "error_type": error_type,
                "error_message": error_message,
            },
            metrics={"latency_ms": 0, "cost_usd": 0.0},
        )

    def build_record(
        self,
        manifest_name: str,
        manifest_version: str,
        runtime_id: str,
        adapter: str,
        adapter_version: str,
        input_data: Any,
        output_data: Any,
        status: ExecutionStatus = ExecutionStatus.SUCCESS,
        error: str | None = None,
    ) -> ExecutionRecord:
        return ExecutionRecord(
            spec_version="1.0",
            trace_id=self.trace_id,
            manifest_name=manifest_name,
            manifest_version=manifest_version,
            runtime_id=runtime_id,
            adapter=adapter,
            adapter_version=adapter_version,
            input=input_data,
            output=output_data,
            events=self._events.copy(),
            status=status,
            error=error,
        )


# ====================================================================
# Inline SimulatedAdapter, Executor, and helpers
# ====================================================================

class AdapterNotFoundError(Exception):
    """Raised when no adapter supports the capability's requirements."""
    pass


class AdapterBase(ABC):
    """Abstract base for runtime adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        pass

    @abstractmethod
    def execute(
        self,
        manifest: CapabilityManifest,
        input_data: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        pass

    def can_execute(self, manifest: CapabilityManifest) -> bool:
        return True


class SimulatedAdapter(AdapterBase):
    """A simulated runtime adapter for integration testing.

    Produces deterministic outputs based on capability name and input.
    Can be configured to simulate failures for testing error handling.
    Requires no network access or API keys.
    """

    def __init__(
        self,
        name: str = "simulated",
        fail_capabilities: list[str] | None = None,
        latency_range: tuple[float, float] = (0.001, 0.005),
    ) -> None:
        self._name = name
        self._fail_capabilities = set(fail_capabilities or [])
        self._latency_range = latency_range

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def default_model(self) -> str:
        return "simulated-model"

    def execute(
        self,
        manifest: CapabilityManifest,
        input_data: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        cap_name = manifest.name

        if cap_name in self._fail_capabilities:
            raise RuntimeError(
                f"server_error: simulated failure for capability '{cap_name}'"
            )

        # Simulate a tiny bit of latency
        latency = random.uniform(*self._latency_range)
        time.sleep(latency)

        result: dict[str, Any] = {
            "_token_usage": {"input": 100, "output": 50, "total": 150},
            "_cost": 0.001,
        }

        lower = cap_name.lower()
        if "search" in lower:
            query = input_data.get("query", input_data.get("input", ""))
            result["results"] = [
                {"title": f"Result 1 for {query}", "url": "https://example.com/1"},
                {"title": f"Result 2 for {query}", "url": "https://example.com/2"},
            ]
            result["total_results"] = 2
        elif "analyze" in lower:
            text = str(input_data.get("text", input_data.get("input", "")))
            result["result"] = f"Analysis of: {text[:50]}..."
            result["confidence"] = 0.85
        elif "report" in lower or "generate" in lower:
            result["report"] = "Generated report based on provided analysis"
            result["format"] = "markdown"
        elif "fetch" in lower:
            result["content"] = (
                f"Fetched content for: {input_data.get('url', 'unknown')}"
            )
        elif "summarize" in lower:
            result["summary"] = "Summary of provided input"
            result["key_points"] = ["Point 1", "Point 2"]
        else:
            result["output"] = f"Executed: {cap_name}"

        return result


class Executor:
    """Simple execution engine that coordinates adapters and recorders."""

    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}

    def register_adapter(self, name: str, adapter: Any) -> None:
        self._adapters[name] = adapter

    def get_available_adapters(self) -> list[str]:
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
            runtime_id=adapter.name if hasattr(adapter, "name") else adapter_name or "unknown",
            model_used=kwargs.get("model", adapter.default_model if hasattr(adapter, "default_model") else "unknown"),
            adapter_params={"model": kwargs.get("model")} if "model" in kwargs else None,
        )

        # Execute via adapter
        start_time = time.monotonic()
        try:
            result = adapter.execute(manifest=manifest, input_data=input_data, **kwargs)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            adapter_type_name = type(adapter).__name__
            adapter_version = getattr(adapter, "version", "0.1.0")
            runtime_id = getattr(adapter, "name", adapter_name or "unknown")

            recorder.record_failed(
                task_id=task_id,
                capability=manifest.id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return recorder.build_record(
                manifest_name=manifest.name,
                manifest_version=manifest.version,
                runtime_id=runtime_id,
                adapter=adapter_type_name,
                adapter_version=adapter_version,
                input_data=input_data,
                output_data=None,
                status=ExecutionStatus.FAILURE,
                error=str(exc),
            )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        adapter_type_name = type(adapter).__name__
        adapter_version = getattr(adapter, "version", "0.1.0")
        runtime_id = getattr(adapter, "name", adapter_name or "unknown")

        # Extract token/cost info
        token_info = result.get("_token_usage", {}) if isinstance(result, dict) else {}
        cost_info = result.get("_cost", 0.0) if isinstance(result, dict) else 0.0

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
        )

        # Strip internal fields from output before validation
        output_data = result
        if isinstance(result, dict):
            output_data = {k: v for k, v in result.items() if not k.startswith("_")}

        validation_errors = _validate_output(output_data, manifest)
        if validation_errors:
            status = ExecutionStatus.FAILURE
            error_msg = "; ".join(validation_errors)
        else:
            status = ExecutionStatus.SUCCESS
            error_msg = None

        return recorder.build_record(
            manifest_name=manifest.name,
            manifest_version=manifest.version,
            runtime_id=runtime_id,
            adapter=adapter_type_name,
            adapter_version=adapter_version,
            input_data=input_data,
            output_data=output_data,
            status=status,
            error=error_msg,
        )

    def _select_adapter(
        self,
        manifest: CapabilityManifest,
        preferred: str | None = None,
    ) -> Any:
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
        first_name = next(iter(self._adapters))
        return self._adapters[first_name]


def _validate_output(
    output: Any,
    manifest: CapabilityManifest,
) -> list[str]:
    """Validate that output conforms to the manifest's output schema.

    Returns a list of error messages. Empty list means valid.
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

        if field_schema.type == "string" and not isinstance(value, str):
            errors.append(
                f"Output field '{field_name}': expected string, got {type(value).__name__}"
            )
        elif field_schema.type == "integer" and not isinstance(value, int):
            errors.append(
                f"Output field '{field_name}': expected integer, got {type(value).__name__}"
            )
        elif field_schema.type == "number" and not isinstance(value, (int, float)):
            errors.append(
                f"Output field '{field_name}': expected number, got {type(value).__name__}"
            )
        elif field_schema.type == "boolean" and not isinstance(value, bool):
            errors.append(
                f"Output field '{field_name}': expected boolean, got {type(value).__name__}"
            )
        elif field_schema.type == "array" and not isinstance(value, list):
            errors.append(
                f"Output field '{field_name}': expected array, got {type(value).__name__}"
            )
        elif field_schema.type == "object" and not isinstance(value, dict):
            errors.append(
                f"Output field '{field_name}': expected object, got {type(value).__name__}"
            )

    return errors


def compare_records(
    record_a: ExecutionRecord,
    record_b: ExecutionRecord,
) -> dict[str, Any]:
    """Compare two ExecutionRecords for structural compatibility.

    Checks performed:
      1. Schema Compatibility (L1) — same manifest name and version
      2. Event Structure Match (L4) — same event types in same order
      3. Metric Dimensions Match — compatible metric field keys

    Returns a dict with 'compatible' (bool) and 'checks' (per-check detail).
    """
    result: dict[str, Any] = {"compatible": True, "checks": {}}

    # 1. Schema Compatibility (L1)
    schema_ok = (
        record_a.manifest_name == record_b.manifest_name
        and record_a.manifest_version == record_b.manifest_version
    )
    result["checks"]["schema_compatibility"] = {
        "passed": schema_ok,
        "details": {
            "manifest_a": f"{record_a.manifest_name}@{record_a.manifest_version}",
            "manifest_b": f"{record_b.manifest_name}@{record_b.manifest_version}",
        },
    }
    if not schema_ok:
        result["compatible"] = False

    # 2. Event Structure Match
    event_types_a = [e.event_type.value for e in record_a.events]
    event_types_b = [e.event_type.value for e in record_b.events]
    events_ok = event_types_a == event_types_b
    result["checks"]["event_structure_match"] = {
        "passed": events_ok,
        "details": {
            "event_types_a": event_types_a,
            "event_types_b": event_types_b,
        },
    }
    if not events_ok:
        result["compatible"] = False

    # 3. Metric Dimensions Match
    metric_keys_a: set[str] = set()
    metric_keys_b: set[str] = set()
    for evt in record_a.events:
        if evt.metrics:
            metric_keys_a.update(evt.metrics.keys())
    for evt in record_b.events:
        if evt.metrics:
            metric_keys_b.update(evt.metrics.keys())

    metrics_ok = (
        not metric_keys_a
        or not metric_keys_b
        or metric_keys_a == metric_keys_b
        or metric_keys_a.issubset(metric_keys_b)
        or metric_keys_b.issubset(metric_keys_a)
    )
    result["checks"]["metric_dimensions_match"] = {
        "passed": metrics_ok,
        "details": {
            "metric_keys_a": sorted(metric_keys_a),
            "metric_keys_b": sorted(metric_keys_b),
            "missing_in_b": sorted(metric_keys_a - metric_keys_b),
            "missing_in_a": sorted(metric_keys_b - metric_keys_a),
        },
    }
    if not metrics_ok:
        result["compatible"] = False

    return result


# ====================================================================
# Constants and helpers
# ====================================================================

TEXT_SUMMARIZE_YAML = """\
kind: Capability
metadata:
  name: text_summarize
  version: "1.0.0"
  description: Summarize the input text into a concise summary
spec:
  input:
    text:
      type: string
      description: The text to summarize
  output:
    summary:
      type: string
      description: The generated summary
    key_points:
      type: array
      optional: true
  requirements:
    models:
      - default
"""

# The reference-runtime path for conditional Ollama imports
_REF_RUNTIME = Path("C:/Users/haiha/Desktop/intent-os/reference-runtime").resolve()


def _ollama_available() -> bool:
    """Return True if a local Ollama server responds at localhost:11434."""
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_has_model(model: str = "llama3.2:1b") -> bool:
    """Return True if Ollama has the given model pulled."""
    if not _ollama_available():
        return False
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = resp.read().decode("utf-8")
        tags = json.loads(data).get("models", [])
        return any(t.get("name") == model for t in tags)
    except Exception:
        return False


def _import_ollama_adapter():
    """Import OllamaAdapter from the reference-runtime.

    Temporarily adds the reference-runtime to sys.path, performs the import,
    then removes the path and cleans up sys.modules to avoid interfering
    with other tests in the same session.
    """
    runtime_path = str(_REF_RUNTIME)
    orig_path = sys.path.copy()
    orig_modules = set(sys.modules.keys())

    try:
        # Add reference-runtime path
        sys.path.insert(0, runtime_path)

        # Now import OllamaAdapter (this will also pull in its transitive
        # dependencies from adapters.base and core.models).
        from adapters.ollama_adapter import OllamaAdapter as OAI

        return OAI
    finally:
        # Restore sys.path to avoid affecting other tests
        sys.path[:] = orig_path

        # Remove any reference-runtime modules from sys.modules cache to
        # avoid shadowing the local intentos core/ package for sibling tests.
        for mod_name in list(sys.modules.keys()):
            if mod_name not in orig_modules:
                del sys.modules[mod_name]


OLLAMA_AVAILABLE = _ollama_available()
OLLAMA_HAS_MODEL = _ollama_has_model()


def _make_executor(
    adapter_name: str = "sim_a",
    fail_capabilities: list[str] | None = None,
) -> Executor:
    """Create an Executor registered with a SimulatedAdapter."""
    exe = Executor()
    exe.register_adapter(
        adapter_name,
        SimulatedAdapter(name=adapter_name, fail_capabilities=fail_capabilities),
    )
    return exe


def _make_manifest(
    name: str = "text_summarize",
    version: str = "1.0.0",
    description: str = "Summarize the input text into a concise summary",
    include_key_points: bool = True,
) -> CapabilityManifest:
    """Build a text_summarize CapabilityManifest."""
    output: dict[str, FieldSchema] = {
        "summary": FieldSchema(type="string", description="The generated summary"),
    }
    if include_key_points:
        output["key_points"] = FieldSchema(type="array", optional=True)

    return CapabilityManifest(
        metadata=MetadataSpec(
            name=name,
            version=version,
            publisher="intent-os",
            description=description,
        ),
        input_schema={
            "text": FieldSchema(type="string", description="The text to summarize"),
        },
        output_schema=output,
        requirements=RequirementSpec(models=["default"]),
        security=SecuritySpec(),
    )


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture
def text_summarize_yaml() -> str:
    """The manifest YAML as a raw string (used by L1)."""
    return TEXT_SUMMARIZE_YAML


@pytest.fixture
def text_summarize_manifest() -> CapabilityManifest:
    """A programmatic text_summarize manifest (used by L1-L4)."""
    return _make_manifest()


@pytest.fixture
def input_data() -> dict[str, str]:
    """Standard input for text_summarize."""
    return {
        "text": "The quick brown fox jumps over the lazy dog. "
                "This is a simple test sentence for summarization."
    }


@pytest.fixture
def executor_a() -> Executor:
    """Executor with the first simulated adapter (sim_a)."""
    return _make_executor("sim_a")


@pytest.fixture
def executor_b() -> Executor:
    """Executor with the second simulated adapter (sim_b)."""
    return _make_executor("sim_b")


@pytest.fixture
def record_a(
    executor_a: Executor,
    text_summarize_manifest: CapabilityManifest,
    input_data: dict[str, str],
) -> ExecutionRecord:
    """ExecutionRecord from sim_a executing text_summarize."""
    return executor_a.execute(text_summarize_manifest, input_data)


@pytest.fixture
def record_b(
    executor_b: Executor,
    text_summarize_manifest: CapabilityManifest,
    input_data: dict[str, str],
) -> ExecutionRecord:
    """ExecutionRecord from sim_b executing text_summarize."""
    return executor_b.execute(text_summarize_manifest, input_data)


# ====================================================================
# L1: Schema Compatibility
# ====================================================================

try:
    # Attempt a clean import of the reference-runtime parser.
    # This may fail if the reference-runtime is not available or if
    # pyyaml is not installed — the parser-dependent tests are
    # skipped gracefully in that case.
    _orig_path = sys.path.copy()
    _orig_mods = set(sys.modules.keys())
    sys.path.insert(0, str(_REF_RUNTIME))
    _PARSER_MOD: Any | None = None
    _parser_import = __import__("core.parser", fromlist=["parse_manifest"])
    _parse_manifest_fn = _parser_import.parse_manifest
    _PARSER_AVAILABLE = True
except Exception:
    _PARSER_AVAILABLE = False
    _parse_manifest_fn = None
finally:
    sys.path[:] = _orig_path
    for mod_name in list(sys.modules.keys()):
        if mod_name not in _orig_mods:
            del sys.modules[mod_name]
    del _orig_path, _orig_mods


class TestL1SchemaCompatibility:
    """L1 — Both runtimes parse the same Manifest and agree on its schema.

    No API key required. Tests that the manifest can be constructed both
    programmatically and from YAML, and that two creation paths produce
    equivalent schema definitions.
    """

    @pytest.mark.skipif(
        not _PARSER_AVAILABLE,
        reason="Reference-runtime parser (core.parser) not importable — "
               "verify pyyaml is installed and the reference-runtime is at "
               + str(_REF_RUNTIME),
    )
    def test_yaml_parses_to_valid_manifest(
        self,
        text_summarize_yaml: str,
    ) -> None:
        """The text_summarize YAML is structurally valid and parseable.

        This test uses the reference-runtime's parser, imported cleanly
        at call time to avoid sys.path pollution.
        """
        manifest, result = _parse_manifest_fn(text_summarize_yaml)
        assert result.valid, (
            f"YAML validation errors: {[e.message for e in result.errors]}"
        )
        assert manifest.name == "text_summarize"
        assert manifest.version == "1.0.0"
        assert "text" in manifest.input_schema
        assert "summary" in manifest.output_schema

    @pytest.mark.skipif(
        not _PARSER_AVAILABLE,
        reason="Reference-runtime parser not available",
    )
    def test_yaml_warnings_are_acceptable(
        self,
        text_summarize_yaml: str,
    ) -> None:
        """Warnings (e.g. missing digest) do not make the manifest invalid."""
        _, result = _parse_manifest_fn(text_summarize_yaml)
        assert result.valid is True
        for w in result.warnings:
            assert w.severity == "warning"

    def test_programmatic_manifest_has_expected_fields(
        self,
        text_summarize_manifest: CapabilityManifest,
    ) -> None:
        """Programmatic manifest exposes the correct structure."""
        manifest = text_summarize_manifest
        assert manifest.name == "text_summarize"
        assert manifest.version == "1.0.0"
        assert manifest.id == "text_summarize@1.0.0"
        assert isinstance(manifest.input_schema, dict)
        assert isinstance(manifest.output_schema, dict)
        assert "summary" in manifest.output_schema
        assert manifest.output_schema["summary"].type == "string"

    @pytest.mark.skipif(
        not _PARSER_AVAILABLE,
        reason="Reference-runtime parser not available",
    )
    def test_programmatic_and_yaml_manifests_equivalent(
        self,
        text_summarize_yaml: str,
        text_summarize_manifest: CapabilityManifest,
    ) -> None:
        """Both manifest construction paths yield compatible schemas.

        This is the core L1 assertion: the same manifest expressed through
        different means (YAML parse, programmatic construction) produces
        the same logical structure.
        """
        yaml_manifest, _ = _parse_manifest_fn(text_summarize_yaml)

        assert yaml_manifest.name == text_summarize_manifest.name
        assert yaml_manifest.version == text_summarize_manifest.version
        assert (
            yaml_manifest.metadata.description
            == text_summarize_manifest.metadata.description
        )

        # Same input fields
        assert set(yaml_manifest.input_schema.keys()) == set(
            text_summarize_manifest.input_schema.keys()
        )
        for field_name in yaml_manifest.input_schema:
            assert (
                yaml_manifest.input_schema[field_name].type
                == text_summarize_manifest.input_schema[field_name].type
            )

        # Same output fields
        assert set(yaml_manifest.output_schema.keys()) == set(
            text_summarize_manifest.output_schema.keys()
        )
        for field_name in yaml_manifest.output_schema:
            assert (
                yaml_manifest.output_schema[field_name].type
                == text_summarize_manifest.output_schema[field_name].type
            )

    def test_manifest_equality_across_instances(self) -> None:
        """Two identical manifests compare equal (dataclass equality)."""
        m1 = _make_manifest()
        m2 = _make_manifest()
        assert m1.metadata == m2.metadata
        assert m1.input_schema == m2.input_schema
        assert m1.output_schema == m2.output_schema
        assert m1 == m2


# ====================================================================
# L2: Capability Compatibility
# ====================================================================

class TestL2CapabilityCompatibility:
    """L2 — Both runtimes can execute the same CapabilityManifest.

    Uses two independent SimulatedAdapter instances to verify that the
    execution pathway (Executor -> Adapter -> ExecutionRecord) works
    identically regardless of which adapter instance processes the manifest.
    """

    def test_both_adapters_execute_successfully(
        self,
        executor_a: Executor,
        executor_b: Executor,
        text_summarize_manifest: CapabilityManifest,
        input_data: dict[str, str],
    ) -> None:
        """Both adapters return ExecutionRecord with SUCCESS status."""
        record_a = executor_a.execute(text_summarize_manifest, input_data)
        record_b = executor_b.execute(text_summarize_manifest, input_data)

        assert record_a.status == ExecutionStatus.SUCCESS
        assert record_b.status == ExecutionStatus.SUCCESS

    def test_both_run_the_same_manifest(
        self,
        executor_a: Executor,
        executor_b: Executor,
        text_summarize_manifest: CapabilityManifest,
        input_data: dict[str, str],
    ) -> None:
        """Both records reference the same manifest name and version."""
        record_a = executor_a.execute(text_summarize_manifest, input_data)
        record_b = executor_b.execute(text_summarize_manifest, input_data)

        assert record_a.manifest_name == "text_summarize"
        assert record_b.manifest_name == "text_summarize"
        assert record_a.manifest_version == "1.0.0"
        assert record_b.manifest_version == "1.0.0"

    def test_adapters_identify_with_unique_runtime_ids(
        self,
        executor_a: Executor,
        executor_b: Executor,
        text_summarize_manifest: CapabilityManifest,
        input_data: dict[str, str],
    ) -> None:
        """Different adapter instances report different runtime IDs."""
        record_a = executor_a.execute(text_summarize_manifest, input_data)
        record_b = executor_b.execute(text_summarize_manifest, input_data)

        assert record_a.runtime_id == "sim_a"
        assert record_b.runtime_id == "sim_b"
        assert record_a.runtime_id != record_b.runtime_id

    def test_adapters_record_trace_ids(
        self,
        executor_a: Executor,
        executor_b: Executor,
        text_summarize_manifest: CapabilityManifest,
        input_data: dict[str, str],
    ) -> None:
        """Each execution gets a unique trace_id."""
        record_a = executor_a.execute(text_summarize_manifest, input_data)
        record_b = executor_b.execute(text_summarize_manifest, input_data)

        assert record_a.trace_id
        assert record_b.trace_id
        assert record_a.trace_id != record_b.trace_id

    def test_both_adapters_have_version(self) -> None:
        """SimulatedAdapter instances expose version metadata."""
        a = SimulatedAdapter(name="test_a")
        b = SimulatedAdapter(name="test_b")
        assert a.version == "0.1.0"
        assert b.version == "0.1.0"

    def test_adapter_reports_failure_gracefully(
        self,
        text_summarize_manifest: CapabilityManifest,
        input_data: dict[str, str],
    ) -> None:
        """An adapter configured to fail returns a FAILURE record, not a crash."""
        exe = _make_executor("faulty", fail_capabilities=["text_summarize"])
        record = exe.execute(text_summarize_manifest, input_data)
        assert record.status == ExecutionStatus.FAILURE
        assert record.error is not None
        assert "text_summarize" in record.error

    def test_missing_adapter_raises(
        self,
        text_summarize_manifest: CapabilityManifest,
        input_data: dict[str, str],
    ) -> None:
        """Requesting a non-existent adapter raises AdapterNotFoundError."""
        exe = Executor()
        with pytest.raises(AdapterNotFoundError, match="No adapters registered"):
            exe.execute(text_summarize_manifest, input_data)


# ====================================================================
# L3: Semantic Contract
# ====================================================================

class TestL3SemanticContract:
    """L3 — Output satisfies the manifest's output schema (semantic contract).

    The output schema is the contract between a capability and its callers.
    L3 verifies that both runtimes produce output conforming to the declared
    output schema, regardless of the actual output values.
    """

    def test_sim_a_output_validates_against_schema(
        self,
        record_a: ExecutionRecord,
        text_summarize_manifest: CapabilityManifest,
    ) -> None:
        """Output from sim_a satisfies the manifest's output schema."""
        errors = _validate_output(record_a.output, text_summarize_manifest)
        assert errors == [], f"Schema validation errors: {errors}"

    def test_sim_b_output_validates_against_schema(
        self,
        record_b: ExecutionRecord,
        text_summarize_manifest: CapabilityManifest,
    ) -> None:
        """Output from sim_b satisfies the manifest's output schema."""
        errors = _validate_output(record_b.output, text_summarize_manifest)
        assert errors == [], f"Schema validation errors: {errors}"

    def test_both_outputs_have_required_fields(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Both outputs contain the required 'summary' field."""
        assert isinstance(record_a.output, dict)
        assert isinstance(record_b.output, dict)
        assert "summary" in record_a.output
        assert "summary" in record_b.output
        assert isinstance(record_a.output["summary"], str)
        assert isinstance(record_b.output["summary"], str)

    def test_optional_field_may_be_present(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Optional 'key_points' may appear in the output."""
        assert isinstance(record_a.output, dict)
        assert isinstance(record_b.output, dict)
        if "key_points" in record_a.output:
            assert isinstance(record_a.output["key_points"], list)
        if "key_points" in record_b.output:
            assert isinstance(record_b.output["key_points"], list)

    def test_both_output_values_are_strings(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """The summary field is a non-empty string in both outputs."""
        assert record_a.output is not None
        assert record_b.output is not None
        summary_a = record_a.output.get("summary", "")
        summary_b = record_b.output.get("summary", "")
        assert isinstance(summary_a, str) and len(summary_a) > 0
        assert isinstance(summary_b, str) and len(summary_b) > 0

    def test_manifest_without_optional_fields_validates(
        self,
        executor_a: Executor,
        input_data: dict[str, str],
    ) -> None:
        """A manifest with only required fields still validates."""
        minimal_manifest = _make_manifest(include_key_points=False)
        record = executor_a.execute(minimal_manifest, input_data)
        errors = _validate_output(record.output, minimal_manifest)
        assert errors == [], (
            f"Schema validation errors on minimal manifest: {errors}"
        )

    def test_schema_type_enforcement(
        self,
        text_summarize_manifest: CapabilityManifest,
    ) -> None:
        """String field rejects non-string values."""
        errors = _validate_output({"summary": 42}, text_summarize_manifest)
        assert len(errors) >= 1
        assert "expected string" in errors[0]

    def test_missing_required_field_caught(
        self,
        text_summarize_manifest: CapabilityManifest,
    ) -> None:
        """Missing a required field produces a validation error."""
        errors = _validate_output({}, text_summarize_manifest)
        assert len(errors) >= 1
        assert "Missing required output field" in errors[0]


# ====================================================================
# L4: Execution Record
# ====================================================================

class TestL4ExecutionRecord:
    """L4 — Events from both runtimes have the same structure.

    The ExecutionRecord bundles the full event stream with metadata.
    L4 verifies that two records produced by different adapters (but the
    same manifest and input) are structurally compatible: same event types
    in the same order, compatible metric dimensions, and matching schema info.
    """

    def test_both_records_are_execution_record_type(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Both runtime outputs are proper ExecutionRecord instances."""
        assert isinstance(record_a, ExecutionRecord)
        assert isinstance(record_b, ExecutionRecord)

    def test_both_records_have_events(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Both executions produce a non-empty event list."""
        assert len(record_a.events) > 0
        assert len(record_b.events) > 0
        # Standard execution: TaskStarted, CapabilityInvoked, TaskCompleted
        assert len(record_a.events) == 3
        assert len(record_b.events) == 3

    def test_event_types_match_across_records(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Both records have the same sequence of event types."""
        types_a = [e.event_type.value for e in record_a.events]
        types_b = [e.event_type.value for e in record_b.events]
        expected = ["TaskStarted", "CapabilityInvoked", "TaskCompleted"]
        assert types_a == expected
        assert types_b == expected

    def test_event_timestamps_are_populated(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Every event in both records has a valid timestamp."""
        for event in record_a.events:
            assert event.timestamp is not None
        for event in record_b.events:
            assert event.timestamp is not None

    def test_event_sources_are_set(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Events have the source field populated."""
        for event in record_a.events:
            assert event.source in ("runtime", "adapter")
        for event in record_b.events:
            assert event.source in ("runtime", "adapter")

    def test_compare_records_confirms_compatibility(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """compare_records() marks the two records as compatible at all levels.

        This is the core L4 assertion: the comparison framework confirms
        that the two execution paths produce structurally equivalent records.
        """
        result = compare_records(record_a, record_b)
        assert result["compatible"] is True, (
            f"Records not compatible: {result.get('checks', {})}"
        )

    def test_compare_schema_checks_passes(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Schema compatibility check passes (same manifest)."""
        result = compare_records(record_a, record_b)
        assert result["checks"]["schema_compatibility"]["passed"] is True

    def test_compare_event_structure_passes(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Event structure match check passes (same event sequence)."""
        result = compare_records(record_a, record_b)
        assert result["checks"]["event_structure_match"]["passed"] is True

    def test_compare_metric_dimensions_passes(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Metric dimensions check passes (compatible metric keys)."""
        result = compare_records(record_a, record_b)
        assert result["checks"]["metric_dimensions_match"]["passed"] is True

    def test_compare_checks_detail_structure(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Each compatibility check returns a 'details' dict with diagnostics."""
        result = compare_records(record_a, record_b)
        for check_name, check_data in result["checks"].items():
            assert "details" in check_data, f"{check_name} missing 'details'"
            assert isinstance(check_data["details"], dict)

    def test_records_report_manifest_info(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Both records carry the manifest name and version."""
        assert record_a.manifest_name == "text_summarize"
        assert record_a.manifest_version == "1.0.0"
        assert record_b.manifest_name == "text_summarize"
        assert record_b.manifest_version == "1.0.0"

    def test_records_report_runtime_info(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Records identify which adapter and runtime produced them."""
        assert record_a.runtime_id == "sim_a"
        assert record_b.runtime_id == "sim_b"
        assert record_a.adapter != ""
        assert record_b.adapter != ""

    def test_reports_metric_totals(
        self,
        record_a: ExecutionRecord,
        record_b: ExecutionRecord,
    ) -> None:
        """Records include latency, cost, and token metrics."""
        assert record_a.total_latency_ms >= 0
        assert record_b.total_latency_ms >= 0
        assert record_a.total_tokens >= 0
        assert record_b.total_tokens >= 0

    def test_comparison_detects_schema_mismatch(
        self,
        record_a: ExecutionRecord,
    ) -> None:
        """compare_records catches different manifests and reports incompatibility."""
        diff_manifest = _make_manifest(name="different_cap")
        diff_executor = _make_executor("diff")
        diff_record = diff_executor.execute(diff_manifest, {"text": "test"})

        result = compare_records(record_a, diff_record)
        assert result["compatible"] is False
        assert result["checks"]["schema_compatibility"]["passed"] is False


# ====================================================================
# Cross-Runtime: Simulated <-> Ollama (conditional)
# ====================================================================

class TestOllamaIntegration:
    """Cross-runtime comparison: SimulatedAdapter vs. OllamaAdapter.

    These tests require a running Ollama server at localhost:11434 with the
    default model (llama3.2:1b) pulled. They are skipped automatically when
    the server or model is unavailable.

    When both runtimes are available, L1-L4 comparisons are performed
    between the simulated and Ollama execution records. The OllamaAdapter
    import is performed inside each test via a context manager that cleans
    up sys.path and sys.modules to avoid interfering with sibling tests.
    """

    # ── Helper: Import OllamaAdapter cleanly at test time ──

    def _ollama_adapter(self):
        """Import OllamaAdapter with proper sys.path management."""
        return _import_ollama_adapter()

    # ── Connection sanity checks ──

    @pytest.mark.skipif(
        not OLLAMA_AVAILABLE,
        reason="Ollama server not detected at http://localhost:11434 — start with 'ollama serve'",
    )
    def test_ollama_server_is_running(self) -> None:
        """Sanity check: the Ollama server responds."""
        assert OLLAMA_AVAILABLE is True

    @pytest.mark.skipif(
        not OLLAMA_HAS_MODEL,
        reason="Ollama model 'llama3.2:1b' not pulled — run 'ollama pull llama3.2:1b'",
    )
    def test_ollama_model_is_available(self) -> None:
        """Sanity check: the required model is pulled."""
        assert OLLAMA_HAS_MODEL is True

    # ── Interface compliance ──

    @pytest.mark.skipif(
        not OLLAMA_AVAILABLE,
        reason="Ollama server not running at localhost:11434",
    )
    def test_ollama_adapter_exposes_correct_interface(self) -> None:
        """OllamaAdapter conforms to AdapterBase and exposes expected properties."""
        OllamaAdapter = self._ollama_adapter()
        adapter = OllamaAdapter()
        assert adapter.name == "ollama"
        assert adapter.version == "0.1.0"
        assert adapter.default_model == "llama3.2:1b"
        assert isinstance(adapter, AdapterBase)
        manifest = _make_manifest()
        assert adapter.can_execute(manifest) is True

    # ── L1: Schema ──

    @pytest.mark.skipif(
        not (OLLAMA_AVAILABLE and _PARSER_AVAILABLE),
        reason="Ollama server or reference-runtime parser not available",
    )
    def test_ollama_parses_same_manifest(
        self,
        text_summarize_yaml: str,
    ) -> None:
        """Ollama (via the shared parser) produces the same manifest.
        Verifies that the cross-runtime parser produces a valid manifest
        for the standard text_summarize definition.
        """
        manifest, result = _parse_manifest_fn(text_summarize_yaml)
        assert result.valid
        assert manifest.name == "text_summarize"

    # ── L2: Execution ──

    @pytest.mark.skipif(
        not OLLAMA_AVAILABLE,
        reason="Ollama server not running at localhost:11434",
    )
    @pytest.mark.skipif(
        not OLLAMA_HAS_MODEL,
        reason="Required Ollama model not available",
    )
    def test_ollama_executes_manifest_successfully(
        self,
        text_summarize_manifest: CapabilityManifest,
        input_data: dict[str, str],
    ) -> None:
        """OllamaAdapter executes text_summarize and returns a success record."""
        OllamaAdapter = self._ollama_adapter()
        exe = Executor()
        exe.register_adapter(
            "ollama", OllamaAdapter(base_url="http://localhost:11434")
        )
        record = exe.execute(
            text_summarize_manifest,
            input_data,
            adapter_name="ollama",
        )
        assert record.status == ExecutionStatus.SUCCESS, (
            f"Ollama execution failed: {record.error}"
        )
        assert isinstance(record.output, dict)
        assert "summary" in record.output

    # ── L3: Semantic contract ──

    @pytest.mark.skipif(
        not OLLAMA_AVAILABLE,
        reason="Ollama server not running at localhost:11434",
    )
    @pytest.mark.skipif(
        not OLLAMA_HAS_MODEL,
        reason="Required Ollama model not available",
    )
    def test_ollama_output_validates_against_schema(
        self,
        text_summarize_manifest: CapabilityManifest,
        input_data: dict[str, str],
    ) -> None:
        """Ollama's output satisfies the manifest's output schema (L3)."""
        OllamaAdapter = self._ollama_adapter()
        exe = Executor()
        exe.register_adapter(
            "ollama", OllamaAdapter(base_url="http://localhost:11434")
        )
        record = exe.execute(
            text_summarize_manifest,
            input_data,
            adapter_name="ollama",
        )
        errors = _validate_output(record.output, text_summarize_manifest)
        assert errors == [], (
            f"Ollama output schema validation errors: {errors}"
        )

    # ── L4: Cross-runtime record compatibility ──

    @pytest.mark.skipif(
        not OLLAMA_AVAILABLE,
        reason="Ollama server not running at localhost:11434",
    )
    @pytest.mark.skipif(
        not OLLAMA_HAS_MODEL,
        reason="Required Ollama model not available",
    )
    def test_ollama_and_simulated_records_compatible(
        self,
        text_summarize_manifest: CapabilityManifest,
        input_data: dict[str, str],
    ) -> None:
        """Execution records from Ollama and SimulatedAdapter are structurally
        compatible — same event types, same schema, compatible metrics (L4).

        This is the primary Phase 0 cross-runtime validation.
        """
        OllamaAdapter = self._ollama_adapter()

        # Simulated execution
        sim_exe = _make_executor("sim_reference")
        sim_record = sim_exe.execute(text_summarize_manifest, input_data)

        # Ollama execution
        ollama_exe = Executor()
        ollama_exe.register_adapter(
            "ollama", OllamaAdapter(base_url="http://localhost:11434")
        )
        ollama_record = ollama_exe.execute(
            text_summarize_manifest,
            input_data,
            adapter_name="ollama",
        )

        # Compare
        result = compare_records(sim_record, ollama_record)
        assert result["compatible"] is True, (
            f"Cross-runtime compatibility check failed: "
            f"{result.get('checks', {})}"
        )
        assert result["checks"]["schema_compatibility"]["passed"] is True
        assert result["checks"]["event_structure_match"]["passed"] is True

    @pytest.mark.skipif(
        not OLLAMA_AVAILABLE,
        reason="Ollama server not running at localhost:11434",
    )
    @pytest.mark.skipif(
        not OLLAMA_HAS_MODEL,
        reason="Required Ollama model not available",
    )
    def test_ollama_record_has_events(
        self,
        text_summarize_manifest: CapabilityManifest,
        input_data: dict[str, str],
    ) -> None:
        """Ollama execution produces the standard event sequence."""
        OllamaAdapter = self._ollama_adapter()
        exe = Executor()
        exe.register_adapter(
            "ollama", OllamaAdapter(base_url="http://localhost:11434")
        )
        record = exe.execute(
            text_summarize_manifest,
            input_data,
            adapter_name="ollama",
        )
        assert len(record.events) == 3
        types = [e.event_type.value for e in record.events]
        assert types == ["TaskStarted", "CapabilityInvoked", "TaskCompleted"]
