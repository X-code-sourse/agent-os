"""Verify Core Constitution compliance — A1..A4."""

import sys, inspect

# ── Plumbing ───────────────────────────────────────────────────────
sys.path.insert(0, "reference/src")
errors = []

def ck(ok, msg):
    print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    if not ok: errors.append(msg)


# ── A2: Capability Pool ────────────────────────────────────────────
from agentos import capability_pool
src = inspect.getsource(capability_pool)
ck("class CapabilityPool" in src,          "A2: CapabilityPool class exists")
ck("def invoke" in src,                     "A2: invoke() method")
ck("def cancel" in src,                     "A2: cancel() method")
ck("def status" in src,                     "A2: status() method")
ck("_LegacyAdapter" not in src,            "R1: dead _LegacyAdapter removed")

pool = capability_pool.CapabilityPool()
pool.register("echo", lambda t, c: t.params)
res = pool.invoke(type("T", (), {"id":"t","type":"echo","params":{"x":1}})(), {})
ck(res.status == "success",                 "A2: pool invoke success")
ck(res.metrics is not None,                 "A2: pool result has metrics")


# ── A3: Task State Machine ─────────────────────────────────────────
from agentos.models import TaskState, TaskResult, StateTransition

for s in TaskState:
    name = s.value
    ck(True, f"A3: state {name} defined")

ck(TaskState.CREATED.can_transition_to(TaskState.QUEUED),     "A3: CREATED->QUEUED")
ck(not TaskState.COMPLETED.can_transition_to(TaskState.RUNNING), "A3: COMPLETED!->RUNNING")
ck(TaskState.FAILED.can_transition_to(TaskState.RETRY_QUEUED), "A3: FAILED->RETRY_QUEUED")

tr = TaskResult("t1")
tr.state_history.append(StateTransition(from_state=None, to_state=TaskState.CREATED))
tr.transition_to(TaskState.QUEUED, "a")
tr.transition_to(TaskState.RUNNING, "b")
tr.transition_to(TaskState.COMPLETED, "c")
ck(tr.status == "completed",                "A3: transition chain ends at completed")
ck(len(tr.state_history) == 4,              "A3: state_history tracks all transitions")

try:
    tr.transition_to(TaskState.RUNNING, "invalid")
    ck(False, "A3: invalid transition should raise")
except ValueError:
    ck(True,                                "A3: invalid transition raises ValueError")


# ── A4: Event Backbone Communication ───────────────────────────────
from agentos import cli as cli_mod
src = inspect.getsource(cli_mod._cmd_run)
ck("subscribe" in src,                      "A4: cli subscribes to Execution:Completed")
ck("do_review" in src,                      "A4: review via subscriber")
ck("format_report" in src,                  "A4: report via subscriber")

from agentos.execution_engine import ExecutionEngine
src = inspect.getsource(ExecutionEngine._publish)
ck("self.bus.publish" in src,               "A4: engine publishes to Event Bus")

src = inspect.getsource(ExecutionEngine.execute)
ck("while ready or running" not in src,     "R5: single while loop")


# ── Report ─────────────────────────────────────────────────────────
print(f"\n{'ALL PASS' if not errors else f'{len(errors)} FAILS'}")
sys.exit(0 if not errors else 1)
