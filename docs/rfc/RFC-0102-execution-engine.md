# RFC-0102: Execution Engine

**Status:** Draft
**Type:** Control Plane RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0001 v1.0, RFC-0002, RFC-0100 v1.0, RFC-0101 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Execution Engine** — the runtime heart of Agent OS. The Engine receives compiled Execution Plans from the Planner (RFC-0101), instantiates Tasks (RFC-0001), drives the Execution state machine, manages dependency resolution and context accumulation, and handles replan, cancel, and error propagation. It is the **sole scheduler** (Constitution Article 2) and must remain **stateless** (Constitution Article 1).

---

## 2. Motivation

The Execution Engine is the bridge between compile time and runtime:

- The **Planner** produces a static, compiled Execution Plan (RFC-0101)
- The **Task State Machine** defines how individual Tasks behave (RFC-0001)
- The **Execution Engine** is the runtime that connects the two — it instantiates Plans, tracks DAG-level dependencies, manages data flow between stages, triggers Reviewers, handles failures, and coordinates replanning

Without a defined Engine architecture:
- Who owns the dependency tracking for multi-stage DAGs? The Planner (compile time) or the Engine (runtime)?
- How does the Engine recover its state after a crash without violating the stateless Kernel constraint?
- Where does the Capability invocation boundary lie — does the Engine call Capabilities directly or through an intermediary?

---

## 3. Engine Architecture Overview

```
                              Execution Engine
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  PlanIngestor ←── receives ExecutionPlan from Planner               │
│       │                                                             │
│       ▼                                                             │
│  TaskFactory ──► instantiates Stages into Tasks (Created state)     │
│       │                                                             │
│       ▼                                                             │
│  DependencyTracker ──► tracks stage dependency completion           │
│       │                                                             │
│       ▼                                                             │
│  Scheduler ──► dispatches ready Tasks to Capability Pool            │
│       │                                                             │
│       ▼                                                             │
│  ContextManager ──► accumulates stage outputs for downstream input  │
│       │                                                             │
│       ▼                                                             │
│  LifecycleManager ──► drives Execution state machine                │
│       │                                                             │
│       ▼                                                             │
│  EventPublisher ──► publishes all state transitions to Event Bus    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │             State Recovery (from Event Store)                │    │
│  │  On startup: replay Events → rebuild active Executions       │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.1 Internal Module Responsibilities

| Module | Responsibility | Stateful? |
|--------|---------------|-----------|
| PlanIngestor | Receives ExecutionPlan from Planner, validates it, initiates Execution | No (pure transform) |
| TaskFactory | Converts Plan stages into Task instances (RFC-0001 Created state) | No (pure transform) |
| DependencyTracker | Maintains the per-Execution dependency graph; emits `Ready` signals when a stage's dependencies are all satisfied | Yes (in-memory, rebuildable from Event stream) |
| Scheduler | Receives `Ready` signals, assigns Tasks to Capabilities via Capability Pool, manages concurrency | Yes (in-memory queue, rebuildable) |
| ContextManager | Accumulates stage outputs into the context object (RFC-0100 §4.4); provides input to downstream Tasks | Yes (in-memory, rebuildable) |
| LifecycleManager | Drives Execution state machine (RFC-0001 §5); decides transitions between Created → Resolving → Running → GlobalReview → terminal | No (state machine logic is pure; current state is stored in DependencyTracker) |
| EventPublisher | Listens to all internal state changes and publishes Events to Event Bus | No |

**Stateless guarantee:** The four stateful modules (DependencyTracker, Scheduler, ContextManager, LifecycleManager) are **rebuilt from the Event Store** on restart. They hold no persistent state of their own — their state is a projection of the Event stream.

---

## 4. Plan Consumption → Task Scheduling

### 4.1 Plan Ingest Flow

```
Planner
    │
    │  ExecutionPlan (RFC-0100 §10 format)
    ▼
