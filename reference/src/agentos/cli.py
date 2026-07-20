"""
Agent OS P1 — CLI Entry Point.

Usage:
    agent-os run <workflow_id> --query "..." [--output report.md] [--verbose]
    agent-os list
    agent-os inspect <workflow_id>
    agent-os version
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any
from . import __version__
from .backbone.bus import EventBus
from .backbone.event import Event
from .capabilities import CAPABILITY_MANIFESTS
from .registry import AgentOSRegistry
from .execution_engine import ExecutionEngine
from .workflow_loader import discover_workflows, load as load_workflow, load_from_path

from .models import Plan, PlannedTask
from .planner import plan as do_plan
from .reporter import format_report
from .reviewer import review as do_review


# ── CLI ────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-os",
        description="Agent OS P1 Runtime Kernel — AI-native workflow engine",
    )
    parser.add_argument("--version", action="version", version=f"agent-os {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    # run
    run_p = sub.add_parser("run", help="Execute a workflow")
    run_p.add_argument("workflow_id", help="Workflow id or path/to/workflow.yaml")
    run_p.add_argument("--query", "-q", default="", help="Query parameter for the workflow")
    run_p.add_argument("--output", "-o", default=None, help="Write report to file")
    run_p.add_argument("--json", "-j", action="store_true", help="Output as JSON (RFC-0700)")
    run_p.add_argument("--verbose", "-v", action="store_true", help="Show detailed event log")

    # list
    list_p = sub.add_parser("list", help="List available workflows")
    list_p.add_argument("--dir", "-d", action="append", help="Extra directory to scan")

    # inspect
    insp_p = sub.add_parser("inspect", help="Show workflow definition")
    insp_p.add_argument("workflow_id", help="Workflow id or path")

    # workflow validate
    wf = sub.add_parser("workflow", help="Workflow management commands")
    wf_sub = wf.add_subparsers(dest="workflow_command", required=True)
    val_p = wf_sub.add_parser("validate", help="Validate a workflow YAML file (RFC-0700 §5)")
    val_p.add_argument("path", help="Path to workflow YAML file")
    val_p.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    plan_p = wf_sub.add_parser("plan", help="Show compiled plan without executing (RFC-0700 §6)")
    plan_p.add_argument("workflow_id", help="Workflow id or path")
    plan_p.add_argument("--query", "-q", required=True, help="Query parameter")
    plan_p.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        return _cmd_list(args)
    elif args.command == "inspect":
        return _cmd_inspect(args)
    elif args.command == "run":
        return _cmd_run(args)
    elif args.command == "workflow":
        if args.workflow_command == "validate":
            return _cmd_workflow_validate(args)
        elif args.workflow_command == "plan":
            return _cmd_workflow_plan(args)
    return 1


def _cmd_list(args: argparse.Namespace) -> int:
    extra = getattr(args, "dir", None)
    wfs = discover_workflows(extra_dirs=extra)
    if not wfs:
        print("No workflows found.")
        return 0
    print(f"Available workflows ({len(wfs)}):")
    for wid, path in sorted(wfs.items()):
        print(f"  {wid:30s}  {path}")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    wf_id = args.workflow_id
    path = Path(wf_id)
    try:
        wf = load_from_path(path) if path.suffix in (".yaml", ".yml") else load_workflow(wf_id)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    print(f"ID:          {wf.id}")
    print(f"Name:        {wf.name}")
    print(f"Description: {wf.description}")
    print(f"Tasks ({len(wf.tasks)}):")
    for t in wf.tasks:
        deps = f"  depends_on={t.depends_on}" if t.depends_on else ""
        print(f"  - {t.id:20s}  type={t.type:10s}  enabled={t.enabled}{deps}")
    if wf.rules:
        print(f"Rules:")
        for r in wf.rules:
            print(f"  - {r.key}={r.value}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    wf_id = args.workflow_id
    query = args.query
    verbose = args.verbose
    output_path = args.output

    # ── Setup logging ──────────────────────────────────────────────
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")

    # ── Initialize system ──────────────────────────────────────────
    bus = EventBus()

    if verbose:
        def log_event(e: Event) -> None:
            print(f"  [event] {e.type:30s} source={e.source}", file=sys.stderr)
        bus.subscribe_all(log_event)

    # Set up Registry (RFC-0300) — loads capabilities + scans workflows
    registry = AgentOSRegistry.setup_default(bus=bus)

    # Create Engine with Registry-backed Pool
    engine = ExecutionEngine(bus=bus, registry=registry)

    # ── Load workflow ──────────────────────────────────────────────
    path = Path(wf_id)
    try:
        if path.suffix in (".yaml", ".yml"):
            wf = load_from_path(path, bus=bus)
        else:
            wf = load_workflow(wf_id, bus=bus)
    except Exception as e:
        print(f"Error loading workflow: {e}", file=sys.stderr)
        return 1

    if verbose:
        print(f"  Loaded workflow: {wf.id} ({len(wf.tasks)} tasks)", file=sys.stderr)

    # ── Plan ───────────────────────────────────────────────────────
    try:
        plan = do_plan(wf, bus=bus, extra_params={"query": query})
    except Exception as e:
        print(f"Planning failed: {e}", file=sys.stderr)
        return 1

    if verbose:
        print(f"  Plan: {len(plan.tasks)} tasks, "
              f"rules={plan.rules_applied}", file=sys.stderr)
        for t in plan.tasks:
            print(f"    {t.id:20s}  type={t.type:10s}  deps={t.depends_on}", file=sys.stderr)

    # ── Execute via Event Bus (A4) ──────────────────────────────────
    # Subscribe to Execution:Completed before running engine.
    # Subscriber (review + report) runs synchronously inside
    # engine.execute()'s final _publish() call — deterministic,
    # no dual-path risk (Constitution Article 4).
    _results: list[tuple] = []

    def _on_completed(event) -> None:
        edata = event.payload
        er: ExecutionResult | None = edata.get("execution_result")
        if not er:
            return
        if verbose:
            finished = er.completed_at
            started = er.started_at
            elapsed = (finished - started).total_seconds() if finished and started else 0
            print(f"  Execution done: {er.status} ({elapsed:.1f}s)", file=sys.stderr)
        v = do_review(er, bus=bus)
        if verbose:
            print(f"  Review: {'PASS' if v.passed else 'FAIL'}", file=sys.stderr)
        rm = format_report(er, verdict=v)
        _results.append((er, v, rm))

    bus.subscribe("Execution:Completed", _on_completed)
    bus.subscribe("Execution:Failed", _on_completed)

    if verbose:
        print(f"  Executing...", file=sys.stderr)

    try:
        engine.execute(plan)
    except Exception as e:
        print(f"Execution failed: {e}", file=sys.stderr)
        return 1

    # Subscriber ran synchronously — results guaranteed
    exec_result, verdict, report_md = _results[0]

    use_json = getattr(args, "json", False)

    if use_json:
        import json as _json
        out = {
            "version": "1.0",
            "command": "run",
            "exit_code": 0 if verdict.passed else 1,
            "execution": {
                "execution_id": f"exec://default/{wf_id}",
                "workflow_ref": wf_id,
                "status": exec_result.status,
                "started_at": exec_result.started_at.isoformat() if exec_result.started_at else "",
                "completed_at": exec_result.completed_at.isoformat() if exec_result.completed_at else "",
            },
            "tasks": [
                {
                    "task_id": tid,
                    "stage_id": tid,
                    "status": tr.status,
                    "duration_ms": 0,
                    "output_preview": str(tr.output)[:120] if tr.output else "",
                }
                for tid, tr in exec_result.task_results.items()
            ],
            "review": {
                "result": "pass" if verdict.passed else "fail",
                "score": 1.0 if verdict.passed else 0.0,
                "checks": [
                    {"check": c.name, "status": "pass" if c.passed else "fail"}
                    for c in (verdict.checks or [])
                ],
            },
            "errors": [],
        }
        print(_json.dumps(out, indent=2, default=str))

    elif output_path:
        Path(output_path).write_text(report_md, encoding="utf-8")
        print(f"Report written to: {output_path}")
        return 0
    else:
        print(report_md)

    return 0 if verdict.passed else 1


def _cmd_workflow_validate(args: argparse.Namespace) -> int:
    """Validate a workflow YAML file (RFC-0700 §5)."""
    path = Path(args.path)
    if not path.exists():
        err = {"code": "SYS_ERR_005", "severity": "fatal", "message": f"File not found: {path}"}
        if getattr(args, "json", False):
            import json as _json
            print(_json.dumps({"version": "1.0", "command": "workflow validate",
                               "exit_code": 1, "valid": False, "errors": [err]}))
        else:
            print(f"❌ {path} — file not found")
        return 1

    try:
        from .workflow_loader import load_from_path
        wf = load_from_path(path)
        errors = []
        # Cycle detection
        visited, stack = set(), set()
        def has_cycle(tid, tasks):
            visited.add(tid)
            stack.add(tid)
            tm = {t.id: t for t in tasks}
            for dep in tm[tid].depends_on:
                if dep not in visited:
                    if has_cycle(dep, tasks):
                        return True
                elif dep in stack:
                    errors.append({"code": "WF_ERR_001", "severity": "fatal",
                                   "message": f"Cyclic dependency at stage '{tid}' → '{dep}'"})
                    return True
            stack.discard(tid)
            return False
        for t in wf.tasks:
            if t.id not in visited:
                has_cycle(t.id, wf.tasks)
        # Missing capability_type
        for t in wf.tasks:
            if not t.type:
                errors.append({"code": "WF_ERR_004", "severity": "error",
                               "message": f"Stage '{t.id}' has no capability_type"})
        # Depends_on reference
        tids = {t.id for t in wf.tasks}
        for t in wf.tasks:
            for dep in t.depends_on:
                if dep not in tids:
                    errors.append({"code": "WF_ERR_002", "severity": "fatal",
                                   "message": f"Stage '{t.id}' references unknown stage '{dep}'"})

        valid = len([e for e in errors if e["severity"] != "warning"]) == 0

        if getattr(args, "json", False):
            import json as _json
            print(_json.dumps({
                "version": "1.0", "command": "workflow validate", "exit_code": 0 if valid else 1,
                "file": str(path), "valid": valid,
                "summary": {"stages": len(wf.tasks), "errors": len(errors)},
                "errors": errors,
            }, indent=2))
        else:
            if valid:
                print(f"✅ {path.name} — valid ({len(wf.tasks)} stages, {len(errors)} warnings)")
            else:
                print(f"❌ {path.name} — {len(errors)} error(s)")
                for e in errors:
                    icon = {"fatal": "🚨", "error": "❌", "warning": "⚠️"}.get(e["severity"], "•")
                    print(f"  {icon} {e['code']}: {e['message']}")
        return 0 if valid else 1

    except Exception as e:
        print(f"❌ Validation error: {e}")
        return 1


def _cmd_workflow_plan(args: argparse.Namespace) -> int:
    """Show compiled plan without executing (RFC-0700 §6)."""
    wf_id = args.workflow_id
    query = args.query
    path = Path(wf_id)

    try:
        from .workflow_loader import load_from_path as _load_path, load as _load
        wf = _load_path(path) if path.suffix in (".yaml", ".yml") else _load(wf_id)
    except Exception as e:
        print(f"Error loading workflow: {e}")
        return 1

    try:
        plan = do_plan(wf, extra_params={"query": query})
    except Exception as e:
        plan_err = {"code": "PLAN_ERR_001" if "parse" in str(e).lower() else "PLAN_ERR_004",
                    "severity": "fatal", "message": str(e)}
        if getattr(args, "json", False):
            import json as _json
            print(_json.dumps({"version": "1.0", "command": "workflow plan",
                               "exit_code": 1, "error": plan_err}))
        else:
            print(f"❌ Planning failed: {plan_err['code']}: {e}")
        return 1

    if getattr(args, "json", False):
        import json as _json
        stages_out = []
        for t in plan.tasks:
            stages_out.append({
                "stage_id": t.id, "type": t.type, "active": True,
                "depends_on": t.depends_on,
            })
        print(_json.dumps({
            "version": "1.0", "command": "workflow plan", "exit_code": 0,
            "workflow_ref": wf.id,
            "stages": stages_out,
            "estimates": {"total_cost_usd": 0.0, "total_latency_ms": 0},
        }, indent=2))
    else:
        print(f"📋 Plan for {wf.id}")
        print(f"  Stages ({len(plan.tasks)}):")
        for t in plan.tasks:
            deps = f"  ← {t.depends_on}" if t.depends_on else ""
            print(f"    → {t.id:20s}  [{t.type:10s}]{deps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
