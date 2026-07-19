# RFC-0001: Execution Semantics

**Status:** Draft
**Type:** Foundation RFC
**RFC-INDEX:** Foundation / RFC-0001
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0 (Core Concepts & Object Model)
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **execution semantics** of the Agent OS runtime — how Tasks transition through states, how Executions progress, and what each terminal result means. It answers the question: **"What does it mean for something to succeed, fail, or partially complete?"**

---

## 2. Motivation

Without formal execution semantics, every module (Reviewer, Loop, Planner) develops its own interpretation of success and failure. This leads to inconsistent retry logic, ambiguous audit trails, and difficulty reasoning about system behavior.

This RFC establishes a single, authoritative model that all modules must follow.

---

## 3. Task State Machine (Formal Definition)

### 3.1 States

Every Task in Agent OS exists in exactly one of the following states at any point in time:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TASK STATE MACHINE                           │
│                                                                     │
│  [Created] ──► [Queued] ──► [Assigned] ──► [Running]               │
│                                                    │              │
│                                           ┌────────┴────────┐     │
│                                           │                 │     │
│                                           ▼                 ▼     │
│                                    [WaitingReview]      [Failed]   │
│                                           │                 │     │
│                                   ┌───────┴───────┐   ┌───┴───┐  │
│                                   │               │   │       │  │
│                                   ▼               ▼   ▼       ▼  │
│                              [Reviewed]    [PendingReview]  [Retry│
│                                   │               │      Queued] │
│                                   │               │       │     │
│                              ┌────┴──┐            │       │     │
│                              │       │            ▼       ▼     │
│                              ▼       ▼       [Pending     [Queued]
│                         [Completed] [Review Queued]             │
│                              │     Failed]        │            │
│                              │           │        │            │
│                         ┌────┴──┐  ┌────┴──┐      │            │
│                         │       │  │       │       │            │
│                         ▼       ▼  ▼       ▼      │            │
│                    [Completed] [Partial] [Failed] ─┤            │
│                    [WithWarning]         │         │            │
│                         │                ├── [RetryQueued]      │
│                         │                └── [ReplanRequested]  │
│                         │                              │        │
│                         │                    ┌─────────┴──┐     │
│                         │                    │            │     │
│                         ▼                    ▼            ▼     │
│                    [Archived]          [CancelQueued]  [Archived]│
│                                              │                  │
│                                              ▼                  │
│                                        [Cancelled]              │
│                                              │                  │
│                                              ▼                  │
│                                        [Archived]               │
│                                                                  │
│              [Skipped] ──► [Archived]                            │
└─────────────────────────────────────────────────────────────────────┘
```

| State | Definition | Terminal? |
|-------|------------|-----------|
| `Created` | Task has been instantiated by Planner as part of an Execution Plan. Not yet scheduled. | No |
| `Queued` | Task is in the Execution Engine's scheduling queue, awaiting capacity. | No |
| `Assigned` | A Capability instance has been selected via Capability Negotiation. Execution pending. | No |
| `Running` | Capability is actively executing the Task. | No |
| `WaitingReview` | Capability has produced output. Awaiting local Reviewer evaluation. | No |
| `Reviewed` | Local Reviewer has evaluated the output. Result pending routing. | No |
| `ReviewFailed` | Local Reviewer determined output does not meet quality/constraint thresholds. | No |
| `Completed` | Task executed successfully, passed Review, output is valid. | Yes |
| `CompletedWithWarning` | Task executed, passed Review, but one or more non-critical warnings were raised. | No (→ Archived) |
| `Partial` | Task produced partial output before a non-critical interruption. Output carries `completeness` (0.0–1.0) and `usable_for[]`. | Yes |
| `Failed` | Task terminated with an unrecoverable error. | No (until routed) |
| `RetryQueued` | Task will be retried (up to `max_retries`). Re-enters the queue. | No |
| `ReplanRequested` | The Execution Engine has determined that the DAG needs structural modification. Planner must generate a new Plan. | No |
| `CancelQueued` | Task cancellation has been initiated (e.g., due to ReplanRequest). Awaiting orderly shutdown. | No |
| `Cancelled` | Task was terminated before completion. Not a failure — intentional stop. | Yes |
| `Skipped` | Task was never started because its condition evaluated to false at runtime (dynamic pruning). | Yes |
| `Archived` | Task record retained for audit/replay. No further processing possible. | Yes |
| `PendingReview` | Task output is being held because a downstream dependency failed and replan resolution is pending. | No |
| `PendingQueued` | Task released from PendingReview or dependency hold, returning to queue. | No |

### 3.2 Transitions (Formal Rules)

Each transition is defined by: `(current_state, trigger, preconditions) → next_state`

| # | From | To | Trigger | Preconditions |
|---|------|----|---------|---------------|
| T1 | Created | Queued | `ExecutionPlan:Activated` | Task is part of an activated Execution |
| T2 | Queued | Assigned | `Capability:NegotiationComplete` | Capability capacity available, Negotiation succeeded |
| T3 | Assigned | Running | `Capability:Execute` | Capability accepted the invocation |
| T4 | Running | WaitingReview | `Capability:OutputProduced` | Output conforms to Capability Contract schema |
| T4.5 | Running | Partial | `Capability:PartialOutput` | Non-critical interruption; partial output available with `completeness` field |
| T5 | Running | Failed | `Capability:Error` | Error is non-retryable (see §4) |
| T6 | Running | Failed | `Capability:Timeout` | Execution exceeded `max_duration` for the Task |
| T7 | WaitingReview | Reviewed | `Reviewer:EvaluationComplete` | Local Reviewer produced a result |
| T7.5 | WaitingReview | PendingReview | `Dependency:Failed` | A downstream dependency failed; review result held pending replan decision |
| T8 | Reviewed | Completed | `Reviewer:Result == pass` | All required constraints satisfied |
| T9 | Reviewed | CompletedWithWarning | `Reviewer:Result == pass_with_warnings` | All required constraints satisfied, some warnings raised |
| T10 | Reviewed | ReviewFailed | `Reviewer:Result == fail` | One or more required constraints violated |
| T11 | ReviewFailed | RetryQueued | `RetryDecider:retry == true` | `retry_count < max_retries` |
| T12 | ReviewFailed | Failed | `RetryDecider:retry == false` | `retry_count >= max_retries` or non-retryable failure |
| T13 | Failed | RetryQueued | `RetryDecider:retry == true` | Failure is `RetryableFailure` (§4) AND `retry_count < max_retries` |
| T14 | Failed | ReplanRequested | `ExecutionEngine:decide_replan` | Failure is non-retryable OR retries exhausted, and replan may resolve |
| T15 | Failed | Cancelled | `ExecutionEngine:decide_cancel` | Failure is non-retryable, replan not appropriate, Execution terminating |
| T16 | ReplanRequested | CancelQueued | `ExecutionEngine:issue_cancel` | All dependent Tasks in the same Execution must be cancelled |
| T17 | ReplanRequested | Archived | `ExecutionEngine:archive_dag` | Entire DAG is being replaced by Planner; this Task is obsolete |
| T18 | CancelQueued | Cancelled | `Capability:CancelAcknowledged` | Capability has stopped execution (or was never started) |
| T18.5 | Partial | Archived | `Execution:Complete` | Execution has reached a terminal state |
| T19 | RetryQueued | Queued | `ExecutionEngine:requeue` | Retry counter incremented, Task re-enters scheduling |
| T20 | Completed | Archived | `Execution:Complete` | Execution has reached a terminal state |
| T20.5 | CompletedWithWarning | Archived | `Execution:Complete` | Execution has reached a terminal state |
| T21 | Cancelled | Archived | `Execution:Complete` | Execution has reached a terminal state |
| T22 | Skipped | Archived | `Execution:Complete` | Execution has reached a terminal state |
| T23 | WaitingReview | ReviewFailed | `Reviewer:Timeout` | Reviewer did not respond within configured deadline |
| T24 | Running | CancelQueued | `ExecutionEngine:issue_cancel` | Downstream dependency replan triggered upstream cancel |
| T25 | Queued | Skipped | `ExecutionEngine:skip_condition` | Task's `condition` expression evaluated to false at dispatch time |
| T26 | PendingReview | PendingQueued | `Dependency:Resolved` | Blocking dependency (e.g., replan decision) is resolved |
| T27 | PendingQueued | Queued | `ExecutionEngine:requeue` | Re-enters standard scheduling |

### 3.3 Task Metadata (per-EC)

Every Task carries the following execution metadata:

```json
{
  "task_id": "task://exec_001/003",
  "state": "running",
  "state_history": [
    { "state": "created", "at": "2026-07-19T10:00:05Z" },
    { "state": "queued", "at": "2026-07-19T10:00:06Z" },
    { "state": "assigned", "at": "2026-07-19T10:00:07Z" },
    { "state": "running", "at": "2026-07-19T10:00:08Z" }
  ],
  "retry_count": 0,
  "max_retries": 3,
  "retry_policy": {
    "backoff": "exponential",
    "initial_delay_ms": 1000,
    "max_delay_ms": 30000
  },
  "created_at": "2026-07-19T10:00:05Z",
  "last_transition_at": "2026-07-19T10:00:08Z",
  "cost_accumulated": { "tokens": 15000, "api_calls": 4, "usd": 0.06 }
}
```

---

## 4. Execution Result Semantics

Every Task terminates in exactly one result classification. These classifications drive the Execution Engine's decision logic.

### 4.1 Result Classifications

| Classification | Definition | Retryable? | Example |
|---------------|------------|------------|---------|
| `Completed` | Task executed successfully AND passed all Reviewer constraints. Output is valid for downstream consumption. | N/A | Research found 20 relevant news articles, cited correctly |
| `CompletedWithWarning` | Task executed successfully AND passed all *required* constraints, but one or more *warning-level* constraints were violated. Output is valid but degraded. | N/A | Research found 20 articles but only 3 of 5 required sources |
| `Partial` | Task produced partial output before a non-critical failure. Some downstream Tasks may proceed with reduced scope, others must wait. | Configuration-dependent | Research found 15 articles before API rate limit; CEO info available but financial data incomplete |
| `RetryableFailure` | Task failed due to a transient condition. Retrying with the same input may succeed. | Yes | API timeout, temporary network error, Capability crashed and restarted |
| `FatalFailure` | Task failed due to a permanent condition. Retrying with the same input will produce the same failure. | No | Invalid input, Capability not found, authentication failure, constraint violation that cannot be resolved |
| `Cancelled` | Task was intentionally terminated before completion. Not a failure. | No | User cancelled, Execution replanned, upstream dependency removed |
| `Skipped` | Task was never started because its condition evaluated to false. | No | User asked "who is CEO" — financial_analysis Task condition was false, skipped automatically |

### 4.2 Retry Policy

Every Task declares a retry policy:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_retries` | 3 | Maximum number of automatic retry attempts |
| `backoff` | `exponential` | Backoff strategy: `fixed`, `exponential`, `linear` |
| `initial_delay_ms` | 1000 | Delay before first retry |
| `max_delay_ms` | 30000 | Maximum delay between retries |
| `retryable_errors` | `["timeout", "rate_limit", "temporary"]` | Error classes that trigger retry |