Execution Engine
    │
    ├─ 1. PlanIngestor.validate(plan) → valid/invalid
    │      Checks: all stages have capability_bindings,
    │              all dependency references exist,
    │              output_schema is valid
    │
    ├─ 2. LifecycleManager.createExecution(plan) → Execution (state: Created)
    │      Publishes: Execution:Created
    │
    ├─ 3. TaskFactory.instantiate(plan, execution_id) → Task[]
    │      For each stage in plan.stages:
    │        Task = {
    │          task_id: task://<execution_id>/<sequence>,
    │          stage_id: stage.id,
    │          type: stage.type,
    │          execution_id: execution_id,
    │          state: Created,
    │          requirements: stage.requirements,
    │          capability_binding: stage.capability_binding,
    │          input: stage.input,
    │          config: stage.config,
    │          max_retries: stage.max_retries,
    │          retry_policy: stage.retry_policy,
    │          replan_allowed: stage.replan_allowed
    │        }
    │      Publishes: Task:Created (for each Task)
    │
    ├─ 4. DependencyTracker.initialize(tasks, plan)
    │      Builds adjacency: graph[node] = [dependents]
    │      Builds reverse:   deps[node] = depends_on
    │      Identifies root stages (depends_on is empty)
    │      For each root stage: emit Ready
    │
    ├─ 5. LifecycleManager.transition(execution, Resolving → Running)
    │      Publishes: Execution:Running
    │
    └─ 6. Scheduler receives Ready signals → begins dispatching
```

### 4.2 Stage → Task Instantiation Rules

| Plan Stage Type | Instantiation | Task Type |
|----------------|---------------|-----------|
| `task_node` | 1 Task | `research`, `python`, etc. (from requirement) |
| `parallel_gate` | No Task (structural node) | N/A — gate passes Ready signal to children |
| `join_gate` | No Task (structural node) | N/A — gate waits for N signals before passing |
| `exclusive_gate` | No Task (structural node) | N/A — gate routes Ready to exactly one child |
| `inline_subworkflow` | Expanded recursively by Planner at compile time | N/A — stages already flattened in Plan |

**Rule:** Structural nodes (`parallel_gate`, `join_gate`, `exclusive_gate`) do not become Tasks. They exist only in the DependencyTracker as coordination points.

### 4.3 Dependency Tracking Algorithm

```python
# Pseudocode — the Engine's core scheduling loop

class DependencyTracker:
    def __init__(self, plan):
        self.remaining_deps = {}  # stage_id → set of incomplete dependency stage_ids
        self.ready_queue = Queue()  # stages whose dependencies are all satisfied

        for stage in plan.stages:
            self.remaining_deps[stage.stage_id] = set(stage.depends_on)
            if not stage.depends_on:
                self.ready_queue.push(stage.stage_id)

    def on_task_completed(self, stage_id, output):
        # Called when a Task transitions to Completed / CompletedWithWarning / Partial
        # Step 1: Find all stages that depend on this stage
        for dependent in self.reverse_adjacency[stage_id]:
            self.remaining_deps[dependent].discard(stage_id)
            if not self.remaining_deps[dependent]:
                self.ready_queue.push(dependent)

    def on_task_failed(self, stage_id):
        # Called when a Task transitions to Failed (terminal, no replan)
        # Propagate: all downstream dependents are cancelled
        downstream = self.get_all_downstream(stage_id)
        for dep in downstream:
            self.execution_engine.cancel_task(dep, f"dependency {stage_id} failed")

    def next_ready(self):
        if self.ready_queue:
            return self.ready_queue.pop()
        return None
```

### 4.4 Scheduler Dispatch

```
ReadySignal (from DependencyTracker)
    │
    ▼
Scheduler.dequeue()
    │
    ├─ 1. Pop next ready stage from priority queue
    │      Priority order (configurable via Profile):
    │        a) Critical path stages (longest chain) — higher priority
    │        b) Stages with no parallelism constraints
    │        c) FIFO fallback
    │
    ├─ 2. Task.transition(Queued → Assigned)
    │      Publishes: Task:Queued, Task:Assigned
    │
    ├─ 3. CapabilityPool.invoke(task)
    │      See §4.5
    │
    └─ 4. Monitor for result:
         ├─ On output: → Task:Running → Task:WaitingReview
         ├─ On partial: → Task:Partial
         └─ On error: → Task:RetryQueued or Task:Failed
