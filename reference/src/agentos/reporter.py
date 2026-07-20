"""
Agent OS P1 — Reporter.

Formats execution + review results into a human-readable report.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import ExecutionResult, ReviewVerdict


def format_report(
    execution_result: ExecutionResult,
    verdict: ReviewVerdict | None = None,
    format: str = "markdown",
) -> str:
    """Format results as a Markdown report string."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        f"# Agent OS Report — `{execution_result.workflow_id}`",
        f"",
        f"**Generated:** {now}",
        f"**Execution Status:** {execution_result.status}",
        f"",
    ]

    # ── Task results ────────────────────────────────────────────────
    lines.append("## Task Results")
    lines.append("")
    lines.append(f"| Task | Status | Output Preview |")
    lines.append(f"|------|--------|---------------|")
    for tr in execution_result.task_results.values():
        preview = _preview(tr.output, 80) if tr.status == "completed" else tr.error or ""
        status_icon = "✅" if tr.status == "completed" else "❌" if tr.status == "failed" else "⏳"
        lines.append(f"| {tr.task_id} | {status_icon} {tr.status} | {preview} |")

    lines.append("")

    # ── Review verdict ──────────────────────────────────────────────
    if verdict:
        lines.append("## Quality Review")
        lines.append("")
        lines.append(f"**Overall:** {'✅ PASSED' if verdict.passed else '❌ FAILED'}")
        lines.append("")
        lines.append(f"| Check | Result | Detail |")
        lines.append(f"|-------|--------|--------|")
        for c in verdict.checks:
            icon = "✅" if c.passed else "❌"
            lines.append(f"| {c.name} | {icon} | {c.detail} |")
        lines.append("")
        if verdict.summary:
            lines.append(f"_{verdict.summary}_")
            lines.append("")

    # ── Full outputs ────────────────────────────────────────────────
    lines.append("## Detailed Outputs")
    lines.append("")
    for tr in execution_result.task_results.values():
        if tr.status == "completed" and tr.output:
            lines.append(f"### {tr.task_id}")
            lines.append("")
            lines.append(str(tr.output))
            lines.append("")
        elif tr.error:
            lines.append(f"### {tr.task_id} (failed)")
            lines.append("")
            lines.append(f"```\n{tr.error}\n```")
            lines.append("")

    return "\n".join(lines)


def _preview(value: object, max_len: int = 80) -> str:
    text = str(value)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