**Backoff formula (exponential):**
```
delay = min(initial_delay_ms * 2^retry_count, max_delay_ms)
```

### 4.3 Replan Decision

When a Task reaches `FatalFailure` or exhausts retries, the Execution Engine must decide:

```
IF replan_candidate(Task) == true AND execution.state == 'running':
    emit ReplanRequested
ELSE:
    propagate failure to Execution
```

A Task is a replan candidate if:
- Its Workflow stage declares `replan_allowed: true` (default: false)
- The failure is structural (missing capability, invalid input) rather than logical (wrong answer)
- The Execution is not already in a replan cycle

---

## 5. Execution State Machine

An Execution (the entire run of an Execution Plan) has its own lifecycle:

```
[Created] ──► [Resolving] ──► [Running] ──► [GlobalReview] ──► [Completed]
                                                  │
                                                  ├──► [CompletedWithWarning]
                                                  │
                                                  └──► [Failed]

[Running] ──► [Replanning] ──► [Running] (cycle)
                    │
                    └──► [Failed]
```

| State | Definition | Terminal? |
|-------|------------|-----------|
| `Created` | Execution instantiated, Plan loaded. | No |
| `Resolving` | Workflow Resolver + Rule Manager resolving dependencies. | No |
| `Running` | Tasks being dispatched and executed. | No |
| `Replanning` | Planner generating a new DAG for the remaining Tasks. | No |
| `GlobalReview` | All Tasks completed. Global Reviewer evaluating the full output. | No |
| `Completed` | All Tasks passed. Global Review passed. Output delivered. | Yes |
| `CompletedWithWarning` | All Tasks completed. Global Review passed with warnings. | Yes |
| `Failed` | One or more failures could not be resolved by retry or replan. | Yes |
| `Cancelled` | User or system cancelled. | Yes |

