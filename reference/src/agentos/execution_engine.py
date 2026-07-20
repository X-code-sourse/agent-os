"""Execution Engine — RFC-0102.

Drives the DAG: receives a Plan, schedules tasks in topological order,
manages the 6-state Task machine (RFC-0001), publishes standard events
through the Event Bus, and invokes capabilities through the Capability Pool.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from .backbone.event import Event as BackboneEvent
from .capability_pool import CapabilityPool, _LegacyAdapter
from .event_bus import EventBus
from .models import (
    ExecutionResult,
    Plan,
    PlannedTask,
    StateTransition,
    TaskResult,
    TaskState,
)

logger = logging.getLogger(__name__)

# ── Event type constants ───────────────────────────────────────────
# RFC-0001 §6.1 standard event types

TASK_CREATED = "Task:Created"
TASK_QUEUED = "Task:Queued"
TASK_RUNNING = "Task:Running"
TASK_COMPLETED = "Task:Completed"
TASK_FAILED = "Task:Failed"
TASK_RETRY_QUEUED = "Task:RetryQueued"
EXECUTION_CREATED = "Execution:Created"
EXECUTION_RUNNING = "Execution:Running"
EXECUTION_COMPLETED = "Execution:Completed"
EXECUTION_FAILED = "Execution:Failed"


class ExecutionEngine:
    """Schedules and executes a Plan's DAG (RFC-0102)."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self.bus = bus
        self.pool = CapabilityPool()

    # ── Plan ingestion (RFC-0102 §4) ───────────────────────────────

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

        self._publish(EXECUTION_CREATED, {
            "execution_id": f"exec://default/{plan.workflow_id}",
            "workflow_ref": plan.workflow_id,
            "task_count": len(plan.tasks),
        })

        task_map = {t.id: t for t in plan.tasks}
        outputs: dict[str, Any] = {}

        # Build reverse DAG for scheduling
        successors: dict[str, list[str]] = {t.id: [] for t in plan.tasks}
        for t in plan.tasks:
            for dep in t.depends_on:
                successors.setdefault(dep, []).append(t.id)

        # ── State tracking ──────────────────────────────────────────
        ready: deque[str] = deque()
        in_degree: dict[str, int] = {t.id: len(t.depends_on) for t in plan.tasks}
        running: dict[str, PlannedTask] = {}
        completed_or_failed: set[str] = set()

        # Seed ready queue
        for t in plan.tasks:
            tr = TaskResult(task_id=t.id, status=TaskState.CREATED.value)
            # Initial state — already CREATED, record without transition
            tr.state_history.append(StateTransition(
                from_state=None, to_state=TaskState.CREATED, reason="plan_activated"
            ))
            result.task_results[t.id] = tr
            self._publish(TASK_CREATED, {"task_id": t.id, "type": t.type})

            if in_degree[t.id] == 0:
                ready.append(t.id)
                tr.transition_to(TaskState.QUEUED, "dependencies_satisfied")
                self._publish(TASK_QUEUED, {"task_id": t.id, "type": t.type})

        self._publish(EXECUTION_RUNNING, {
            "execution_id": f"exec://default/{plan.workflow_id}",
            "task_count": len(plan.tasks),
        })

        # ── Main execution loop ─────────────────────────────────────
        while ready or running:
            while ready:
                task_id = ready.popleft()
                task = task_map[task_id]
                running[task_id] = task
                tr = result.task_results[task_id]

                tr.transition_to(TaskState.RUNNING, "dispatched")
                tr.started_at = datetime.now(timezone.utc)
                self._publish(TASK_RUNNING, {
                    "task_id": task_id,
                    "type": task.type,
                })

                # Execute via Capability Pool (RFC-0200 §5)
                inv_result = self.pool.invoke(task, {**ctx, **outputs})

                if inv_result.status == "success":
                    tr.transition_to(TaskState.COMPLETED, "execution_success")
                    tr.output = inv_result.output
                    tr.completed_at = datetime.now(timezone.utc)
                    outputs[task_id] = inv_result.output
                    self._publish(TASK_COMPLETED, {
                        "task_id": task_id,
                        "duration_ms": 0,
                    })
                else:
                    tr.transition_to(TaskState.FAILED, inv_result.error or "unknown_error")
                    tr.error = inv_result.error
                    tr.completed_at = datetime.now(timezone.utc)
                    logger.error("Task %s failed: %s", task_id, inv_result.error)
                    self._publish(TASK_FAILED, {
                        "task_id": task_id,
                        "error": inv_result.error,
                        "error_code": inv_result.error_code,
                    })

                completed_or_failed.add(task_id)
                del running[task_id]

                # Update successors
                for succ_id in successors.get(task_id, []):
                    in_degree[succ_id] -= 1
                    if in_degree[succ_id] == 0 and succ_id not in completed_or_failed:
                        succ_tr = result.task_results[succ_id]
                        succ_tr.transition_to(TaskState.QUEUED, "dependencies_satisfied")
                        self._publish(TASK_QUEUED, {"task_id": succ_id})
                        ready.append(succ_id)

        # ── Aggregate result ────────────────────────────────────────
        failed = [r for r in result.task_results.values() if r.status == "failed"]
        if failed:
            result.status = "partial" if len(failed) < len(result.task_results) else "failed"
        else:
            result.status = "completed"

        result.completed_at = datetime.now(timezone.utc)

        exec_status = EXECUTION_COMPLETED if result.status == "completed" else EXECUTION_FAILED
        self._publish(exec_status, {
            "workflow_id": plan.workflow_id,
            "status": result.status,
            "total": len(result.task_results),
            "failed": len(failed),
            "execution_result": result,
        })

        return result

    # ── Event publishing ────────────────────────────────────────────

    def _publish(self, event_type: str, payload: dict) -> None:
        """Publish a standard BackboneEvent and a legacy P1 Event."""
        if not self.bus:
            return
        # RFC-0500 compliant event
        event = BackboneEvent.new(
            event_type=event_type,
            payload=payload,
            source={"module": "execution_engine", "instance_id": ""},
        )
        # Publish to EventBus using models.Event (legacy) wrapped content
        from .models import Event as LegacyEvent
        self.bus.publish(LegacyEvent(
            type=event_type,
            source="execution_engine",
            data=payload,
        ))
        # Also log the backbone event
        logger.debug("Published: %s", event.event_type)
