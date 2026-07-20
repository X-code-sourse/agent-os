"""Capability Pool — RFC-0200/0203.

Manages invocation of capabilities with invoke/cancel/status interface.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .models import PlannedTask

logger = logging.getLogger(__name__)


# ── Result envelope ────────────────────────────────────────────────

@dataclass
class InvocationResult:
    """Structured result from a capability invocation."""
    status: str                                     # success | partial | error | cancelled
    output: Any = None
    error: str | None = None
    error_code: str = ""
    metrics: dict = field(default_factory=lambda: {
        "tokens_used": 0, "api_calls": 0, "latency_ms": 0, "cost_usd": 0,
    })

    @property
    def is_retryable(self) -> bool:
        return self.error_code in ("timeout", "rate_limit_exceeded", "temporary")


# ── Capability Pool ────────────────────────────────────────────────

class CapabilityPool:
    """Manages capability invocation with invoke/cancel/status.

    RFC-0200 §5 / RFC-0203.
    v1: synchronous, in-process, no queueing.
    """

    def __init__(self, registry: "AgentOSRegistry | None" = None) -> None:
        self._registry_dict: dict[str, Callable] = {}
        self._invocations: dict[str, InvocationResult] = {}
        self._manifest_registry = registry

    def register(self, task_type: str, fn: Callable) -> None:
        """Register a callable for a task type."""
        self._registry_dict[task_type] = fn
        logger.debug("Pool: registered type=%s", task_type)

    def invoke(
        self,
        task: PlannedTask,
        context: dict[str, Any],
    ) -> InvocationResult:
        """Invoke a capability. Returns structured result."""
        fn = None
        # Check direct dict first, then manifest registry
        if task.type in self._registry_dict:
            fn = self._registry_dict[task.type]
        elif self._manifest_registry:
            manifest = self._manifest_registry.resolve_capability(task.type)
            if manifest and manifest.fn:
                fn = manifest.fn
                # Cache for future calls
                self._registry_dict[task.type] = fn
        if fn is None:
            return InvocationResult(
                status="error",
                error=f"No capability registered for type '{task.type}'",
                error_code="invalid_input",
            )

        invocation_id = f"invoc://pool/{task.id}"
        try:
            output = fn(task, context)
            result = InvocationResult(status="success", output=output)
            self._invocations[invocation_id] = result
            return result
        except Exception as e:
            result = InvocationResult(
                status="error",
                error=str(e),
                error_code="internal_error",
            )
            self._invocations[invocation_id] = result
            return result

    def cancel(self, task_id: str) -> None:
        """Cancel a running invocation. v1: no-op (synchronous only)."""
        logger.debug("Pool: cancel requested for %s (v1 no-op)", task_id)

    def status(self, task_id: str) -> InvocationResult | None:
        """Return the result of a completed invocation."""
        return self._invocations.get(f"invoc://pool/{task_id}")