### 5.1 Execution Transition Rules

| From | To | Condition |
|------|----|-----------|
| Created | Resolving | Plan is loaded and validated |
| Resolving | Running | All dependencies (Workflow, Rules, Profile) resolved |
| Running | GlobalReview | All Tasks in terminal state (Completed / CompletedWithWarning / Skipped / Cancelled) |
| Running | Replanning | A Task emitted `ReplanRequested` |
| Replanning | Running | Planner produced a new Plan; remaining Tasks reassigned |
| Replanning | Failed | Planner could not produce a valid new Plan |
| GlobalReview | Completed | Global Reviewer passed: all required constraints satisfied |
| GlobalReview | CompletedWithWarning | Global Reviewer passed with warnings |
| GlobalReview | Failed | Global Reviewer failed: one or more required constraints violated, or FatalFailure detected |
| (any) | Cancelled | User or Security Manager initiated cancellation |

### 5.2 Execution Metadata

```json
{
  "execution_id": "exec://finance/a1b2c3d4-...",
  "state": "running",
  "state_history": [
    { "state": "created", "at": "2026-07-19T10:00:00Z" },
    { "state": "resolving", "at": "2026-07-19T10:00:01Z" },
    { "state": "running", "at": "2026-07-19T10:00:05Z" }
  ],
  "task_summary": {
    "total": 6,
    "completed": 2,
    "failed": 0,
    "running": 1,
    "pending": 3,
    "skipped": 0,
    "cancelled": 0
  },
  "started_at": "2026-07-19T10:00:00Z",
  "cost_accumulated": { "tokens": 150000, "api_calls": 40, "usd": 0.60 },
  "replan_count": 0
}
```