```

### 4.5 Capability Invocation

The Engine does **not** call Capabilities directly. It invokes through the **Capability Pool** — a Runtime Plane component that manages Capability instances:

```
Scheduler ──► CapabilityPool.invoke(task)
                    │
                    ├─ 1. Lookup capability instance from binding:
                    │       capability_id = task.capability_binding.capability_id
                    │
                    ├─ 2. Check instance availability:
                    │       if busy: queue the invocation
                    │       if available: allocate instance
                    │
                    ├─ 3. Execute:
                    │       capability_instance.execute(task.input, task.config)
                    │
                    └─ 4. Return result to Engine:
                         ├─ Capability:OutputProduced → run review
                         ├─ Capability:PartialOutput  → run partial review
                         └─ Capability:Error          → retry or fail
```

**Engine ↔ Capability Pool contract:**
```
Engine → Pool:   invoke(task_id, capability_id, input, config, deadline) → invocation_id
Pool → Engine:   on_output(invocation_id, output)
Pool → Engine:   on_partial(invocation_id, output, completeness)
Pool → Engine:   on_error(invocation_id, error)
Pool → Engine:   on_timeout(invocation_id)
```

---

## 5. Context Accumulation

### 5.1 Context Object

The ContextManager maintains a per-Execution context object (RFC-0100 §4.4).

```
Execution Context
├── execution_id
├── goal (original user goal text)
├── intent (structured intent)
├── profile (resolved profile config)
├── stages: {
│       <stage_id>: {
│           status: "pending" | "running" | "completed" | "failed" | "skipped",
│           output: <stage output or null>,
│           completed_at: <timestamp or null>
│       }
│   }
└── accumulated: {
        # Computed: all completed stage outputs merged
    }
```

### 5.2 Context Merging Rules

When a stage completes, its output is merged into the accumulated context:

```
def merge_context(context, stage_id, output):
    context.stages[stage_id] = {
        "status": "completed",
        "output": output,
        "completed_at": now()
    }

    # The "current" field for the next downstream stage includes:
    #   - All completed stage outputs keyed by stage_id
    #   - A synthesized "current" object with the most relevant values
    context.accumulated = synthesize(context.stages)
```

### 5.3 Downstream Input Construction

When a downstream Task is dispatched, the ContextManager constructs its input:

```json
{
  "task_id": "task://exec_001/004",
  "stage_id": "valuation_analysis",
  "input": {
    # Explicit input_template from Plan (if any), with template variables resolved
    "company": "{context.stages.company_identification.output.company}",
    "financials": "{context.stages.financial_analysis.output}",
    "news": "{context.stages.news_analysis.output}"
  },
  "context": {
    # Full context for downstream reference
    "previous_stages": ["company_identification", "financial_analysis", "news_analysis"],
    "session_id": "session_abc",
    "profile_id": "profile://finance/deep@1.0.0"
  }
}
```

Template resolution uses `{context.stages.<stage_id>.output.<path>}` syntax.

---

## 6. Execution Lifecycle Management

### 6.1 Execution State Machine Driver

The LifecycleManager drives the Execution state machine (RFC-0001 §5) based on aggregate Task states:

```
Execution:Created
    │ Plan validated and Tasks instantiated
    ▼
Execution:Resolving
    │ All dependency lookups complete
    ▼
Execution:Running
    │
    ├── [All Tasks in terminal state] ──────────────────────────┐
    │                                                           │
    │   ┌─ All Completed/CompletedWithWarning/Skipped ──► GlobalReview  ──► Completed / CompletedWithWarning
    │   │                                                                        │
    │   └─ Any Failed (terminal, no replan) ──► GlobalReview (partial) ──► Failed
    │                                                                        
    ├── [ReplanRequested emitted by a Task] ──► Replanning
    │       │ Planner produces ReplacementPlan
    │       ├── success → Running (with new stages)
    │       └── failure → Failed
    │
    └── [External cancel signal] ──► Cancelled
