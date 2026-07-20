"""
Agent OS P1 — Reviewer.

Performs basic quality checks on execution results before report generation.
Simple check functions that can be extended without changing the pipeline.
"""

from __future__ import annotations

from typing import Any

from .event_bus import EventBus
from .models import Event, ExecutionResult, ReviewCheck, ReviewVerdict


def review(
    execution_result: ExecutionResult,
    bus: EventBus | None = None,
) -> ReviewVerdict:
    """Run all applicable checks on an execution result."""
    checks: list[ReviewCheck] = []

    # Check 1: status
    checks.append(ReviewCheck(
        name="execution_status",
        passed=execution_result.status in ("completed", "partial"),
        detail=f"Status: {execution_result.status}",
    ))

    # Check 2: non-empty outputs for completed tasks
    non_empty_count = 0
    for tr in execution_result.task_results.values():
        if tr.status == "completed" and tr.output is not None:
            non_empty_count += 1

    total = len(execution_result.task_results)
    checks.append(ReviewCheck(
        name="non_empty_outputs",
        passed=non_empty_count > 0,
        detail=f"{non_empty_count}/{total} tasks produced output",
    ))

    # Check 3: minimum content length (concatenate string outputs)
    full_text = ""
    for tr in execution_result.task_results.values():
        if isinstance(tr.output, str):
            full_text += tr.output
        elif isinstance(tr.output, dict) and "text" in tr.output:
            full_text += str(tr.output["text"])

    min_len = 50
    checks.append(ReviewCheck(
        name="min_content_length",
        passed=len(full_text.strip()) >= min_len,
        detail=f"Report text length: {len(full_text.strip())} (min: {min_len})",
    ))

    passed = all(c.passed for c in checks)

    verdict = ReviewVerdict(
        workflow_id=execution_result.workflow_id,
        passed=passed,
        checks=checks,
        summary=_build_summary(checks, passed),
    )

    if bus:
        bus.publish(Event(
            type="review.passed" if passed else "review.failed",
            source="reviewer",
            data={
                "workflow_id": execution_result.workflow_id,
                "passed": passed,
                "check_count": len(checks),
            }
        ))

    return verdict


def _build_summary(checks: list[ReviewCheck], passed: bool) -> str:
    passed_count = sum(1 for c in checks if c.passed)
    total = len(checks)
    if passed:
        return f"✅ All {passed_count}/{total} quality checks passed"
    return f"⚠️  {passed_count}/{total} quality checks passed — review details below"