---

## 6. Event Schema (State Transitions)

Every state transition MUST publish an Event. The Event Schema follows SPEC-0000 §3.9 with the following type hierarchy:

### 6.1 Task Events

| Event Type | Trigger | Key Payload Fields |
|------------|---------|-------------------|
| `Task:Created` | T1 | `task_id`, `execution_id`, `workflow_stage_id` |
| `Task:Queued` | T1, T19 | `task_id`, `queue_position`, `estimated_delay_ms` |
| `Task:Assigned` | T2 | `task_id`, `capability_id`, `capability_version` |
| `Task:Running` | T3 | `task_id`, `capability_id`, `model_used` |
| `Task:WaitingReview` | T4 | `task_id`, `output_summary`, `token_cost` |
| `Task:PendingReview` | T7.5 | `task_id`, `reason`, `dependency_failed_id` |
| `Task:Partial` | T4.5 | `task_id`, `completeness`, `usable_for[]`, `output_ref` |
| `Task:Reviewed` | T7 | `task_id`, `result` (pass/fail/warning), `score`, `issues[]` |
| `Task:ReviewFailed` | T10 | `task_id`, `violations[]`, `reviewer_id` |
| `Task:Completed` | T8 | `task_id`, `output_ref`, `duration_ms`, `cost` |
| `Task:CompletedWithWarning` | T9 | `task_id`, `output_ref`, `warnings[]`, `duration_ms` |
| `Task:Failed` | T5, T6, T12 | `task_id`, `error_code`, `error_detail`, `retry_count` |
| `Task:RetryQueued` | T11, T13 | `task_id`, `retry_attempt`, `next_retry_at` |
| `Task:ReplanRequested` | T14 | `task_id`, `reason`, `failed_node_context` |
| `Task:CancelQueued` | T16, T24 | `task_id`, `reason` |
| `Task:Cancelled` | T18 | `task_id`, `reason` |
| `Task:Skipped` | T25 | `task_id`, `condition_expression`, `condition_result` |
| `Task:Archived` | T20, T20.5, T18.5 | `task_id` |