```

### 6.2 Aggregate State Computation

The Engine computes the Execution's aggregate state from its Tasks' states:

```
ALL Tasks in [Completed, CompletedWithWarning, Skipped, Cancelled, Archived]:
    → All Clean: GlobalReview
    → Any Failed: GlobalReview (with degraded scope) → Failed

ANY Task in [Running, WaitingReview, Reviewed, Queued, Assigned]:
    → Running

ANY Task in [ReplanRequested]:
    → Replanning

NO Tasks (all pruned or all structural nodes):
    → Empty Execution → Completed (no-op)
```

### 6.3 Run-to-Completion Guarantee

The Engine guarantees that every Execution reaches a terminal state. If the Engine crashes:

1. On restart, the Engine replays Events from the Event Store (see §9)
2. All in-flight Tasks that were Running at crash time receive a `Capability:Timeout` (deadline exceeded)
3. The Engine resumes from the last known state and continues driving toward termination

---

## 7. Replan Protocol Implementation

### 7.1 Replan Trigger

When a Task's `retry_count >= max_retries` and `replan_allowed == true`:

```
1. Task transitions to Failed
2. Engine calls RetryDecider:
      retry_count >= max_retries AND replan_allowed → emit ReplanRequested
3. Engine publishes: Task:ReplanRequested
```

### 7.2 Replan Flow

```
Engine                                    Planner
  │                                         │
  │  Task:ReplanRequested                   │
  │  (within Execution:Running)             │
  │                                         │
  ├─ LifecycleManager.transition(           │
  │      Running → Replanning)              │
  │  Publishes: Execution:Replanning        │
  │                                         │
  ├─ Cancel all unstarted downstream Tasks  │
  │  (Tasks in Queued/Assigned state)       │
  │  Publishes: Task:Cancelled (per Task)   │
  │                                         │
  ├─ Freeze ContextManager state            │
  │  (completed outputs are preserved)      │
  │                                         │
  ├── ReplanRequest ─────────────────────►  │
  │   { execution_id,                       │  [Planner re-enters pipeline,
  │     failed_stage_id,                    │   §5 of RFC-0101]
  │     remaining_stages:                   │
  │       [stages not yet started],         │
  │     completed_outputs: {                │
  │       <stage_id>: <output>              │
  │     }                                   │
  │   }                                     │
  │                                         │
  │◄── ReplacementPlan ───────────────────│  │
  │   { execution_id,                       │
  │     new_stages: [...],                  │
  │     inherited_context: {...},           │
  │     plan_type: "replacement"            │
  │   }                                     │
  │                                         │
  ├─ Unfreeze ContextManager                │
  ├─ TaskFactory.instantiate(new_stages)    │
  ├─ DependencyTracker.merge(new_stages)    │
  ├─ LifecycleManager.transition(           │
  │      Replanning → Running)              │
  │  Publishes: Execution:Running           │
  │                                         │
  └─ Scheduler resumes dispatching          │
```

### 7.3 Replan Safety

- `replan_count` is tracked in the Execution metadata (RFC-0001 §8.4)
- If `replan_count >= max_replans` (default: 3), Engine rejects further replans and transitions Execution to `Failed`
- Replan loops are flagged as an `Execution:ReplanLoopDetected` event for Loop analysis

---

## 8. Cancel Propagation

### 8.1 Single Task Cancel

```
Engine LifecycleManager
    │
    ├─ 1. Publish Task:CancelQueued
    │
    ├─ 2. If Task is Running: signal Capability Pool to cancel invocation
    │      Pool responds with Capability:CancelAcknowledged
    │
    ├─ 3. Task transitions: Running → CancelQueued → Cancelled
    │      Publishes: Task:Cancelled
    │
    └─ 4. DependencyTracker.on_task_cancelled(stage_id)
          → propagate to dependents (see below)
