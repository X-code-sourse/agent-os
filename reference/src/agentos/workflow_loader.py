"""
Agent OS P1 — Workflow Loader.

Reads workflow definitions from local YAML files and validates them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .event_bus import EventBus
from .models import Event, Rule, TaskDef, Workflow

WORKFLOW_DIRS = [
    Path.cwd() / "workflows",
    Path.home() / ".agent-os" / "workflows",
]


class WorkflowLoadError(Exception):
    """Raised when a workflow cannot be loaded or validated."""


def discover_workflows(
    extra_dirs: list[str | Path] | None = None,
) -> dict[str, Path]:
    """Scan known directories for *.yaml workflow files.

    Returns {workflow_id: path}.
    """
    dirs = list(WORKFLOW_DIRS)
    if extra_dirs:
        dirs.extend(Path(d) for d in extra_dirs)

    discovered: dict[str, Path] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.yaml")):
            wf_id = f.stem
            discovered[wf_id] = f
    return discovered


def load(workflow_id: str, bus: EventBus | None = None) -> Workflow:
    """Load and validate a workflow by its id.

    Searches WORKFLOW_DIRS in order. Raises WorkflowLoadError if not found
    or invalid.
    """
    discovered = discover_workflows()
    path = discovered.get(workflow_id)
    if not path:
        raise WorkflowLoadError(
            f"Workflow '{workflow_id}' not found. "
            f"Available: {list(discovered.keys())}"
        )
    return _load_from_path(path, bus)


def load_from_path(path: str | Path, bus: EventBus | None = None) -> Workflow:
    """Load and validate a workflow from a specific file path."""
    return _load_from_path(Path(path), bus)


def _load_from_path(path: Path, bus: EventBus | None = None) -> Workflow:
    if not path.exists():
        raise WorkflowLoadError(f"Workflow file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    if not raw:
        raise WorkflowLoadError(f"Empty workflow file: {path}")

    # ── Validate required fields ────────────────────────────────────
    if "id" not in raw:
        raise WorkflowLoadError(f"Workflow {path} missing 'id' field")
    if "tasks" not in raw or not isinstance(raw["tasks"], list):
        raise WorkflowLoadError(f"Workflow {raw.get('id')} missing 'tasks' list")

    # ── Parse fields ────────────────────────────────────────────────
    tasks = []
    for t in raw["tasks"]:
        if "id" not in t:
            raise WorkflowLoadError(f"Task in {raw['id']} missing 'id'")
        if "type" not in t:
            raise WorkflowLoadError(f"Task '{t['id']}' in {raw['id']} missing 'type'")
        tasks.append(
            TaskDef(
                id=t["id"],
                type=t["type"],
                params=t.get("params", {}),
                depends_on=t.get("depends_on", []),
                enabled=t.get("enabled", True),
            )
        )

    rules = []
    for r in raw.get("rules", []):
        if isinstance(r, dict):
            for k, v in r.items():
                rules.append(Rule(key=k, value=v))
        elif isinstance(r, str):
            rules.append(Rule(key=r, value=True))

    wf = Workflow(
        id=raw["id"],
        name=raw.get("name", raw["id"]),
        description=raw.get("description", ""),
        tasks=tasks,
        rules=rules,
        capabilities=raw.get("capabilities", {}),
    )

    if bus:
        bus.publish(
            Event(type="workflow.loaded", source="workflow_loader",
                  data={"workflow_id": wf.id, "task_count": len(tasks)})
        )

    return wf
