"""
Agent OS P1 — Planner.

Transforms a Workflow into an executable Plan:
1. Filter enabled tasks
2. Resolve dependencies & build DAG
3. Inject rules as task-level params
4. Bind capabilities
5. Topological sort
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any

from .backbone.bus import EventBus
from .models import Plan, PlannedTask, Rule, TaskDef, Workflow


class PlanningError(Exception):
    """Raised when plan construction fails (cycle, missing dep, etc.)."""


def plan(
    workflow: Workflow,
    bus: EventBus | None = None,
    extra_params: dict[str, Any] | None = None,
) -> Plan:
    """Produce an executable Plan from a Workflow definition."""
    extra = extra_params or {}
    rules_applied: list[str] = []

    # ── 1. Filter enabled tasks ────────────────────────────────────
    enabled = [t for t in workflow.tasks if t.enabled]
    if not enabled:
        raise PlanningError(f"Workflow '{workflow.id}' has no enabled tasks")

    # ── 2. Inject rules ────────────────────────────────────────────
    for rule in workflow.rules:
        if rule.key == "max_tasks" and len(enabled) > int(rule.value):
            enabled = enabled[: int(rule.value)]
            rules_applied.append(f"max_tasks={rule.value}")

        if rule.key == "timeout_seconds":
            for t in enabled:
                t.params.setdefault("timeout", int(rule.value))
            rules_applied.append(f"timeout_seconds={rule.value}")

    # ── 3. Build PlannedTasks ──────────────────────────────────────
    planned: list[PlannedTask] = []
    for t in enabled:
        params = dict(t.params)
        params.update(extra)  # inject CLI params like {query}

        planned.append(
            PlannedTask(
                id=t.id,
                type=t.type,
                params=params,
                depends_on=list(t.depends_on),
                capability=workflow.capabilities.get(t.type, "default"),
            )
        )

    # ── 4. Build DAG & validate dependencies ──────────────────────
    task_ids = {t.id for t in planned}
    dag: dict[str, list[str]] = {}
    for t in planned:
        for dep in t.depends_on:
            if dep not in task_ids:
                raise PlanningError(
                    f"Task '{t.id}' depends on '{dep}' which is not in the workflow"
                )
        dag[t.id] = list(t.depends_on)

    # ── 5. Topological sort (Kahn's algorithm) ────────────────────
    sorted_ids = _topological_sort(dag, list(task_ids))

    # Reorder tasks per topological sort
    order_map = {t.id: t for t in planned}
    sorted_planned = [order_map[tid] for tid in sorted_ids]

    plan = Plan(
        workflow_id=workflow.id,
        tasks=sorted_planned,
        rules_applied=rules_applied,
        dag=dag,
    )

    if bus:
        from .backbone.event import Event
        bus.publish(Event.new(
            event_type="plan.ready",
            payload={
                "workflow_id": workflow.id,
                "task_count": len(sorted_planned),
                "dag": dag,
            },
            source={"module": "planner", "instance_id": ""},
        ))

    return plan


def _topological_sort(dag: dict[str, list[str]], all_ids: list[str]) -> list[str]:
    """Kahn's algorithm. Raises PlanningError on cycle."""
    in_degree: dict[str, int] = {nid: 0 for nid in all_ids}
    for nid, deps in dag.items():
        for dep in deps:
            if dep in in_degree:
                in_degree[nid] += 1

    queue: deque[str] = deque(nid for nid, d in in_degree.items() if d == 0)
    sorted_ids: list[str] = []

    while queue:
        nid = queue.popleft()
        sorted_ids.append(nid)
        for other_id, deps in dag.items():
            if nid in deps:
                in_degree[other_id] -= 1
                if in_degree[other_id] == 0:
                    queue.append(other_id)

    if len(sorted_ids) != len(all_ids):
        raise PlanningError(
            f"Cycle detected in task DAG. Sorted {len(sorted_ids)}/{len(all_ids)}"
        )

    return sorted_ids