```

### 8.2 Cascading Cancel

When a Task fails terminally (retries exhausted, `replan_allowed == false`):

```
DependencyTracker.on_task_failed(stage_id)
    │
    ├─ 1. Find all transitive downstream stages:
    │       downstream = get_all_downstream(stage_id)
    │
    ├─ 2. For each downstream stage:
    │       if stage.state in [Queued, Assigned, Running]:
    │           Engine.cancel_task(stage.stage_id, "dependency {stage_id} failed")
    │       if stage.state in [WaitingReview, Reviewed]:
    │           Engine.transition(stage, WaitingReview → Cancelled)
    │       (Skipped and Archived stages are already terminal — no action needed)
    │
    └─ 3. After all cancels complete:
           LifecycleManager.evaluate_remaining_graph()
           If no remaining Tasks can proceed → Execution:Failed
```

### 8.3 Partial Cancel (Replan)

During replan, only **unstarted** downstream Tasks are cancelled:

```
ReplanCancel:
    │  For each downstream stage of the failed stage:
    │      if stage.state in [Queued, Assigned]:
    │          cancel_task(stage.stage_id, "replan")
    │      if stage.state in [Running, WaitingReview, Reviewed]:
    │          LET RUN — their outputs may still be useful
    │          (The replacement Plan will decide whether to reuse or discard them)
```

---

## 9. Reviewer Runtime Integration

### 9.1 Local Reviewer Trigger

The Engine triggers the Local Reviewer automatically when a Task produces output:

```
Task:Running
    │ Capability produces output
    ▼
Engine: receives Capability:OutputProduced
    │
    ▼
1. Engine transitions Task: Running → WaitingReview
   Publishes: Task:WaitingReview

2. Engine sends review request to Local Reviewer:
   REVIEW: {
       task_id, stage_id, input, output,
       constraints: [from Rule injection in Plan],
       quality_threshold: [from Profile],
       capability_schema: [from Capability Manifest]
   }

3. Reviewer returns:
   REVIEW_RESULT: {
       result: "pass" | "pass_with_warnings" | "fail",
       score: 0.92,
       constraint_results: [...]
   }

4. Engine applies result to Task state machine:
   ├─ pass           → Task:Completed
   ├─ pass_with_warnings → Task:CompletedWithWarning
   └─ fail           → Task:ReviewFailed → retry or fail
```

### 9.2 Global Reviewer Trigger

When all Tasks reach terminal states, the Engine triggers the Global Reviewer:

```
DependencyTracker: all Tasks terminal
    │
    ▼
LifecycleManager: Execution:Running → Execution:GlobalReview
    │
    ▼
Engine sends full execution output to Global Reviewer:
    REVIEW: {
        execution_id,
        workflow_ref,
        all_stage_outputs: {<stage_id>: <output>},
        rules_applied: [...],
        profile_ref,
        completeness: {
            stages_successful: N,
            stages_skipped: N,
            stages_partial: N,
            stages_failed: N
        }
    }
    │
    ▼
Reviewer returns:
    REVIEW_RESULT: {
        result: "pass" | "pass_with_warnings" | "fail",
        score: 0.91,
        checks: [...]
    }
    │
    ▼
Engine applies result:
    ├─ pass              → Execution:Completed
    ├─ pass_with_warnings → Execution:CompletedWithWarning
    └─ fail              → Execution:Failed
```

### 9.3 Reviewer Failure Handling

If the Reviewer itself fails (crashes, timeout):

```
REVIEWER_FAILURE:
    ├─ Local: Task returns to Running state for retry
    │      Task publishes: Task:Running (re-review)
    │      Up to 1 retry, then treat as review_failed
    │
    └─ Global: Execution stays in GlobalReview state
           Engine retries once, then transitions to Failed