### 6.2 Execution Events

| Event Type | Trigger | Key Payload Fields |
|------------|---------|-------------------|
| `Execution:Created` | — | `execution_id`, `plan_hash`, `workflow_ref` |
| `Execution:Resolving` | — | `execution_id`, `rules_loaded[]`, `profile_loaded` |
| `Execution:Running` | — | `execution_id`, `task_count` |
| `Execution:Replanning` | — | `execution_id`, `reason`, `tasks_affected[]` |
| `Execution:GlobalReview` | — | `execution_id`, `task_summary` |
| `Execution:Completed` | — | `execution_id`, `result_summary`, `total_cost` |
| `Execution:CompletedWithWarning` | — | `execution_id`, `warnings[]`, `total_cost` |
| `Execution:Failed` | — | `execution_id`, `failure_chain[]` (propagation path) |
| `Execution:Cancelled` | — | `execution_id`, `reason` |

### 6.3 Event Envelope

```json
{
  "event_id": "event://store-001/uuid",
  "event_type": "Task:Completed",
  "version": 1,
  "source": {
    "module": "execution-engine",
    "instance_id": "ee-001"
  },
  "payload": {
    "task_id": "task://exec_001/003",
    "output_ref": "event://store-001/event_047",
    "duration_ms": 3200,
    "cost": { "tokens": 45000, "api_calls": 12, "usd": 0.18 }
  },
  "context": {
    "execution_id": "exec://finance/a1b2c3d4-...",
    "session_id": "session_abc"
  },
  "timestamp": "2026-07-19T10:00:30.123Z"
}
```

---

## 7. Reviewer Integration

### 7.1 Local Reviewer

Each Task output passes through a **Local Reviewer** before the Task reaches a terminal state.

```
Task:Running
    │ Capability produces output
    ▼
Task:WaitingReview
    │ Local Reviewer evaluates against:
    │   1. Task-specific constraints (from Rule Manager)
    │   2. Capability Contract output schema
    │   3. Quality thresholds (from Profile)
    ▼
Task:Reviewed
    │
    ├─ [[All required constraints pass]] → Task:Completed (or CompletedWithWarning)
    │
    └─ [[Required constraint violated]] → Task:ReviewFailed → retry or fail
```

**Reviewer output schema:**
```json
{
  "reviewer_id": "reviewer://local/default",
  "task_id": "task://exec_001/003",
  "result": "pass_with_warnings",
  "score": 0.88,
  "threshold": 0.85,
  "constraint_results": [
    { "constraint_id": "rule://finance/sec-filing/v1.2.0/#primary_source", "status": "pass" },
    { "constraint_id": "rule://finance/sec-filing/v1.2.0/#filing_recency", "status": "pass" },
    { "constraint_id": "rule://finance/sec-filing/v1.2.0/#minimum_quarters", "status": "warning", "detail": "Only 3 of 4 quarters found" }
  ],
  "evaluated_at": "2026-07-19T10:00:28.456Z"
}
```

### 7.2 Global Reviewer

After all Tasks complete, a **Global Reviewer** evaluates the full execution output:

```
Execution:Running
    │ All Tasks in terminal state
    ▼
Execution:GlobalReview
    │ Global Reviewer evaluates:
    │   1. Cross-Task consistency
    │   2. Output completeness (all required sections present)
    │   3. Global constraints (from Rule Manager)
    │   4. Execution-level quality thresholds
    ▼
Execution:Completed / CompletedWithWarning / Failed
```

