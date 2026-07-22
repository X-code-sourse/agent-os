"""
Intent OS — Workflow YAML Parser (SPEC-0002)

Formal parser for Workflow YAML files. Validates structure, required fields,
variable references, and produces a validated WorkflowSpec.

This replaces the ad-hoc yaml.safe_load() calls in cli.py with proper validation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from core.workflow import (
    ExecutionSemantics,
    FailurePolicy,
    FailurePropagation,
    MergeStrategy,
    ParallelPolicy,
    ParallelStrategy,
    RetryPolicy,
    RetryStrategy,
    TimeoutPolicy,
    WorkflowEdge,
    WorkflowSpec,
    WorkflowTask,
    WorkflowValidationError,
)


class WorkflowParseError(Exception):
    """Raised when a Workflow YAML cannot be parsed."""

    def __init__(self, message: str, field: str | None = None) -> None:
        self.field = field or "unknown"
        super().__init__(message)


# ──────────────────────────────────────────────
# Variable reference pattern
# ──────────────────────────────────────────────

_VAR_REF_PATTERN = re.compile(r'\$\{([^}]+)\}')


def parse_workflow_yaml(source: str | Path) -> WorkflowSpec:
    """
    Parse a Workflow YAML file into a validated WorkflowSpec.

    Args:
        source: Path to YAML file or raw YAML string.

    Returns:
        Validated WorkflowSpec ready for DAG construction.

    Raises:
        WorkflowParseError: If the YAML is invalid or validation fails.
    """
    # Read input
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).exists()):
        path = Path(source)
        raw_yaml = path.read_text(encoding="utf-8")
    else:
        raw_yaml = source

    # Parse YAML
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise WorkflowParseError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise WorkflowParseError("Workflow must be a YAML mapping (dictionary)")

    # Validate kind
    kind = data.get("kind")
    if kind != "Workflow":
        raise WorkflowParseError(f"Expected 'kind: Workflow', got 'kind: {kind}'", field="kind")

    # Parse metadata
    raw_metadata = data.get("metadata", {})
    if not isinstance(raw_metadata, dict):
        raise WorkflowParseError("'metadata' must be a mapping", field="metadata")

    name = raw_metadata.get("name", "")
    if not name:
        raise WorkflowParseError("'metadata.name' is required", field="metadata.name")

    version = raw_metadata.get("version", "")
    if not version:
        raise WorkflowParseError("'metadata.version' is required", field="metadata.version")

    description = raw_metadata.get("description", "")

    # Parse spec
    raw_spec = data.get("spec", {})
    if not isinstance(raw_spec, dict):
        raise WorkflowParseError("'spec' must be a mapping", field="spec")

    goal = raw_spec.get("goal", "")

    # ── Parse Tasks ──
    raw_tasks = raw_spec.get("tasks", [])
    if not isinstance(raw_tasks, list) or len(raw_tasks) == 0:
        raise WorkflowParseError("'spec.tasks' must be a non-empty list", field="spec.tasks")

    seen_ids: set[str] = set()
    tasks: list[WorkflowTask] = []

    for i, raw_task in enumerate(raw_tasks):
        if not isinstance(raw_task, dict):
            raise WorkflowParseError(f"Task at index {i} must be a mapping", field=f"spec.tasks[{i}]")

        task_id = raw_task.get("id", "")
        if not task_id:
            raise WorkflowParseError(f"Task at index {i} is missing required field 'id'", field=f"spec.tasks[{i}].id")
        if task_id in seen_ids:
            raise WorkflowParseError(f"Duplicate task id '{task_id}' at index {i}", field=f"spec.tasks[{i}].id")
        seen_ids.add(task_id)

        capability = raw_task.get("capability", "")
        if not capability:
            raise WorkflowParseError(f"Task '{task_id}' is missing required field 'capability'", field=f"spec.tasks[{i}].capability")

        task_input = raw_task.get("input", {})
        if not isinstance(task_input, dict):
            raise WorkflowParseError(f"Task '{task_id}' 'input' must be a mapping", field=f"spec.tasks[{i}].input")

        tasks.append(WorkflowTask(
            id=task_id,
            capability=capability,
            input=task_input,
            description=raw_task.get("description"),
            skip_if=raw_task.get("skip_if"),
        ))

    # ── Parse Edges ──
    raw_edges = raw_spec.get("edges", [])
    if not isinstance(raw_edges, list):
        raise WorkflowParseError("'spec.edges' must be a list", field="spec.edges")

    edges: list[WorkflowEdge] = []

    for i, raw_edge in enumerate(raw_edges):
        if not isinstance(raw_edge, dict):
            raise WorkflowParseError(f"Edge at index {i} must be a mapping", field=f"spec.edges[{i}]")

        from_task = raw_edge.get("from", "")
        to_task = raw_edge.get("to", "")
        if not from_task or not to_task:
            raise WorkflowParseError(
                f"Edge at index {i} must have 'from' and 'to' fields",
                field=f"spec.edges[{i}]",
            )

        # Validate task references
        task_ids = {t.id for t in tasks}
        if from_task not in task_ids:
            raise WorkflowParseError(
                f"Edge references unknown task '{from_task}'",
                field=f"spec.edges[{i}].from",
            )
        if to_task not in task_ids:
            raise WorkflowParseError(
                f"Edge references unknown task '{to_task}'",
                field=f"spec.edges[{i}].to",
            )

        edges.append(WorkflowEdge(
            from_task=from_task,
            to_task=to_task,
            data=raw_edge.get("data"),
            condition=raw_edge.get("condition"),
        ))

    # ── Parse Semantics ──
    semantics = _parse_semantics(raw_spec.get("semantics", {}))

    # ── Validate variable references ──
    _validate_variable_references(tasks, edges, goal)

    # ── Build WorkflowSpec ──
    return WorkflowSpec(
        name=name,
        version=version,
        tasks=tasks,
        edges=edges,
        semantics=semantics,
        description=description,
        goal=goal,
    )


def _parse_semantics(raw: dict[str, Any]) -> ExecutionSemantics:
    """Parse the semantics section of a Workflow YAML."""
    if not isinstance(raw, dict):
        return ExecutionSemantics.defaults()

    # Retry
    retry = RetryPolicy()
    raw_retry = raw.get("retry", {})
    if isinstance(raw_retry, dict):
        strategy_map = {
            "fixed": RetryStrategy.FIXED,
            "exponential": RetryStrategy.EXPONENTIAL,
            "none": RetryStrategy.NONE,
        }
        strategy_str = raw_retry.get("strategy", "exponential")
        retry.strategy = strategy_map.get(strategy_str, RetryStrategy.EXPONENTIAL)
        retry.max_attempts = int(raw_retry.get("max_attempts", 3))
        retry.initial_interval_ms = _parse_duration(raw_retry.get("initial_interval", "1s"))
        retry.max_interval_ms = _parse_duration(raw_retry.get("max_interval", "30s"))

    # Timeout
    timeout = TimeoutPolicy()
    raw_timeout = raw.get("timeout", {})
    if isinstance(raw_timeout, dict):
        timeout.task_ms = _parse_duration(raw_timeout.get("task", "30s"))
        timeout.workflow_ms = _parse_duration(raw_timeout.get("workflow", "300s"))
        timeout.on_timeout = raw_timeout.get("on_timeout", "fail")

    # Failure
    failure = FailurePolicy()
    raw_failure = raw.get("failure", {})
    if isinstance(raw_failure, dict):
        prop_map = {
            "immediate": FailurePropagation.IMMEDIATE,
            "deferred": FailurePropagation.DEFERRED,
            "none": FailurePropagation.NONE,
        }
        prop_str = raw_failure.get("propagation", "deferred")
        failure.propagation = prop_map.get(prop_str, FailurePropagation.DEFERRED)
        failure.cancel_dependents = bool(raw_failure.get("cancel_dependents", True))
        failure.continue_independents = bool(raw_failure.get("continue_independents", True))
        failure.max_failures = int(raw_failure.get("max_failures", 1))

    # Parallel
    parallel = ParallelPolicy()
    raw_parallel = raw.get("parallel", {})
    if isinstance(raw_parallel, dict):
        strat_map = {
            "task_parallel": ParallelStrategy.TASK_PARALLEL,
            "sequential": ParallelStrategy.SEQUENTIAL,
        }
        strat_str = raw_parallel.get("strategy", "task_parallel")
        parallel.strategy = strat_map.get(strat_str, ParallelStrategy.TASK_PARALLEL)
        parallel.max_concurrency = int(raw_parallel.get("max_concurrency", 0))
        merge_map = {
            "collect": MergeStrategy.COLLECT,
            "merge": MergeStrategy.MERGE,
            "first_complete": MergeStrategy.FIRST_COMPLETE,
        }
        merge_str = raw_parallel.get("merge_strategy", "collect")
        parallel.merge_strategy = merge_map.get(merge_str, MergeStrategy.COLLECT)

    return ExecutionSemantics(
        retry=retry,
        timeout=timeout,
        failure=failure,
        parallel=parallel,
    )


def _parse_duration(value: str | int | None) -> int:
    """Parse a duration string like '30s', '5m', '300' into milliseconds."""
    if value is None:
        return 30000
    if isinstance(value, (int, float)):
        return int(value) * 1000

    value = str(value).strip().lower()
    if value.endswith("ms"):
        try:
            return int(value[:-2])
        except ValueError:
            return 30000
    if value.endswith("s"):
        try:
            return int(value[:-1]) * 1000
        except ValueError:
            return 30000
    if value.endswith("m"):
        try:
            return int(value[:-1]) * 60000
        except ValueError:
            return 30000
    try:
        return int(value) * 1000
    except ValueError:
        return 30000


def _validate_variable_references(
    tasks: list[WorkflowTask],
    edges: list[WorkflowEdge],
    goal: str,
) -> None:
    """Validate that all ${...} variable references resolve to valid sources.

    Supports:
      ${goal.field} — references to goal parameters
      ${task_id.field} — references to upstream task outputs

    Raises:
        WorkflowParseError: If a reference cannot be resolved.
    """
    task_ids = {t.id for t in tasks}

    # Collect all variable references from task inputs and edge data
    all_refs: list[tuple[str, str, str]] = []  # (task_id_or_edge_idx, field_path, reference)

    for task in tasks:
        _collect_refs(task.input, task.id, "input", all_refs)

    for i, edge in enumerate(edges):
        if edge.data:
            _collect_refs(edge.data, f"edge[{i}]", "data", all_refs)

    # Validate each reference
    for context_id, field_path, reference in all_refs:
        parts = reference.split(".")
        if len(parts) < 2:
            raise WorkflowParseError(
                f"Invalid variable reference '${{{reference}}}' in {context_id}.{field_path}",
                field=field_path,
            )

        source_id = parts[0]
        source_field = ".".join(parts[1:])

        if source_id == "goal":
            # goal.field references are always valid (provided at runtime)
            continue

        if source_id not in task_ids:
            raise WorkflowParseError(
                f"Variable '${{{reference}}}' in {context_id}.{field_path} "
                f"references unknown task '{source_id}'",
                field=field_path,
            )

        # Check that the source task appears before the referencing task in the DAG
        if context_id in task_ids:
            # This is checked by the DAG validator later (topological order)
            pass


def _collect_refs(
    obj: Any,
    context_id: str,
    field_path: str,
    results: list[tuple[str, str, str]],
) -> None:
    """Recursively collect all ${...} variable references from a nested dict/list."""
    if isinstance(obj, str):
        for match in _VAR_REF_PATTERN.finditer(obj):
            results.append((context_id, field_path, match.group(1)))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            _collect_refs(value, context_id, f"{field_path}.{key}", results)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _collect_refs(item, context_id, f"{field_path}[{i}]", results)


def workflow_yaml_to_dict(source: str | Path) -> dict[str, Any]:
    """Load a Workflow YAML as a raw dict without full validation.

    Useful for quick inspection.
    """
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).exists()):
        path = Path(source)
        raw_yaml = path.read_text(encoding="utf-8")
    else:
        raw_yaml = source

    data = yaml.safe_load(raw_yaml)
    if not isinstance(data, dict):
        raise WorkflowParseError("Workflow YAML must contain a mapping")
    return data
