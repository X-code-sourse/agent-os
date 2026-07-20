"""
Agent OS P1 — Execution Engine.

Drives the DAG: receives a Plan, schedules tasks in topological order,
manages the task state machine (pending → running → completed/failed),
and publishes state transitions via the Event Bus.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from .event_bus import EventBus
from .models import (
    Event,
    ExecutionResult,
    Plan,
    PlannedTask,
    TaskResult,
)

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Resolves a task type to an actual callable.

    v1: simple dict-based registry. Injected by the Engine.
    """

    def __init__(self) -> None:
        self._registry: dict[str, Any] = {}

    def register(self, task_type: str, fn: Any) -> None:
        self._registry[task_type] = fn

    def execute(self, task: PlannedTask, context: dict[str, Any]) -> Any:
        fn = self._registry.get(task.type)
        if fn is None:
            raise ValueError(f"No executor registered for task type '{task.type}'")
        return fn(task, context)


class ExecutionEngine:
    """Schedules and executes a Plan's DAG."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self.bus = bus
        self.executor = TaskExecutor()

    def execute(
        self,
        plan: Plan,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute a Plan and return aggregated results."""
        ctx = context or {}
        result = ExecutionResult(
            workflow_id=plan.workflow_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )

        # Map task_id → PlannedTask
        task_map = {t.id: t for t in plan.tasks}

        # Track completed task outputs
        outputs: dict[str, Any] = {}

        # Build reverse DAG (successors) for scheduling
        successors: dict[str, list[str]] = {t.id: [] for t in plan.tasks}
        for t in plan.tasks:
            for dep in t.depends_on:
                successors.setdefault(dep, []).append(t.id)

        # ── State tracking ─────────────────────────────────────────
        ready: deque[str] = deque()
        in_degree: dict[str, int] = {t.id: len(t.depends_on) for t in plan.tasks}
        running: dict[str, PlannedTask] = {}
        completed_or_failed: set[str] = set()

        # Seed ready queue
        for t in plan.tasks:
            if in_degree[t.id] == 0:
                ready.append(t.id)

        # ── Main execution loop ─────────────────────────────────────
        while ready or running:
            # Start available tasks
            while ready:
                task_id = ready.popleft()
                task = task_map[task_id]
                running[task_id] = task

                tr = TaskResult(task_id=task_id, status="running",
                                started_at=datetime.now(timezone.utc))
                result.task_results[task_id] = tr

                self._publish(Event(
                    type="task.started", source="execution_engine",
                    data={"task_id": task_id, "type": task.type}
                ))

                # Execute (synchronously for v1)
                try:
                    output = self.executor.execute(task, {**ctx, **outputs})
                    tr.status = "completed"
                    tr.output = output
                    tr.completed_at = datetime.now(timezone.utc)
                    outputs[task_id] = output
                    self._publish(Event(
                        type="task.completed", source="execution_engine",
                        data={"task_id": task_id, "status": "completed"}
                    ))
                except Exception as e:
                    tr.status = "failed"
                    tr.error = str(e)
                    tr.completed_at = datetime.now(timezone.utc)
                    logger.error("Task %s failed: %s", task_id, e)
                    self._publish(Event(
                        type="task.failed", source="execution_engine",
                        data={"task_id": task_id, "error": str(e)}
                    ))

                completed_or_failed.add(task_id)
                del running[task_id]

                # Update successors' readiness
                for succ_id in successors.get(task_id, []):
                    in_degree[succ_id] -= 1
                    if in_degree[succ_id] == 0 and succ_id not in completed_or_failed:
                        ready.append(succ_id)

        # ── Aggregate result ────────────────────────────────────────
        failed = [r for r in result.task_results.values() if r.status == "failed"]
        if failed:
            result.status = "partial" if len(failed) < len(result.task_results) else "failed"
        else:
            result.status = "completed"

        result.completed_at = datetime.now(timezone.utc)

        self._publish(Event(
            type="execution.finished", source="execution_engine",
            data={
                "workflow_id": plan.workflow_id,
                "status": result.status,
                "total": len(result.task_results),
                "failed": len(failed),
            }
        ))

        return result

    def _publish(self, event: Event) -> None:
        if self.bus:
            self.bus.publish(event)
