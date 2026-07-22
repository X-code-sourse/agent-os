"""
Agent OS — Workflow Data Model (SPEC-0002)

Defines the data structures for representing executable workflows:

  WorkflowSpec      — Top-level workflow definition (Structure + Semantics)
  WorkflowTask      — A single task node referencing a Capability
  WorkflowEdge      — Dependency and data flow between tasks
  ExecutionSemantics — Retry, timeout, failure, parallel, lifecycle policies
  WorkflowDAG       — Validated, ready-to-execute DAG with adjacency structures
  WorkflowStatus    — Execution state tracking for each task

This implements the SPEC-0002 split:
  - Workflow Structure Spec: nodes, edges, dependency, dataflow
  - Execution Semantics Spec: retry, timeout, failure propagation, compensation, parallel
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class TaskStatus(Enum):
    """Execution status of a single workflow task."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRIABLE = "failed_retriable"
    FAILED_FATAL = "failed_fatal"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"


class WorkflowStatus(Enum):
    """Top-level workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class RetryStrategy(Enum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    NONE = "none"


class FailurePropagation(Enum):
    IMMEDIATE = "immediate"
    DEFERRED = "deferred"
    NONE = "none"


class ParallelStrategy(Enum):
    TASK_PARALLEL = "task_parallel"
    SEQUENTIAL = "sequential"


class MergeStrategy(Enum):
    COLLECT = "collect"
    MERGE = "merge"
    FIRST_COMPLETE = "first_complete"


class TaskInitMode(Enum):
    ON_DEMAND = "on_demand"
    EAGER = "eager"


class CompensationStrategy(Enum):
    """How compensation actions are triggered on fatal failure."""
    ROLLBACK = "rollback"
    COMPENSATE = "compensate"
    NONE = "none"


# ──────────────────────────────────────────────
# Execution Semantics (SPEC-0002 Section 4)
# ──────────────────────────────────────────────

@dataclass
class RetryPolicy:
    """How task failures are retried."""
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    max_attempts: int = 3
    initial_interval_ms: int = 1000
    max_interval_ms: int = 30000
    backoff_multiplier: float = 2.0
    retryable_errors: tuple[str, ...] = (
        "timeout", "rate_limit", "server_error", "unavailable"
    )


@dataclass
class TimeoutPolicy:
    """How timeouts are handled."""
    task_ms: int = 30000
    workflow_ms: int = 300000
    on_timeout: str = "fail"  # fail | skip | retry
    retry_on_timeout: bool = True


@dataclass
class FailurePolicy:
    """How failures propagate through the workflow."""
    propagation: FailurePropagation = FailurePropagation.DEFERRED
    cancel_dependents: bool = True
    continue_independents: bool = True
    max_failures: int = 1


@dataclass
class ParallelPolicy:
    """How parallel execution is controlled."""
    max_concurrency: int = 0  # 0 = unlimited
    strategy: ParallelStrategy = ParallelStrategy.TASK_PARALLEL
    merge_strategy: MergeStrategy = MergeStrategy.COLLECT


@dataclass
class LifecyclePolicy:
    """Task lifecycle behavior."""
    task_init: TaskInitMode = TaskInitMode.ON_DEMAND
    caching: bool = True


@dataclass
class CompensationPolicy:
    """How compensation is handled when a task reaches FAILED_FATAL."""
    strategy: CompensationStrategy = CompensationStrategy.NONE
    action: str | None = None
    order: str = "reverse"
    max_compensation_attempts: int = 1


@dataclass
class CheckpointPolicy:
    """How checkpoints are created during workflow execution (Phase 2+)."""
    interval: str = "task"
    store: str = "event_store"
    resume: str = "auto"


@dataclass
class ExecutionSemantics:
    """
    Complete execution semantics for a workflow (SPEC-0002 Section 4).

    This is the behavioral contract that makes workflows truly portable.
    Two runtimes executing the same WorkflowSpec with the same semantics
    MUST produce the same observable behavior.
    """
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: TimeoutPolicy = field(default_factory=TimeoutPolicy)
    failure: FailurePolicy = field(default_factory=FailurePolicy)
    parallel: ParallelPolicy = field(default_factory=ParallelPolicy)
    lifecycle: LifecyclePolicy = field(default_factory=LifecyclePolicy)
    compensation: CompensationPolicy = field(default_factory=CompensationPolicy)
    checkpoint: CheckpointPolicy = field(default_factory=CheckpointPolicy)

    @classmethod
    def defaults(cls) -> ExecutionSemantics:
        return cls()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for event recording."""
        return {
            "retry": {
                "strategy": self.retry.strategy.value,
                "max_attempts": self.retry.max_attempts,
                "initial_interval_ms": self.retry.initial_interval_ms,
                "max_interval_ms": self.retry.max_interval_ms,
                "backoff_multiplier": self.retry.backoff_multiplier,
            },
            "timeout": {
                "task_ms": self.timeout.task_ms,
                "workflow_ms": self.timeout.workflow_ms,
                "on_timeout": self.timeout.on_timeout,
            },
            "failure": {
                "propagation": self.failure.propagation.value,
                "cancel_dependents": self.failure.cancel_dependents,
                "continue_independents": self.failure.continue_independents,
                "max_failures": self.failure.max_failures,
            },
            "parallel": {
                "max_concurrency": self.parallel.max_concurrency,
                "strategy": self.parallel.strategy.value,
                "merge_strategy": self.parallel.merge_strategy.value,
            },
            "compensation": {
                "strategy": self.compensation.strategy.value,
                "action": self.compensation.action,
                "order": self.compensation.order,
            },
            "checkpoint": {
                "interval": self.checkpoint.interval,
                "store": self.checkpoint.store,
                "resume": self.checkpoint.resume,
            },
        }


