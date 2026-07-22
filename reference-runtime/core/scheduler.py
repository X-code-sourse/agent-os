"""
Agent OS — Workflow Execution Scheduler (SPEC-0002 Execution Semantics)

The Scheduler drives the execution of a WorkflowDAG according to its
ExecutionSemantics. It implements the full task state machine:

  PENDING → READY → RUNNING → SUCCEEDED
                              → FAILED_RETRIABLE → READY (with backoff)
                              → FAILED_FATAL → BLOCKED (trigger compensation)
                              → TIMEOUT → BLOCKED

The Scheduler is part of the Control Plane and OWNS NO STATE.
All state transitions are recorded as Events through the Event Bus.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

from core.executor import Executor
from core.models import EventType, ExecutionRecord, ExecutionStatus
from core.recorder import ExecutionRecorder
from core.workflow import (
    CompensationStrategy,
    ExecutionSemantics,
    FailurePropagation,
    MergeStrategy,
    RetryStrategy,
    TaskStatus,
    WorkflowDAG,
    WorkflowSpec,
    WorkflowTask,
    WorkflowStatus,
)


class ScheduleError(Exception):
    """Raised when scheduling fails."""
    pass


class Scheduler:
    """
    Executes a WorkflowDAG according to its ExecutionSemantics.

    The Scheduler:
      - Drives task state machine transitions
      - Manages retry logic with configurable backoff
      - Enforces failure propagation policies
      - Controls parallel execution concurrency
      - Monitors timeouts
      - Records all events through the Event Bus

    Design constraint: The Scheduler is part of the Control Plane.
    It does NOT own state—all state is recorded as Events.
    """

    def __init__(
        self,
        executor: Executor,
        recorder: ExecutionRecorder,
        workflow_dag: WorkflowDAG,
        trace_id: str | None = None,
    ) -> None:
        self._executor = executor
        self._recorder = recorder
        self._dag = workflow_dag
        self._trace_id = trace_id or str(uuid.uuid4())
        self._semantics = workflow_dag.spec.semantics

        # Internal state
        self._lock = threading.Lock()
        self._status: WorkflowStatus = WorkflowStatus.PENDING
        self._failed_tasks: int = 0
        self._completed_tasks: int = 0
        self._running_tasks: dict[str, threading.Thread] = {}
        self._task_outputs: dict[str, Any] = {}
        self._task_errors: dict[str, str] = {}
        self._task_attempts: dict[str, int] = {}
        self._completed_order: list[str] = []
        self._compensation_events: list[dict[str, Any]] = []
        self._registry: Any = None
        self._input_data: dict[str, Any] = {}  # For condition evaluation

        # Callbacks
        self._on_task_complete: Callable | None = None
        self._on_workflow_complete: Callable | None = None

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def status(self) -> WorkflowStatus:
        return self._status

    def set_callbacks(
        self,
        on_task_complete: Callable | None = None,
        on_workflow_complete: Callable | None = None,
    ) -> None:
        self._on_task_complete = on_task_complete
        self._on_workflow_complete = on_workflow_complete

    def set_registry(self, registry: Any) -> None:
        self._registry = registry

    def set_executor(self, executor: Executor) -> None:
        self._executor = executor

    def execute(
        self,
        input_data: dict[str, Any] | None = None,
        adapter_name: str | None = None,
    ) -> ExecutionRecord:
        """
        Execute the full workflow DAG.

        This is the main entry point. It:
          1. Records WorkflowStarted event
          2. Processes tasks in topological order
          3. Manages parallel branches according to semantics
          4. Records WorkflowCompleted event
          5. Returns an ExecutionRecord

        Args:
            input_data: Optional global input data for the workflow.
            adapter_name: Optional adapter override for all tasks.

        Returns:
            ExecutionRecord with all workflow events.
        """
        input_data = input_data or {}
        self._input_data = input_data
        self._status = WorkflowStatus.RUNNING

        # Record workflow start
        self._recorder.record(
            event_type=EventType.WORKFLOW_STARTED,
            source="scheduler",
            payload={
                "workflow_id": self._dag.spec.id,
                "goal": self._dag.spec.goal or "",
                "task_count": len(self._dag.spec.tasks),
                "semantic_hash": str(hash(str(self._semantics.to_dict()))),
            },
        )

        # Process tasks in topological order, level by level
        try:
            self._process_levels(adapter_name)
        except Exception as exc:
            self._status = WorkflowStatus.FAILED
            self._recorder.record_failed(
                task_id="_workflow",
                capability=self._dag.spec.id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                retry_allowed=False,
            )

        # Determine final status
        final_status = self._compute_final_status()
        self._status = final_status

        # Trigger compensation if workflow failed
        if final_status in (WorkflowStatus.FAILED, WorkflowStatus.PARTIAL):
            self._execute_compensation()

        # Record workflow completion
        self._recorder.record(
            event_type=EventType.WORKFLOW_COMPLETED,
            source="scheduler",
            payload={
                "workflow_id": self._dag.spec.id,
                "status": final_status.value,
                "tasks_succeeded": sum(
                    1 for t in self._dag.spec.tasks
                    if t.status == TaskStatus.SUCCEEDED
                ),
                "tasks_failed": sum(
                    1 for t in self._dag.spec.tasks
                    if t.status in (TaskStatus.FAILED_FATAL, TaskStatus.TIMEOUT)
                ),
                "tasks_skipped": sum(
                    1 for t in self._dag.spec.tasks
                    if t.status == TaskStatus.SKIPPED
                ),
            },
            metrics={
                "total_latency_ms": self._compute_total_latency(),
                "total_cost_usd": sum(t.cost_usd for t in self._dag.spec.tasks),
                "total_tokens": sum(t.token_count for t in self._dag.spec.tasks),
            },
        )

        # Build execution record
        record = self._recorder.build_record(
            manifest_name=self._dag.spec.name,
            manifest_version=self._dag.spec.version,
            runtime_id="scheduler",
            adapter="WorkflowScheduler",
            adapter_version="0.1.0",
            input_data=input_data,
            output_data=self._task_outputs,
            status=ExecutionStatus.SUCCESS
            if final_status == WorkflowStatus.SUCCEEDED
            else ExecutionStatus.PARTIAL
            if final_status == WorkflowStatus.PARTIAL
            else ExecutionStatus.FAILURE,
            error=None if final_status in (
                WorkflowStatus.SUCCEEDED, WorkflowStatus.PARTIAL
            ) else "Workflow execution failed",
        )

        if self._on_workflow_complete:
            self._on_workflow_complete(record)

        return record

    def _process_levels(self, adapter_name: str | None) -> None:
        """Process tasks level by level through the DAG.

        Within a level, tasks are executed according to the parallel policy.
        """
        max_level = max(
            (self._dag.get_level(t.id) for t in self._dag.spec.tasks),
            default=0,
        )

        for level in range(max_level + 1):
            if self._status == WorkflowStatus.FAILED:
                break

            level_tasks = [
                t for t in self._dag.spec.tasks
                if self._dag.get_level(t.id) == level
            ]

            if not level_tasks:
                continue

            # Execute this level's tasks
            if (self._semantics.parallel.strategy.value == "sequential"
                    or len(level_tasks) == 1):
                # Sequential: one at a time
                for task in level_tasks:
                    self._execute_single_task(task, adapter_name)
                    if self._should_abort():
                        break
            else:
                # Parallel: concurrent with concurrency limit
                self._execute_parallel_tasks(level_tasks, adapter_name)

    def _execute_single_task(
        self,
        task: WorkflowTask,
        adapter_name: str | None,
    ) -> None:
        """Execute a single task with retry logic and failure handling."""
        # Check dependencies
        if not self._dag.are_dependencies_satisfied(task.id):
            task.status = TaskStatus.BLOCKED
            return

        # Check inbound edge conditions (adaptive execution graph)
        if not self._dag.has_satisfied_inbound_path(task.id, self._task_outputs, self._input_data):
            task.status = TaskStatus.BLOCKED
            self._recorder.record(
                event_type=EventType.TASK_SKIPPED,
                source="scheduler",
                task_id=task.id,
                payload={"reason": "No inbound edge condition satisfied"},
            )
            return

        # Check failure propagation
        if self._should_skip_due_to_failure(task):
            task.status = TaskStatus.SKIPPED
            self._recorder.record(
                event_type=EventType.TASK_SKIPPED,
                source="scheduler",
                task_id=task.id,
                payload={"reason": "Upstream task failed"},
            )
            return

        # Check adaptive skip condition (Phase 2)
        if self._dag.should_skip_task(task.id, self._task_outputs, self._input_data):
            task.status = TaskStatus.SKIPPED
            self._recorder.record(
                event_type=EventType.TASK_SKIPPED,
                source="scheduler",
                task_id=task.id,
                payload={"reason": f"skip_if condition met: {task.skip_if}"},
            )
            return

        task.status = TaskStatus.READY
        attempt = 0
        max_attempts = self._semantics.retry.max_attempts

        while attempt < max_attempts:
            attempt += 1
            task.attempt = attempt
            task.status = TaskStatus.RUNNING

            # Record start
            self._recorder.record_started(
                task_id=task.id,
                capability=task.capability,
                input_ref=str(task.input),
            )

            # Execute with timeout
            start_time = time.monotonic()
            result = None
            error = None
            timed_out = False

            # Check timeout before execution
            timeout_ms = self._semantics.timeout.task_ms
            if timeout_ms <= 0:
                timeout_ms = 30000  # Default

            def execute_task() -> tuple[Any, Any | None]:
                try:
                    record = self._executor.execute(
                        manifest=self._resolve_capability_manifest(task),
                        input_data=task.input,
                        adapter_name=adapter_name,
                        trace_id=self._trace_id,
                    )
                    if record.status == ExecutionStatus.SUCCESS:
                        return record.output, None
                    else:
                        return None, record.error or "Execution failed"
                except Exception as exc:
                    return None, str(exc)

            # Run with timeout via a thread
            exec_thread = threading.Thread(target=lambda: None)
            exec_thread.start()

            # Simplified timeout handling — in production this would use
            # concurrent.futures.ThreadPoolExecutor with timeout
            try:
                # Use the executor directly (simplified for Phase 1)
                record = self._executor.execute(
                    manifest=self._resolve_capability_manifest(task),
                    input_data=task.input,
                    adapter_name=adapter_name,
                    trace_id=self._trace_id,
                )
                elapsed_ms = int((time.monotonic() - start_time) * 1000)

                if record.status == ExecutionStatus.SUCCESS:
                    result = record.output
                    task.output = result
                    task.latency_ms = elapsed_ms
                    # Extract token metrics from record
                    task.token_count = record.total_tokens
                    task.cost_usd = record.total_cost_usd
                    error = None
                else:
                    error = record.error or "Execution failed"
                    # Check if error is retriable
                    if not self._is_retriable(error):
                        attempt = max_attempts  # Don't retry

            except Exception as exc:
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                error = str(exc)
                if not self._is_retriable(error):
                    attempt = max_attempts

            if error is not None:
                # Record failure
                retriable = attempt < max_attempts and self._is_retriable(error)
                self._recorder.record_failed(
                    task_id=task.id,
                    capability=task.capability,
                    error_type="ExecutionError",
                    error_message=error,
                    attempt=attempt,
                    retry_allowed=retriable,
                )

                if retriable:
                    task.status = TaskStatus.FAILED_RETRIABLE
                    # Apply backoff
                    backoff_ms = self._compute_backoff(attempt)
                    self._recorder.record(
                        event_type=EventType.TASK_RETRIED,
                        source="scheduler",
                        task_id=task.id,
                        payload={
                            "attempt": attempt,
                            "previous_attempt": attempt - 1,
                            "backoff_ms": backoff_ms,
                            "retry_reason": error,
                        },
                    )
                    time.sleep(backoff_ms / 1000)
                else:
                    task.status = TaskStatus.FAILED_FATAL
                    task.error = error
                    self._failed_tasks += 1
                    self._task_errors[task.id] = error

                    # Check failure propagation
                    if self._semantics.failure.propagation.value == "immediate":
                        self._status = WorkflowStatus.FAILED
                        return

                    if self._failed_tasks >= self._semantics.failure.max_failures:
                        if self._semantics.failure.propagation.value != "none":
                            self._status = WorkflowStatus.FAILED
                            return
            else:
                # Success!
                task.status = TaskStatus.SUCCEEDED
                self._completed_tasks += 1
                self._task_outputs[task.id] = result
                self._completed_order.append(task.id)

                if self._on_task_complete:
                    self._on_task_complete(task)

                return

    def _execute_parallel_tasks(
        self,
        tasks: list[WorkflowTask],
        adapter_name: str | None,
    ) -> None:
        """Execute multiple tasks in parallel with concurrency control."""
        max_concurrency = self._semantics.parallel.max_concurrency
        if max_concurrency <= 0:
            max_concurrency = len(tasks)

        threads: list[threading.Thread] = []
        results: dict[str, Any] = {}

        def run_task_in_thread(t: WorkflowTask) -> None:
            self._execute_single_task(t, adapter_name)
            results[t.id] = (t.status, t.output, t.error)

        # Limit concurrency
        for i in range(0, len(tasks), max_concurrency):
            batch = tasks[i:i + max_concurrency]
            batch_threads = []

            for task in batch:
                if self._should_abort():
                    break
                t = threading.Thread(target=run_task_in_thread, args=(task,))
                t.start()
                batch_threads.append(t)

            for t in batch_threads:
                t.join()

            if self._should_abort():
                break

    def _resolve_capability_manifest(self, task: WorkflowTask) -> Any:
        """Resolve a task's capability reference to a CapabilityManifest."""
        # This needs the actual manifest — in Phase 1, the caller
        # should have registered the capability. The Executor will
        # look it up from its registry.
        # For now, create a minimal placeholder manifest.
        from core.models import (
            CapabilityManifest, MetadataSpec, FieldSchema,
            RequirementSpec, SecuritySpec,
        )
        name = task.capability
        version = "1.0.0"
        if "@" in task.capability:
            parts = task.capability.split("@")
            name = parts[0]
            version = parts[1] if len(parts) > 1 else "1.0.0"

        return CapabilityManifest(
            metadata=MetadataSpec(name=name, version=version),
            input_schema={},
            output_schema={},
            requirements=RequirementSpec(),
            security=SecuritySpec(),
        )

    def _is_retriable(self, error: str) -> bool:
        """Check if an error is retriable based on the retry policy."""
        error_lower = error.lower()
        for err_type in self._semantics.retry.retryable_errors:
            if err_type in error_lower:
                return True

        # Common retriable error patterns
        retriable_patterns = [
            "timeout", "rate_limit", "429", "503", "unavailable",
            "server error", "connection", "temporary",
        ]
        for pattern in retriable_patterns:
            if pattern in error_lower:
                return True

        return False

    def _compute_backoff(self, attempt: int) -> int:
        """Compute backoff interval in milliseconds based on retry policy."""
        if self._semantics.retry.strategy.value == "fixed":
            return self._semantics.retry.initial_interval_ms

        # Exponential: interval * multiplier^(attempt-1), capped at max_interval
        backoff = self._semantics.retry.initial_interval_ms * (
            self._semantics.retry.backoff_multiplier ** (attempt - 1)
        )
        return min(int(backoff), self._semantics.retry.max_interval_ms)

    def _should_skip_due_to_failure(self, task: WorkflowTask) -> bool:
        """Check if a task should be skipped due to upstream failures."""
        if not self._semantics.failure.cancel_dependents:
            return False

        for dep in self._dag.get_dependencies(task.id):
            if dep.status in (
                TaskStatus.FAILED_FATAL,
                TaskStatus.TIMEOUT,
                TaskStatus.CANCELLED,
            ):
                return True
        return False

    def _should_abort(self) -> bool:
        """Check if execution should abort due to failures."""
        return self._status == WorkflowStatus.FAILED

    def _execute_compensation(self) -> None:
        strategy = self._semantics.compensation.strategy
        if strategy == CompensationStrategy.NONE:
            return
        if strategy == CompensationStrategy.ROLLBACK:
            order = list(self._completed_order)
            if self._semantics.compensation.order == "reverse":
                order.reverse()
            rec = self._recorder
            for task_id in order:
                task = self._dag.get_task(task_id)
                if task.status == TaskStatus.SUCCEEDED:
                    task.status = TaskStatus.CANCELLED
                    rec.record(event_type=EventType.TASK_CANCELLED, source="scheduler",
                               task_id=task_id, capability=task.capability,
                               payload={"reason": "compensation_rollback"})
        elif strategy == CompensationStrategy.COMPENSATE:
            rec = self._recorder
            rec.record(event_type=EventType.TASK_CANCELLED, source="scheduler", task_id="_workflow",
                       payload={"reason": "compensation_not_implemented", "strategy": "compensate"})

    def _compute_final_status(self) -> WorkflowStatus:
        """Compute the final workflow status based on task outcomes."""
        all_succeeded = all(
            t.status == TaskStatus.SUCCEEDED
            for t in self._dag.spec.tasks
        )
        any_failed = any(
            t.status in (TaskStatus.FAILED_FATAL, TaskStatus.TIMEOUT)
            for t in self._dag.spec.tasks
        )
        any_skipped = any(
            t.status == TaskStatus.SKIPPED
            for t in self._dag.spec.tasks
        )

        if all_succeeded:
            return WorkflowStatus.SUCCEEDED
        elif any_failed and any_skipped:
            return WorkflowStatus.PARTIAL
        elif any_failed:
            return WorkflowStatus.FAILED
        else:
            return WorkflowStatus.PARTIAL

    def _compute_total_latency(self) -> int:
        """Sum of all task latencies."""
        return sum(
            t.latency_ms for t in self._dag.spec.tasks
        )
