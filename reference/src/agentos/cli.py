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
from .event_bus import EventBus
from .execution_engine import ExecutionEngine
from .models import Event, Plan, PlannedTask
from .planner import plan as do_plan
from .reporter import format_report
from .reviewer import review as do_review
from .workflow_loader import discover_workflows, load as load_workflow, load_from_path

# ── Built-in task executors ────────────────────────────────────────


def _exec_search(task: PlannedTask, context: dict[str, Any]) -> str:
    """Mock search executor — v1 returns placeholder text."""
    query = task.params.get("query", "")
    return f"【搜索结果】\n查询: {query}\n\n1. {query} 最新动态摘要\n2. {query} 行业分析\n3. 相关市场数据\n\n（注：v1 原型使用模拟数据，实际搜索 API 将在后续迭代接入）"


def _exec_llm(task: PlannedTask, context: dict[str, Any]) -> str:
    """Mock LLM executor — v1 returns placeholder analysis."""
    prompt = task.params.get("prompt", "")
    return f"【LLM 分析结果】\n\n输入提示: {prompt[:100]}...\n\n## 投资亮点\n- 行业领先地位\n- 强劲的营收增长\n- 技术创新驱动\n\n## 风险因素\n- 市场竞争加剧\n- 监管不确定性\n- 估值偏高\n\n## 综合评估\n基于现有数据，该公司在行业中具有竞争优势，建议持续关注。（v1 原型模拟数据）"


def _exec_review(task: PlannedTask, context: dict[str, Any]) -> dict:
    """Review task — aggregates previous outputs into a structured result."""
    checks = task.params.get("checks", ["non_empty"])
    outputs = {k: v for k, v in context.items() if isinstance(v, str)}
    return {
        "checks": checks,
        "non_empty_count": sum(1 for v in outputs.values() if v.strip()),
        "text": "\n\n".join(outputs.values()),
    }


def _exec_report(task: PlannedTask, context: dict[str, Any]) -> str:
    """Report task — compiles final output."""
    sections = task.params.get("sections", [])
    lines = []
    for sec in sections:
        title = sec.get("title", "")
        content = sec.get("content", "")
        resolved = _resolve_template(content, context)
        if title:
            lines.append(f"## {title}")
        lines.append(resolved)
        lines.append("")
    return "\n".join(lines) if lines else "报告生成完成。"


def _resolve_template(template: str, context: dict[str, Any]) -> str:
    """Replace {key} placeholders with context values."""
    import re

    def replacer(m: re.Match) -> str:
        key = m.group(1)
        # Support dotted path like search_news.output
        parts = key.replace(".output", "").split(".")
        val = context
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p, "")
            else:
                return f"{{{key}}}"
        return str(val) if val is not None else f"{{{key}}}"

    return re.sub(r"\{(\w+(?:\.\w+)*)\}", replacer, template)


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
    run_p.add_argument("--verbose", "-v", action="store_true", help="Show detailed event log")

    # list
    list_p = sub.add_parser("list", help="List available workflows")
    list_p.add_argument("--dir", "-d", action="append", help="Extra directory to scan")

    # inspect
    insp_p = sub.add_parser("inspect", help="Show workflow definition")
    insp_p.add_argument("workflow_id", help="Workflow id or path")

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

    engine = ExecutionEngine(bus=bus)

    # Register built-in executors
    engine.executor.register("search", _exec_search)
    engine.executor.register("llm", _exec_llm)
    engine.executor.register("gather", _exec_review)
    engine.executor.register("review", _exec_review)
    engine.executor.register("report", _exec_report)

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

    # ── Execute ────────────────────────────────────────────────────
    if verbose:
        print(f"  Executing...", file=sys.stderr)
    try:
        exec_result = engine.execute(plan)
    except Exception as e:
        print(f"Execution failed: {e}", file=sys.stderr)
        return 1

    if verbose:
        finished = exec_result.completed_at
        started = exec_result.started_at
        elapsed = (finished - started).total_seconds() if finished and started else 0
        print(f"  Execution done: {exec_result.status} ({elapsed:.1f}s)", file=sys.stderr)

    # ── Review ─────────────────────────────────────────────────────
    verdict = do_review(exec_result, bus=bus)
    if verbose:
        print(f"  Review: {'PASS' if verdict.passed else 'FAIL'}", file=sys.stderr)

    # ── Report ─────────────────────────────────────────────────────
    report = format_report(exec_result, verdict=verdict)

    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")
        print(f"Report written to: {output_path}")
    else:
        print(report)

    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