```

---

## 10. Engine State Recovery (Stateless Kernel)

### 10.1 The Problem

Constitution Article 1 requires the Kernel to be stateless. Yet the Engine has four modules that inherently hold runtime state (DependencyTracker, Scheduler, ContextManager, LifecycleManager).

**Resolution:** These modules hold **ephemeral state** — state that can be reconstructed from the Event Store. The Engine does not persist its own state; it relies on the Event Store as the source of truth.

### 10.2 Recovery Flow

```
Engine Crash
    │
    ▼
Engine Restart
    │
    ├─ 1. Connect to Event Store
    │
    ├─ 2. Query: all Events where execution.state != terminal
    │      SELECT * FROM events
    │      WHERE event_type IN ('Execution:Created', 'Execution:Running', ...)
    │      AND execution_id NOT IN (
    │          SELECT execution_id FROM events
    │          WHERE event_type IN ('Execution:Completed', 'Execution:Failed', 'Execution:Cancelled')
    │      )
    │
    ├─ 3. For each active Execution:
    │      a) Replay all events for that execution_id, in order
    │      b) Rebuild: DependencyTracker state (completed/failed stages)
    │      c) Rebuild: ContextManager state (accumulated outputs)
    │      d) Rebuild: LifecycleManager state (current Execution state)
    │      e) Rebuild: Scheduler queue (queued Tasks)
    │
    ├─ 4. For each Task in Running state at time of crash:
    │      a) Publish Capability:Timeout (deadline exceeded)
    │      b) Task transitions: Running → Failed → RetryQueued or Failed
    │
    ├─ 5. Resume Execution: LifecycleManager continues driving
    │      from recovered state
    │
    └─ 6. Publish Execution:Recovered
            { execution_id, tasks_recovered: N, tasks_lost: N }
```

### 10.3 Recovery Guarantees

| State at Crash | Recovery Action | Data Loss? |
|----------------|----------------|------------|
| Task in Created/Queued/Assigned | Re-queue from DependencyTracker | None |
| Task in Running | Timeout → Retry/Fail | Output lost (non-durable) |
| Task in WaitingReview | Re-review (output available in Event Store) | None |
| Task in Reviewed/Completed | State restored from Event | None |
| Execution in Created/Resolving | Restart from Event replay | None |
| Execution in Running | Resume from last Event | None |
| Execution in GlobalReview | Re-trigger Global Review | None |

### 10.4 Checkpointing (Performance Optimization)

For long-running Executions with many events, full replay may be slow. Optional snapshot mechanism:

```
Every N events (configurable, default: 100), the Engine persists a
**StateSnapshot** to the Data Plane:
    { execution_id, snapshot_at, engine_state: { ... } }

On recovery:
    ├─ Load latest snapshot (if exists)
    └─ Replay only events after snapshot
    → Reduces recovery time for long-running Executions

The snapshot is NEVER the source of truth — the Event Store is.
The snapshot is a performance optimization only.
```

---

## 11. Engine API

### 11.1 Public Interface (consumed by Kernel and external triggers)

```json
// Submit an Execution Plan for execution
POST /engine/execute
{
  "plan": { /* ExecutionPlan from RFC-0100 §10 */ },
  "execution_id": "exec://finance/...",
  "session_id": "session://...",
  "activate_immediately": true
}
→ { "execution_id", "status": "created" }


// Cancel an active Execution
POST /engine/cancel
{
  "execution_id": "exec://finance/...",
  "reason": "user_requested"
}
→ { "execution_id", "status": "cancelling" }


// Get Execution status
GET /engine/status?execution_id=exec://finance/...
→ {
    "execution_id",
    "state": "running",
    "task_summary": { "total": 6, "completed": 2, "running": 1, ... },
    "replan_count": 0,
    "started_at": "...",
    "estimated_remaining_ms": 15000
  }


// Recover all active Executions after restart
POST /engine/recover
→ {
    "executions_recovered": 3,
    "tasks_recovered": 12,
    "tasks_lost": 1,
    "recovery_duration_ms": 450
  }