# ──────────────────────────────────────────────
# Workflow Structure (SPEC-0002 Section 3)
# ──────────────────────────────────────────────

@dataclass
class WorkflowTask:
    """
    A single task node in a workflow. References a Capability Manifest.

    Each task:
      - Has a unique ID within the workflow
      - References a capability by name@version
      - Declares its input bindings (static values or references to upstream outputs)
      - Has runtime state during execution
    """
    id: str
    capability: str  # name@version
    input: dict[str, Any] = field(default_factory=dict)
    description: str | None = None
    skip_if: str | None = None  # Condition expression; if true, task is skipped

    # Runtime state (set during execution, not serialized in Spec)
    status: TaskStatus = TaskStatus.PENDING
    output: Any = None
    error: str | None = None
    attempt: int = 0
    latency_ms: int = 0
    token_count: int = 0
    cost_usd: float = 0.0

    def to_spec_dict(self) -> dict[str, Any]:
        """Serialize the spec portion (no runtime state)."""
        result: dict[str, Any] = {
            "id": self.id,
            "capability": self.capability,
            "input": self.input,
            "description": self.description,
        }
        if self.skip_if:
            result["skip_if"] = self.skip_if
        return result


@dataclass
class WorkflowEdge:
    """
    A directed edge between two tasks, with optional data mapping.

    Edges define:
      - Control flow: from → to (dependency ordering)
      - Data flow: how upstream outputs are mapped to downstream inputs
    """
    from_task: str
    to_task: str
    data: dict[str, Any] | None = None  # Optional explicit data mapping
    condition: str | None = None  # Condition expression; if false, edge is skipped

    def to_dict(self) -> dict[str, str | dict | None]:
        result: dict[str, str | dict | None] = {
            "from": self.from_task,
            "to": self.to_task,
            "data": self.data,
        }
        if self.condition:
            result["condition"] = self.condition
        return result


