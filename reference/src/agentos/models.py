"""Agent OS — Core data models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ── Task State Machine ─────────────────────────────────────────────

class TaskState(str, Enum):
    """Task states per RFC-0001 §3.1 — simplified 6-state path."""

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY_QUEUED = "retry_queued"

    def can_transition_to(self, target: TaskState) -> bool:
        transitions = {
            TaskState.CREATED:      {TaskState.QUEUED},
            TaskState.QUEUED:       {TaskState.RUNNING},
            TaskState.RUNNING:      {TaskState.COMPLETED, TaskState.FAILED},
            TaskState.COMPLETED:    set(),
            TaskState.FAILED:       {TaskState.RETRY_QUEUED},
            TaskState.RETRY_QUEUED: {TaskState.QUEUED},
        }
        return target in transitions.get(self, set())


# ── Workflow Definition ────────────────────────────────────────────

@dataclass
class Rule:
    """A simple key-value rule (max_tasks, timeout_seconds, etc.)."""
    key: str
    value: Any


@dataclass
class TaskDef:
    """A single task node in the workflow YAML definition."""
    id: str
    type: str                          # search | llm | gather | review | report
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class Workflow:
    """Loaded from a local YAML file."""
    id: str
    name: str
    description: str = ""
    tasks: list[TaskDef] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    capabilities: dict[str, str] = field(default_factory=dict)


# ── Plan ───────────────────────────────────────────────────────────

@dataclass
class PlannedTask:
    """A task after Planner processing — rules injected, capability bound."""
    id: str
    type: str
    params: dict[str, Any]
    depends_on: list[str]
    capability: str = "default"
    retry_count: int = 0
    max_retries: int = 3
    timeout: int = 120


@dataclass
class Plan:
    """Executable plan produced by the Planner."""
    workflow_id: str
    tasks: list[PlannedTask]
    rules_applied: list[str] = field(default_factory=list)
    dag: dict[str, list[str]] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── State History ──────────────────────────────────────────────────

@dataclass
class StateTransition:
    """A single state transition record."""
    from_state: TaskState | None
    to_state: TaskState
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str = ""


# ── Execution ──────────────────────────────────────────────────────

@dataclass
class TaskResult:
    """Outcome of executing a single planned task, with state history."""
    task_id: str
    status: str = TaskState.CREATED.value
    output: Any = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    state_history: list[StateTransition] = field(default_factory=list)

    def transition_to(self, new_state: TaskState, reason: str = "") -> None:
        current = TaskState(self.status)
        if not current.can_transition_to(new_state):
            raise ValueError(
                f"Invalid transition: {current.value} → {new_state.value}"
            )
        self.state_history.append(StateTransition(
            from_state=current, to_state=new_state, reason=reason
        ))
        self.status = new_state.value


@dataclass
class ExecutionResult:
    """Aggregate result of executing a complete Plan."""
    workflow_id: str
    task_results: dict[str, TaskResult] = field(default_factory=dict)
    status: str = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None


# ── Review ─────────────────────────────────────────────────────────

@dataclass
class ReviewCheck:
    """A single check outcome from the Reviewer."""
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ReviewVerdict:
    """Overall review verdict for a workflow run."""
    workflow_id: str
    passed: bool
    checks: list[ReviewCheck] = field(default_factory=list)
    summary: str = ""


# ── Events (legacy — used by P1 EventBus) ──────────────────────────

@dataclass
class Event:
    """Legacy P1 Event — used by event_bus.EventBus.
    
    Deprecated in favour of backbone.event.Event (RFC-0500 compliant).
    Kept for backward compatibility with existing subscribers.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""
    source: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