```

### 11.2 Internal Events (subscribed from Event Bus)

| Event | Consumer | Action |
|-------|----------|--------|
| `Capability:OutputProduced` | LifecycleManager | Transition Task: Running → WaitingReview; trigger Local Reviewer |
| `Capability:PartialOutput` | LifecycleManager | Transition Task: Running → Partial |
| `Capability:Error` | LifecycleManager | Transition Task: Running → Failed; evaluate retry |
| `Capability:Timeout` | LifecycleManager | Transition Task: Running → Failed; evaluate retry |
| `Reviewer:LocalResult` | LifecycleManager | Apply review result to Task state machine |
| `Reviewer:GlobalResult` | LifecycleManager | Apply global review result to Execution state machine |
| `Planner:ReplacementPlan` | PlanIngestor | Receive new Plan; merge into running Execution |
| `User:CancelExecution` | LifecycleManager | Cancel execution and all its Tasks |

### 11.3 Published Events (to Event Bus)

The Engine publishes all events defined in RFC-0001 §6.1 (Task events) and §6.2 (Execution events). Additionally:

| Event | Trigger | Payload |
|-------|---------|---------|
| `Execution:Recovered` | Engine restart replay complete | `execution_id`, `tasks_recovered`, `tasks_lost` |
| `Execution:ReplanLoopDetected` | `replan_count >= max_replans` | `execution_id`, `replan_count`, `failed_stages[]` |
| `Scheduler:QueueDeep` | Queue depth > threshold (monitoring) | `execution_id`, `queue_depth`, `oldest_enqueued_at` |

---

## 12. Compliance

Any implementation claiming Agent OS Execution Engine compatibility **must**:

1. Implement the Plan Ingest flow defined in §4, including all 6 steps
2. Implement the DependencyTracker algorithm defined in §4.3
3. Implement the ContextManager with merge rules defined in §5
4. Drive the Execution state machine as defined in §6
5. Implement the Replan protocol as defined in §7, including the Engine ↔ Planner communication flow
6. Implement cascading cancel propagation as defined in §8
7. Trigger Local and Global Reviewers as defined in §9
8. Implement stateless recovery from Event Store as defined in §10
9. Invoke Capabilities through a Capability Pool (not directly)
10. Publish all state transition Events defined in §11.3

---

## 13. Open Questions

1. **Concurrency limits** — should the Engine support per-Workflow or per-Capability concurrency limits? If so, where is the limit configured (Profile? Plan? Registry?)
2. **Priority scheduling** — should Users or Profiles be able to specify execution priority (e.g., "this execution preempts that execution")?
3. **Snapshot strategy** — what is the optimal checkpoint interval for the state snapshot mechanism (§10.4)?
4. **Capability Pool architecture** — should the Pool be part of the Engine process or a separate service? (Deferred to RFC-0203: Runtime Scheduling)
5. **Execution timeout** — should Executions have a max wall-clock time? What happens when exceeded?

---

## 14. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.4 | Task entity |
| SPEC-0000 §3.10 | Execution entity |
| SPEC-0000 §3.15 | Session entity (scope for execution) |
| SPEC-0000 §3.16 | Execution Plan entity (Engine input) |
| RFC-0001 §3 | Task State Machine (all transitions Engine must drive) |
| RFC-0001 §4.3 | Replan Decision |
| RFC-0001 §5 | Execution State Machine |
| RFC-0001 §6 | Event schema (all events Engine must publish) |
| RFC-0001 §8.3 | Failure Propagation |
| RFC-0001 §8.4 | Replan Loops |
| RFC-0100 §4.4 | Data flow between stages (ContextManager) |
| RFC-0100 §10 | Execution Plan format (Engine input) |
| RFC-0101 §3 | Planner Compiler Pipeline |
| RFC-0101 §5 | Replan Protocol (Engine ↔ Planner) |
| ADR-0001 | Event Sourcing |
| Constitution Article 1 | Kernel must be stateless |
| Constitution Article 2 | Execution Engine is sole scheduler |
| Constitution Article 4 | All cross-module communication via Event Backbone |