**Global Reviewer output schema:**
```json
{
  "reviewer_id": "reviewer://global/default",
  "execution_id": "exec://finance/a1b2c3d4-...",
  "result": "pass",
  "score": 0.91,
  "threshold": 0.85,
  "checks": [
    { "check": "cross_task_consistency", "status": "pass" },
    { "check": "output_completeness", "status": "pass" },
    { "check": "citation_accuracy", "status": "pass" }
  ],
  "evaluated_at": "2026-07-19T10:01:15.789Z"
}
```

---

## 8. Edge Cases & Special Semantics

### 8.1 DAG with Skipped Tasks

If a Task's `condition` evaluates to false, it transitions directly to `Skipped`. All downstream Tasks that depend *only* on skipped Tasks must also evaluate their conditions:

- If a downstream Task's condition is `always`, it is **also skipped** (no input to process)
- If a downstream Task's condition is independently evaluable (e.g., `input.contains('company')`), it is evaluated independently

### 8.2 Partial Output

`Partial` is distinct from `CompletedWithWarning`:

- `CompletedWithWarning`: The full Task completed, but some quality metrics were below threshold
- `Partial`: The Task did not fully complete, but produced enough output for constrained downstream processing

Partial output carries a `completeness` field (0.0 — 1.0) and a `usable_for[]` array listing which downstream Tasks can proceed.

### 8.3 Failure Propagation

When a Task reaches a terminal failure state (`FatalFailure`, retries exhausted):

1. All Tasks that depend **directly** on the failed Task receive a `DependencyFailed` signal
2. Those Tasks transition to `Cancelled` (they cannot proceed without upstream input)
3. Their downstream dependencies are also cancelled (cascade)
4. The Execution Engine evaluates the remaining subgraph for viability
5. If the remaining subgraph is viable (no dead dependencies), surviving Tasks continue
6. If the remaining subgraph is not viable, Execution transitions to `Failed`

### 8.4 Replan Loops

A replan loop occurs when Planner generates a new DAG that fails in the same way. Protection:

- Each Execution tracks `replan_count`
- If `replan_count >= max_replans` (default: 3), Execution transitions to `Failed`
- The Loop subsystem should detect replan loops and suggest Workflow or Rule changes

---

## 9. Execution Record Integration

When an Execution reaches a terminal state, an **Execution Record** is finalized (see SPEC-0000 §3.11). The record captures:

- The complete `state_history` of each Task
- All Events published during the Execution
- The final result classification and summary
- Total cost, latency, and quality metrics

The Execution Record is the single source of truth for replay, audit, and Loop analysis.

---

## 10. Compliance

Any implementation claiming Agent OS compatibility **must**:

1. Implement the Task state machine as defined in §3, including all 30+ transitions
2. Publish Events for every state transition as defined in §6
3. Support all 7 result classifications (§4)
4. Implement the retry policy engine as defined in §4.2
5. Implement the replan decider as defined in §4.3
6. Implement both Local and Global Reviewers as defined in §7

---

## 11. Open Questions

These are deferred to later RFCs:

1. **Reviewer timeout semantics** (T23) — configurable per-Task or per-Execution?
2. **Replan scoping** — should replan affect only the failed branch or the entire DAG?
3. **Partial output delivery** — how does a downstream Task signal that it can consume partial output?
4. **Archival triggers** — when exactly does a Task transition to `Archived`? (Currently defined as "when Execution completes")

---

## 12. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.4 | Task entity definition |
| SPEC-0000 §3.9 | Event entity definition |
| SPEC-0000 §3.10 | Execution entity definition |
| SPEC-0000 §3.11 | Execution Record entity definition |
| SPEC-0000 §7 | State Models Summary |
| Constitution Article 2 | Execution Engine is sole scheduler |
| Constitution Article 4 | All cross-module communication via Event Backbone |
| ADR-0001 | Event Sourcing pattern |
