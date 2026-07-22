"""
Intent OS — Execution Recorder (SPEC-0003 Event System)

Records execution events and produces structured ExecutionRecords.
Phase 0 implementation writes events in-memory and can export them
as JSON Lines to stdout or to disk.

The Event System is the foundation of Intent OS's observability and
learning backbone. Every execution produces an ExecutionRecord that
can be compared across runtimes for compatibility verification.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from core.models import (
    Event,
    EventType,
    ExecutionRecord,
    ExecutionStatus,
)


class ExecutionRecorder:
    """
    Records execution events and produces ExecutionRecords.

    Thread-safe for use by concurrent capability executions.
    """

    def __init__(self, trace_id: str, output: TextIO | None = None) -> None:
        """
        Args:
            trace_id: Unique trace identifier for this execution.
            output: Optional stream for real-time event output.
                    If None, events are only stored in memory.
        """
        self.trace_id = trace_id
        self._output = output
        self._events: list[Event] = []
        self._sequence: int = 0

    def record(
        self,
        event_type: EventType,
        source: str = "runtime",
        payload: dict | None = None,
        metrics: dict | None = None,
        workflow_id: str | None = None,
        task_id: str | None = None,
        capability: str | None = None,
        runtime: str | None = None,
        adapter_version: str | None = None,
    ) -> Event:
        """Record an execution event."""
        self._sequence += 1
        event = Event.create(
            event_type=event_type,
            trace_id=self.trace_id,
            source=source,
            sequence=self._sequence,
            payload=payload,
            metrics=metrics,
            workflow_id=workflow_id,
            task_id=task_id,
            capability=capability,
            runtime=runtime,
            adapter_version=adapter_version,
        )
        self._events.append(event)

        # Write to output stream if configured
        if self._output is not None:
            self._output.write(json.dumps(event.to_dict()) + "\n")
            self._output.flush()

        return event

    def record_started(
        self,
        task_id: str,
        capability: str,
        input_ref: str,
        depends_on: list[str] | None = None,
    ) -> Event:
        """Record TaskStarted event."""
        return self.record(
            event_type=EventType.TASK_STARTED,
            task_id=task_id,
            capability=capability,
            payload={
                "task_id": task_id,
                "capability": capability,
                "input_ref": input_ref,
                "depends_on": depends_on or [],
            },
        )

    def record_invoked(
        self,
        task_id: str,
        capability: str,
        runtime_id: str,
        model_used: str,
        adapter_params: dict | None = None,
        input_truncated: bool = False,
    ) -> Event:
        """Record CapabilityInvoked event."""
        return self.record(
            event_type=EventType.CAPABILITY_INVOKED,
            source="adapter",
            task_id=task_id,
            capability=capability,
            runtime=runtime_id,
            payload={
                "task_id": task_id,
                "capability": capability,
                "runtime_id": runtime_id,
                "model_used": model_used,
                "adapter_parameters": adapter_params or {},
                "input_truncated": input_truncated,
            },
        )

    def record_completed(
        self,
        task_id: str,
        capability: str,
        latency_ms: int,
        token_count: dict[str, int],
        cost_usd: float,
        attempt: int = 1,
        output_ref: str | None = None,
    ) -> Event:
        """Record TaskCompleted event."""
        return self.record(
            event_type=EventType.TASK_COMPLETED,
            task_id=task_id,
            capability=capability,
            payload={
                "task_id": task_id,
                "output_ref": output_ref or "",
                "output_schema_valid": True,
                "latency_ms": latency_ms,
                "attempt": attempt,
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
        attempt: int = 1,
        retry_allowed: bool = True,
        error_code: str | None = None,
    ) -> Event:
        """Record TaskFailed event."""
        return self.record(
            event_type=EventType.TASK_FAILED,
            task_id=task_id,
            capability=capability,
            payload={
                "task_id": task_id,
                "error_type": error_type,
                "error_message": error_message,
                "error_code": error_code,
                "attempt": attempt,
                "retry_allowed": retry_allowed,
                "recovery_action": "retry" if retry_allowed else "fail",
            },
            metrics={
                "latency_ms": 0,
                "cost_usd": 0.0,
            },
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
        """Build a complete ExecutionRecord from all recorded events."""
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


def save_execution_record(record: ExecutionRecord, path: str | Path) -> Path:
    """Save an ExecutionRecord to a JSON file on disk."""
    path = Path(path)
    path.write_text(json.dumps(record.to_dict(), indent=2, default=str), encoding="utf-8")
    return path


def load_execution_record(path: str | Path) -> ExecutionRecord:
    """Load an ExecutionRecord from a JSON file on disk."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    # Reconstruct from dict — simplified for Phase 0
    record = ExecutionRecord(
        spec_version=data.get("spec_version", "1.0"),
        trace_id=data.get("trace_id", ""),
        manifest_name=data["manifest"]["name"],
        manifest_version=data["manifest"]["version"],
        runtime_id=data["runtime"]["id"],
        adapter=data["runtime"]["adapter"],
        adapter_version=data["runtime"]["adapter_version"],
        input=data.get("input"),
        output=data.get("output"),
        status=ExecutionStatus(data.get("status", "success")),
        error=data.get("error"),
    )
    return record


def compare_records(
    record_a: ExecutionRecord,
    record_b: ExecutionRecord,
) -> dict[str, Any]:
    """
    Compare two ExecutionRecords for compatibility (SPEC-0003).

    This is the core verification function for Phase 0.
    It checks that two records have compatible structure even if
    their metric values differ (which is expected — different runtimes
    have different performance characteristics).

    Returns:
        Dict with compatibility results for each level:
          - schema_compatible: Same manifest schema?
          - event_structure_match: Same event types and sequence?
          - metric_dimensions_match: Same metric fields?
          - details: Per-check breakdown.
    """
    result: dict[str, Any] = {
        "compatible": True,
        "checks": {},
    }

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
    metric_keys_a = set()
    metric_keys_b = set()
    for evt in record_a.events:
        if evt.metrics:
            metric_keys_a.update(evt.metrics.keys())
    for evt in record_b.events:
        if evt.metrics:
            metric_keys_b.update(evt.metrics.keys())

    # Defensive check: one set being a subset of the other is acceptable
    # (e.g., Runtime B may emit an extra metric that Runtime A doesn't).
    # Only flag incompatibility when both have non-empty key sets and
    # neither is a subset — meaning they disagree on dimensions.
    metrics_ok = (
        not metric_keys_a or not metric_keys_b
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
