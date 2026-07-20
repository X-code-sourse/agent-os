"""
Agent OS P1 — Core data models.

All modules share these types. No external dependencies.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── Workflow Definition ────────────────────────────────────────────────

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


# ── Plan ───────────────────────────────────────────────────────────────

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
    dag: dict[str, list[str]] = field(default_factory=dict)  # task_id → [dep_ids]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Execution ──────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    """Outcome of executing a single planned task."""
    task_id: str
    status: str                                     # pending | running | completed | failed
    output: Any = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class ExecutionResult:
    """Aggregate result of executing a complete Plan."""
    workflow_id: str
    task_results: dict[str, TaskResult] = field(default_factory=dict)
    status: str = "pending"                         # pending | running | completed | partial | failed
    started_at: datetime | None = None
    completed_at: datetime | None = None


# ── Review ─────────────────────────────────────────────────────────────

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


# ── Events ─────────────────────────────────────────────────────────────

@dataclass
class Event:
    """Message published on the Event Bus."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""               # workflow.loaded | plan.ready | task.started | ...
    source: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