@dataclass
class WorkflowSpec:
    """
    Complete workflow specification (SPEC-0002).

    Contains everything needed to define a workflow:
      - Metadata (name, version, description, goal)
      - Task topology (tasks + edges)
      - Execution semantics (how the workflow behaves at runtime)

    This is the portable unit — it can be serialized, shared, and
    executed on any compatible runtime.
    """
    name: str
    version: str
    tasks: list[WorkflowTask]
    edges: list[WorkflowEdge]
    semantics: ExecutionSemantics = field(default_factory=ExecutionSemantics)
    description: str | None = None
    goal: str | None = None

    @property
    def id(self) -> str:
        return f"{self.name}@{self.version}"

    def get_task(self, task_id: str) -> WorkflowTask | None:
        """Look up a task by ID."""
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def get_dependencies(self, task_id: str) -> list[WorkflowTask]:
        """Get all direct dependencies (upstream tasks) for a given task."""
        deps = []
        for edge in self.edges:
            if edge.to_task == task_id:
                task = self.get_task(edge.from_task)
                if task:
                    deps.append(task)
        return deps

    def get_dependents(self, task_id: str) -> list[WorkflowTask]:
        """Get all direct dependents (downstream tasks) for a given task."""
        deps = []
        for edge in self.edges:
            if edge.from_task == task_id:
                task = self.get_task(edge.to_task)
                if task:
                    deps.append(task)
        return deps

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict (for YAML output / event recording)."""
        return {
            "kind": "Workflow",
            "metadata": {
                "name": self.name,
                "version": self.version,
                "description": self.description,
            },
            "spec": {
                "goal": self.goal,
                "tasks": [t.to_spec_dict() for t in self.tasks],
                "edges": [e.to_dict() for e in self.edges],
                "semantics": self.semantics.to_dict(),
            },
        }


# ──────────────────────────────────────────────
# Workflow DAG — Validated Runtime Structure
# ──────────────────────────────────────────────

class WorkflowDAG:
    """
    A validated, ready-to-execute DAG derived from a WorkflowSpec.

    Responsibilities:
      - Validate acyclicity (no cycles)
      - Compute topological ordering
      - Identify parallel branches (independent sub-DAGs)
      - Provide fast adjacency lookups during scheduling

    This is the runtime representation — it's what the Scheduler
    uses to drive execution.
    """

    def __init__(self, spec: WorkflowSpec) -> None:
        self.spec = spec
        self._task_map: dict[str, WorkflowTask] = {t.id: t for t in spec.tasks}
        self._adjacency: dict[str, list[str]] = {}   # task → [dependents]
        self._dependencies: dict[str, list[str]] = {}  # task → [dependencies]
        self._topological_order: list[str] = []
        self._levels: dict[str, int] = {}  # task_id → topological level

        # Build adjacency structures
        for task in spec.tasks:
            self._adjacency[task.id] = []
            self._dependencies[task.id] = []

        for edge in spec.edges:
            if edge.from_task in self._adjacency:
                self._adjacency[edge.from_task].append(edge.to_task)
            if edge.to_task in self._dependencies:
                self._dependencies[edge.to_task].append(edge.from_task)

        # Validate and compute ordering
        self._validate()
        self._compute_topological_order()
        self._compute_levels()

    def _validate(self) -> None:
        """Validate the DAG: acyclicity and task existence."""
        # Check all referenced tasks exist
        for edge in self.spec.edges:
            if edge.from_task not in self._task_map:
                raise WorkflowValidationError(
                    f"Edge references unknown task '{edge.from_task}'"
                )
            if edge.to_task not in self._task_map:
                raise WorkflowValidationError(
                    f"Edge references unknown task '{edge.to_task}'"
                )

        # Cycle detection using DFS
        UNVISITED, VISITING, VISITED = 0, 1, 2
        state: dict[str, int] = {t.id: UNVISITED for t in self.spec.tasks}
        parent: dict[str, str | None] = {}

        def dfs(node: str) -> None:
            state[node] = VISITING
            for neighbor in self._adjacency.get(node, []):
                if state.get(neighbor) == VISITING:
                    # Cycle detected — trace it
                    cycle_path = [neighbor, node]
                    current = node
                    while current != neighbor:
                        current = parent.get(current)
                        if current is None:
                            break
                        cycle_path.append(current)
                    cycle_path.reverse()
                    raise WorkflowValidationError(
                        f"Cycle detected in workflow: {' → '.join(cycle_path)}"
                    )
                if state.get(neighbor) == UNVISITED:
                    parent[neighbor] = node
                    dfs(neighbor)
            state[node] = VISITED

        for task in self.spec.tasks:
            if state[task.id] == UNVISITED:
                parent[task.id] = None
                dfs(task.id)

        # Check all tasks are reachable from at least one root
        roots = self.get_root_tasks()
        if not roots:
            raise WorkflowValidationError("No root tasks (all tasks have dependencies)")

    def _compute_topological_order(self) -> None:
        """Kahn's algorithm for topological sort."""
        in_degree: dict[str, int] = {}
        for task in self.spec.tasks:
            in_degree[task.id] = len(self._dependencies.get(task.id, []))

        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        order = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in self._adjacency.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self.spec.tasks):
            raise WorkflowValidationError(
                "Topological sort failed — possible unresolved dependencies"
            )

        self._topological_order = order

    def _compute_levels(self) -> None:
        """Compute topological levels (longest path from root)."""
        levels: dict[str, int] = {}
        for tid in self._topological_order:
            deps = self._dependencies.get(tid, [])
            if not deps:
                levels[tid] = 0
            else:
                levels[tid] = max(levels.get(d, -1) for d in deps) + 1
        self._levels = levels

    @property
    def topological_order(self) -> list[str]:
        return list(self._topological_order)

    def get_level(self, task_id: str) -> int:
        return self._levels.get(task_id, 0)

    def get_root_tasks(self) -> list[WorkflowTask]:
        """Tasks with no dependencies (entry points)."""
        return [
            self._task_map[tid]
            for tid, deps in self._dependencies.items()
            if not deps
        ]

    def get_leaf_tasks(self) -> list[WorkflowTask]:
        """Tasks with no dependents (exit points)."""
        return [
            self._task_map[tid]
            for tid, adjs in self._adjacency.items()
            if not adjs
        ]

    def get_parallel_branches(self, level: int) -> list[list[WorkflowTask]]:
        """Group tasks at the same topological level into parallel branches.

        Tasks at the same level with no shared dependencies are independent
        and can be executed in parallel.
        """
        level_tasks = [
            t for t in self.spec.tasks
            if self._levels.get(t.id) == level
        ]
        # Each task at the same level is an independent branch
        return [[t] for t in level_tasks]

    def get_task(self, task_id: str) -> WorkflowTask:
        task = self._task_map.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found in workflow")
        return task

    def get_dependencies(self, task_id: str) -> list[WorkflowTask]:
        return [self._task_map[d] for d in self._dependencies.get(task_id, [])
                if d in self._task_map]

    def are_dependencies_satisfied(self, task_id: str) -> bool:
        """Check if all dependencies of a task have succeeded."""
        for dep in self.get_dependencies(task_id):
            if dep.status != TaskStatus.SUCCEEDED:
                return False
        return True

    # ── Condition Evaluation (Adaptive Execution Graph) ──

    def evaluate_condition(
        self,
        condition: str | None,
        task_outputs: dict[str, Any],
        input_data: dict[str, Any] | None = None,
    ) -> bool:
        """Evaluate a condition expression against current task outputs.

        If condition is None or empty, returns True (always pass).
        This ensures backward compatibility — workflows without conditions
        are unaffected.

        Args:
            condition: Condition expression string or None.
            task_outputs: Dict of {task_id: output} from completed tasks.
            input_data: Optional workflow input data.

        Returns:
            True if condition is met (or no condition), False otherwise.
        """
        if not condition:
            return True
        from core.conditions import evaluate_condition as _eval
        return _eval(condition, task_outputs, input_data)

    def get_outbound_edges(self, task_id: str) -> list[Any]:
        """Get all outbound edges from a task."""
        return [e for e in self.spec.edges if e.from_task == task_id]

    def get_effective_dependents(
        self,
        task_id: str,
        task_outputs: dict[str, Any],
        input_data: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Get downstream tasks enabled by this task's completion,
        filtering by condition expressions on outbound edges.

        An edge with a condition that evaluates to False is pruned.
        Unless another edge enables the same downstream task, it won't
        be scheduled.
        """
        enabled: list[Any] = []
        for edge in self.get_outbound_edges(task_id):
            if self.evaluate_condition(edge.condition, task_outputs, input_data):
                task = self._task_map.get(edge.to_task)
                if task:
                    enabled.append(task)
        return enabled

    def should_skip_task(
        self,
        task_id: str,
        task_outputs: dict[str, Any],
        input_data: dict[str, Any] | None = None,
    ) -> bool:
        """Check if a task should be skipped due to its skip_if condition."""
        task = self._task_map.get(task_id)
        if not task or not task.skip_if:
            return False
        return self.evaluate_condition(task.skip_if, task_outputs, input_data)

    def has_satisfied_inbound_path(
        self,
        task_id: str,
        task_outputs: dict[str, Any],
        input_data: dict[str, Any] | None = None,
    ) -> bool:
        """Check if at least one inbound edge to a task has a satisfied condition.

        A task with no inbound edges (root task) always returns True.
        An edge with no condition always passes.
        This prevents scheduling a task whose conditional data paths
        have all been blocked by failing edge conditions.
        """
        inbound = [e for e in self.spec.edges if e.to_task == task_id]
        if not inbound:
            return True  # Root task
        return any(
            self.evaluate_condition(e.condition, task_outputs, input_data)
            for e in inbound
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize DAG info for debugging / observability."""
        return {
            "task_count": len(self.spec.tasks),
            "edge_count": len(self.spec.edges),
            "topological_order": self.topological_order,
            "levels": self._levels,
            "roots": [t.id for t in self.get_root_tasks()],
            "leaves": [t.id for t in self.get_leaf_tasks()],
        }


class WorkflowValidationError(Exception):
    """Raised when a workflow specification fails validation."""
    pass
