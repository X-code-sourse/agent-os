"""
Intent OS — Adaptive Execution Graph Tests

Tests cover:
  1. Conditional edge routing — task with ${x} > N condition
  2. Skip_if conditions — task skipped when condition is met
  3. Inbound path blocking — all inbound edges condition-failed → BLOCKED
  4. Backward compatibility — workflows without conditions work unchanged
  5. Combined conditions — multiple conditions in one workflow
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.executor import Executor
from core.models import (
    EventType, ExecutionRecord, ExecutionStatus,
    FieldSchema, MetadataSpec, RequirementSpec, SecuritySpec,
    CapabilityManifest,
)
from core.recorder import ExecutionRecorder
from core.scheduler import Scheduler
from core.workflow import (
    ExecutionSemantics, FailurePolicy, FailurePropagation,
    ParallelPolicy, ParallelStrategy, RetryPolicy, RetryStrategy,
    TaskStatus, WorkflowDAG, WorkflowEdge, WorkflowSpec,
    WorkflowTask, WorkflowStatus,
)
from core.workflow_runner import SimulatedExecutor, SimulatedAdapter


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def executor():
    return SimulatedExecutor()


@pytest.fixture
def seq_semantics():
    return ExecutionSemantics(
        retry=RetryPolicy(strategy=RetryStrategy.NONE),
        parallel=ParallelPolicy(strategy=ParallelStrategy.SEQUENTIAL),
    )


def run_workflow(dag, executor, input_data=None):
    """Helper: run a workflow and return the record and dag."""
    recorder = ExecutionRecorder(trace_id="adaptive-test")
    scheduler = Scheduler(executor, recorder, dag, trace_id="adaptive-test")
    record = scheduler.execute(input_data=input_data or {})
    return record, dag


# ====================================================================
# 1. Conditional Edge Routing
# ====================================================================

class TestConditionalEdges:
    """Test that edge conditions direct execution flow."""

    def test_edge_condition_met(self, executor, seq_semantics):
        """When condition is met, the downstream task should execute."""
        spec = WorkflowSpec(
            name="conditional_test", version="1.0.0",
            tasks=[
                WorkflowTask(id="search", capability="web_search@1.0.0",
                             input={"query": "test"}),
                WorkflowTask(id="analyze", capability="text_analyze@1.0.0",
                             input={"text": "${search.results}"}),
                WorkflowTask(id="report", capability="report_generate@1.0.0",
                             input={"content": "${analyze.result}"}),
            ],
            edges=[
                WorkflowEdge(from_task="search", to_task="analyze"),
                WorkflowEdge(from_task="analyze", to_task="report",
                             condition="${analyze.confidence} > 0.5"),
            ],
            semantics=seq_semantics,
        )
        dag = WorkflowDAG(spec)
        record, dag = run_workflow(dag, executor)

        # analyze.confidence is 0.85 in SimulatedAdapter → condition met
        assert dag.get_task("report").status == TaskStatus.SUCCEEDED

    def test_edge_condition_blocked(self, executor, seq_semantics):
        """When condition is not met, the downstream task should be blocked."""
        spec = WorkflowSpec(
            name="conditional_block", version="1.0.0",
            tasks=[
                WorkflowTask(id="search", capability="web_search@1.0.0",
                             input={"query": "test"}),
                WorkflowTask(id="analyze", capability="text_analyze@1.0.0",
                             input={"text": "${search.results}"}),
                WorkflowTask(id="report", capability="report_generate@1.0.0",
                             input={"content": "${analyze.result}"}),
            ],
            edges=[
                WorkflowEdge(from_task="search", to_task="analyze"),
                WorkflowEdge(from_task="analyze", to_task="report",
                             condition="${analyze.confidence} > 0.99"),
            ],
            semantics=seq_semantics,
        )
        dag = WorkflowDAG(spec)
        record, dag = run_workflow(dag, executor)

        # analyze.confidence is 0.85 in SimulatedAdapter → condition NOT met
        # The report task should be BLOCKED because its only inbound edge failed
        report = dag.get_task("report")
        assert report.status == TaskStatus.BLOCKED

    def test_conditional_fan_out(self, executor, seq_semantics):
        """Fan-out with conditions: only matching path executes."""
        spec = WorkflowSpec(
            name="conditional_fanout", version="1.0.0",
            tasks=[
                WorkflowTask(id="search", capability="web_search@1.0.0",
                             input={"query": "test"}),
                WorkflowTask(id="urgent_path", capability="text_analyze@1.0.0",
                             input={"text": "${search.results}"}),
                WorkflowTask(id="normal_path", capability="text_analyze@1.0.0",
                             input={"text": "${search.results}"}),
            ],
            edges=[
                WorkflowEdge(from_task="search", to_task="urgent_path",
                             condition="${search.total_results} > 10"),
                WorkflowEdge(from_task="search", to_task="normal_path"),
            ],
            semantics=seq_semantics,
        )
        dag = WorkflowDAG(spec)
        record, dag = run_workflow(dag, executor)

        # SimulatedAdapter returns total_results=2, so urgent_path condition fails
        assert dag.get_task("urgent_path").status == TaskStatus.BLOCKED
        # normal_path has no condition → should execute
        assert dag.get_task("normal_path").status == TaskStatus.SUCCEEDED


# ====================================================================
# 2. Skip Conditions
# ====================================================================

class TestSkipConditions:
    """Test that skip_if conditions cause tasks to be skipped."""

    def test_skip_if_met(self, executor, seq_semantics):
        """When skip_if condition is true, task should be skipped."""
        spec = WorkflowSpec(
            name="skip_test", version="1.0.0",
            tasks=[
                WorkflowTask(id="search", capability="web_search@1.0.0",
                             input={"query": "test"}),
                WorkflowTask(id="analyze", capability="text_analyze@1.0.0",
                             input={"text": "${search.results}"},
                             skip_if="${search.total_results} == 0"),
            ],
            edges=[
                WorkflowEdge(from_task="search", to_task="analyze"),
            ],
            semantics=seq_semantics,
        )
        dag = WorkflowDAG(spec)
        record, dag = run_workflow(dag, executor)

        # total_results=2, so skip_if is false → analyze should run
        assert dag.get_task("analyze").status == TaskStatus.SUCCEEDED

    def test_skip_if_triggers(self, executor, seq_semantics):
        """When skip_if condition is true (total_results == 2), task should be skipped."""
        spec = WorkflowSpec(
            name="skip_trigger", version="1.0.0",
            tasks=[
                WorkflowTask(id="search", capability="web_search@1.0.0",
                             input={"query": "test"}),
                WorkflowTask(id="analyze", capability="text_analyze@1.0.0",
                             input={"text": "${search.results}"},
                             skip_if="${search.total_results} > 0"),
            ],
            edges=[
                WorkflowEdge(from_task="search", to_task="analyze"),
            ],
            semantics=seq_semantics,
        )
        dag = WorkflowDAG(spec)
        record, dag = run_workflow(dag, executor)

        # total_results=2 > 0, so skip_if is true → analyze should be skipped
        assert dag.get_task("analyze").status == TaskStatus.SKIPPED


# ====================================================================
# 3. Backward Compatibility
# ====================================================================

class TestBackwardCompatibility:
    """Workflows without conditions must behave exactly as before."""

    def test_standard_workflow_unchanged(self, executor, seq_semantics):
        """A workflow with no conditions should execute normally."""
        spec = WorkflowSpec(
            name="standard", version="1.0.0",
            tasks=[
                WorkflowTask(id="search", capability="web_search@1.0.0",
                             input={"query": "test"}),
                WorkflowTask(id="analyze", capability="text_analyze@1.0.0",
                             input={"text": "${search.results}"}),
                WorkflowTask(id="report", capability="report_generate@1.0.0",
                             input={"content": "${analyze.result}"}),
            ],
            edges=[
                WorkflowEdge(from_task="search", to_task="analyze"),
                WorkflowEdge(from_task="analyze", to_task="report"),
            ],
            semantics=seq_semantics,
        )
        dag = WorkflowDAG(spec)
        record, dag = run_workflow(dag, executor)

        assert record.status == ExecutionStatus.SUCCESS
        assert all(t.status == TaskStatus.SUCCEEDED for t in dag.spec.tasks)


# ====================================================================
# 4. DAG Condition Methods
# ====================================================================

class TestDAGConditionMethods:
    """Test the WorkflowDAG condition evaluation methods directly."""

    def test_should_skip_task_none(self):
        """With no skip_if, should_skip_task returns False."""
        spec = WorkflowSpec(
            name="test", version="1.0.0",
            tasks=[WorkflowTask(id="t1", capability="test@1.0")],
            edges=[],
        )
        dag = WorkflowDAG(spec)
        assert not dag.should_skip_task("t1", {})

    def test_evaluate_outbound_edges(self):
        """get_effective_dependents should filter by edge conditions."""
        spec = WorkflowSpec(
            name="test", version="1.0.0",
            tasks=[
                WorkflowTask(id="t1", capability="test@1.0"),
                WorkflowTask(id="t2", capability="test@1.0"),
                WorkflowTask(id="t3", capability="test@1.0"),
            ],
            edges=[
                WorkflowEdge(from_task="t1", to_task="t2",
                             condition="${t1.score} > 0.5"),
                WorkflowEdge(from_task="t1", to_task="t3"),
            ],
        )
        dag = WorkflowDAG(spec)
        outputs = {"t1": {"score": 0.3}}
        dependents = dag.get_effective_dependents("t1", outputs)
        dep_ids = [t.id for t in dependents]
        # t2 blocked by condition, t3 always passes
        assert "t3" in dep_ids
        assert "t2" not in dep_ids

    def test_has_satisfied_inbound_path_root(self):
        """Root tasks always have satisfied inbound paths."""
        spec = WorkflowSpec(
            name="test", version="1.0.0",
            tasks=[WorkflowTask(id="root", capability="test@1.0")],
            edges=[],
        )
        dag = WorkflowDAG(spec)
        assert dag.has_satisfied_inbound_path("root", {})

    def test_has_satisfied_inbound_path_blocked(self):
        """All inbound edges failing should return False."""
        spec = WorkflowSpec(
            name="test", version="1.0.0",
            tasks=[
                WorkflowTask(id="t1", capability="test@1.0"),
                WorkflowTask(id="t2", capability="test@1.0"),
            ],
            edges=[
                WorkflowEdge(from_task="t1", to_task="t2",
                             condition="${t1.flag} == true"),
            ],
        )
        dag = WorkflowDAG(spec)
        assert not dag.has_satisfied_inbound_path("t2", {"t1": {"flag": False}})

    def test_has_satisfied_inbound_path_no_condition(self):
        """Edge without condition always passes."""
        spec = WorkflowSpec(
            name="test", version="1.0.0",
            tasks=[
                WorkflowTask(id="t1", capability="test@1.0"),
                WorkflowTask(id="t2", capability="test@1.0"),
            ],
            edges=[WorkflowEdge(from_task="t1", to_task="t2")],
        )
        dag = WorkflowDAG(spec)
        assert dag.has_satisfied_inbound_path("t2", {"t1": {"x": 1}})
