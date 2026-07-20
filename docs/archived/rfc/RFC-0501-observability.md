# RFC-0501: Observability

**Status:** Draft
**Type:** Infrastructure RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0001 v1.0, RFC-0102 v1.0, RFC-0200 v1.0, RFC-0500 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Observability subsystem** — the standard metrics, traces, and audit data that every Agent OS implementation must expose. It covers three concerns:

- **Execution Trace** — the full path of an Execution from Goal to Output, with every state transition, latency measurement, and decision recorded
- **Cost Aggregation** — standardized cost tracking per Execution, per Capability, per Model, with budget enforcement data
- **Event Link Tracing** — connecting causally related Events across modules to enable drill-down from "Execution X failed" to "Capability Y returned error code Z at timestamp T"

---

## 2. Motivation

The existing RFCs scatter observability-related fields across multiple documents without a unified specification:

| Where | What's Referenced | Missing |
|-------|-------------------|---------|
| RFC-0102 §5.2 | Execution metadata (task_summary, cost_accumulated) | No schema for what goes in a trace |
| RFC-0200 §4.3 | Per-invocation metrics (tokens, latency, cost) | No aggregation specification |
| RFC-0200 §8 | Cost report schema | No budget enforcement data |
| RFC-0500 §6 | Event Store retention policies | No trace-level query interface |

Without RFC-0501:
- Every module reports metrics in its own format
- There is no standard Execution Trace that can be rendered in a dashboard
- Cost data cannot be aggregated across Executions, Capabilities, or Models
- Debugging a failed Execution requires manually correlating Events across the Event Store

---

## 3. Observability Architecture

```
Module                    Observable Data                        Consumer
                              │
  Execution Engine ──────────► Execution Trace                    │
  Capability Pool  ──────────► Cost Aggregation                   ├── Operator (dashboard)
  Reviewer         ──────────► Quality Metrics                    │
  Registry         ──────────► Event Link Trace                   ├── Loop (learning)
  Event Backbone   ──────────► Throughput / Latency               │
                              │                                   ├── Auditor (compliance)
                              ▼                                   │
                     ┌──────────────────┐                         └── Developer (debug)
                     │  Observability    │
                     │  Data Lake        │
                     │                   │
                     │  Traces (OLAP)    │
                     │  Costs (time-series)│
                     │  Metrics (counters)│
                     └──────────────────┘
```

### 3.1 Data Classification

| Category | Volume | Retention | Query Pattern |
|----------|--------|-----------|---------------|
| Execution Trace | Low (per Execution) | 90 days | Point lookup by execution_id |
| Cost Metrics | Medium (per invocation) | 90 days | Aggregation by time/model/capability |
| Quality Metrics | Low (per Review) | 90 days | Aggregation by workflow/capability |
| Event Metrics | High (per Event) | 7 days | Time-series (throughput, latency) |
| Audit Log | Low (per state change) | Permanent | Point lookup by entity_id |

---

## 4. Execution Trace

### 4.1 Trace Schema

An Execution Trace is the complete record of one Execution, structured as a tree of spans:

```json
{
  "trace_id": "trace://exec/finance/abc123",
  "execution_id": "exec://finance/abc123",
  "workflow_ref": "wf://finance/stock-research@2.1.0",
  "rules_applied": [
    { "id": "rule://finance/sec-filing", "version": "1.2.0" }
  ],
  "profile_ref": "profile://finance/deep@1.0.0",

  "timeline": {
    "created_at": "2026-07-19T10:00:00.000Z",
    "resolved_at": "2026-07-19T10:00:01.200Z",
    "running_at": "2026-07-19T10:00:05.000Z",
    "completed_at": "2026-07-19T10:01:18.500Z",
    "total_duration_ms": 78500
  },

  "spans": [
    {
      "span_id": "span://exec/finance/abc123/compile",
      "parent_span_id": null,
      "name": "planner.compile",
      "kind": "compile",
      "started_at": "2026-07-19T10:00:00.000Z",
      "ended_at": "2026-07-19T10:00:03.500Z",
      "duration_ms": 3500,
      "status": "ok",
      "attributes": {
        "stages_in_plan": 6,
        "stages_pruned": 4,
        "capabilities_bound": 2,
        "cache_hit": false
      },
      "events": [
        { "at": "10:00:01.000", "name": "workflow_resolved" },
        { "at": "10:00:02.000", "name": "rules_injected", "count": 2 },
        { "at": "10:00:03.000", "name": "negotiation_completed", "matches": 2 }
      ]
    },
    {
      "span_id": "span://exec/finance/abc123/company_id",
      "parent_span_id": null,
      "name": "stage.company_identification",
      "kind": "task",
      "started_at": "2026-07-19T10:00:05.000Z",
      "ended_at": "2026-07-19T10:00:08.200Z",
      "duration_ms": 3200,
      "status": "ok",
      "attributes": {
        "stage_id": "company_identification",
        "capability_id": "cap://nous-research/research-v2@2.3.0",
        "model": "claude-sonnet-4",
        "task_id": "task://exec_001/001",
        "review_result": "pass",
        "review_score": 0.95
      }
    },
    {
      "span_id": "span://exec/finance/abc123/news",
      "parent_span_id": null,
      "name": "stage.news_analysis",
      "kind": "task",
      "started_at": "2026-07-19T10:00:08.200Z",
      "ended_at": "2026-07-19T10:00:12.100Z",
      "duration_ms": 3900,
      "status": "ok",
      "attributes": {
        "stage_id": "news_analysis",
        "capability_id": "cap://nous-research/research-v2@2.3.0",
        "model": "claude-sonnet-4",
        "task_id": "task://exec_001/002",
        "sources_found": 15
      },
      "dependencies": ["span://exec/finance/abc123/company_id"]
    }
  ],

  "summary": {
    "stages_total": 2,
    "stages_completed": 2,
    "stages_failed": 0,
    "stages_skipped": 0,
    "total_cost_usd": 0.42,
    "total_review_score": 0.91,
    "replan_count": 0,
    "retry_count": 0
  }
}
```

### 4.2 Span Kinds

| Kind | Description | Examples |
|------|-------------|----------|
| `compile` | Planner compilation phase | `planner.compile` |
| `task` | A single Task execution | `stage.company_identification` |
| `review` | Local or Global Reviewer | `reviewer.local`, `reviewer.global` |
| `negotiation` | Capability Negotiation | `registry.negotiate` |
| `replan` | Replan cycle | `planner.replan` |
| `cancel` | Task or Execution cancellation | `engine.cancel_propagation` |

### 4.3 Trace Query API

```json
// Get trace for an execution
GET /observability/v1/traces?execution_id=exec://finance/abc123
→ { "trace_id": "...", "spans": [...], "summary": {...} }


// Find traces by status and time range
GET /observability/v1/traces?status=failed&from=2026-07-19T00:00:00Z&to=2026-07-19T23:59:59Z
→ { "traces": [...], "total": 5 }


// Span-level drill-down
GET /observability/v1/traces/{trace_id}/spans/{span_id}
→ { "span": {...}, "related_events": ["event://store/1547", "event://store/1548"] }
```

### 4.4 Trace Collection

Traces are **not** published as individual Events (too high volume). They are:

1. **Built incrementally** — each module publishes a `Span:Started` and `Span:Completed` event
2. **Assembled by the Observability subsystem** — merges span events into a complete trace
3. **Stored separately** from the Event Store (OLAP-friendly format: Parquet, ClickHouse, or similar)

```json
// Module publishes span start
{
  "event_type": "Span:Started",
  "payload": {
    "trace_id": "trace://exec/finance/abc123",
    "span_id": "span://exec/finance/abc123/company_id",
    "parent_span_id": null,
    "name": "stage.company_identification",
    "kind": "task",
    "started_at": "2026-07-19T10:00:05.000Z",
    "attributes": { "stage_id": "company_identification", "capability_id": "cap://..." }
  }
}

// Module publishes span end
{
  "event_type": "Span:Completed",
  "payload": {
    "trace_id": "trace://exec/finance/abc123",
    "span_id": "span://exec/finance/abc123/company_id",
    "ended_at": "2026-07-19T10:00:08.200Z",
    "duration_ms": 3200,
    "status": "ok",
    "attributes": { "review_score": 0.95, "tokens_used": 5000 }
  }
}
```

---

## 5. Cost Aggregation

### 5.1 Cost Records

Every Capability invocation produces a Cost Record (extending RFC-0200 §8):

```json
{
  "cost_record_id": "cost://obs-001/invoc_047",
  "trace_id": "trace://exec/finance/abc123",
  "span_id": "span://exec/finance/abc123/company_id",

  "execution_id": "exec://finance/abc123",
  "workflow_ref": "wf://finance/stock-research@2.1.0",
  "task_id": "task://exec_001/001",
  "capability_id": "cap://nous-research/research-v2",
  "capability_version": "2.3.0",
  "model": "claude-sonnet-4",

  "cost": {
    "tokens": { "input": 2000, "output": 3000, "total": 5000 },
    "api_calls": 12,
    "latency_ms": 3200,
    "usd": 0.18,
    "usd_breakdown": {
      "model_inference": 0.15,
      "tool_calls": 0.03
    }
  },

  "quality": {
    "review_score": 0.95,
    "confidence": 0.92
  },

  "invoked_at": "2026-07-19T10:00:05.100Z",
  "completed_at": "2026-07-19T10:00:08.200Z"
}
```

### 5.2 Aggregation Dimensions

The Observability subsystem must support aggregation along these dimensions:

| Dimension | Levels | Use Case |
|-----------|--------|----------|
| Time | hour, day, week, month | Cost trends |
| Workflow | workflow_id | "Which workflows cost the most?" |
| Capability | capability_id | "Which capabilities are most expensive?" |
| Model | model_id | "Is GPT-4o cheaper than Claude for research?" |
| Execution | execution_id | "Why did this execution cost $2.50?" |
| User/Session | session_id | "How much is this user spending?" |

### 5.3 Aggregation Query API

```json
// Cost by workflow over time
GET /observability/v1/costs?group_by=workflow&from=2026-07-01&to=2026-07-19
→ {
    "groups": [
      { "workflow_ref": "wf://finance/stock-research@2.1.0", "total_usd": 42.50, "invocations": 150 },
      { "workflow_ref": "wf://finance/etf-analysis@1.0.0", "total_usd": 18.30, "invocations": 60 }
    ],
    "total_usd": 60.80
  }


// Cost by model
GET /observability/v1/costs?group_by=model&from=...
→ {
    "groups": [
      { "model": "claude-sonnet-4", "total_usd": 35.00, "avg_cost_per_invocation": 0.23 },
      { "model": "gpt-4o", "total_usd": 20.00, "avg_cost_per_invocation": 0.15 }
    ]
  }


// Single execution cost breakdown
GET /observability/v1/costs?execution_id=exec://finance/abc123
→ {
    "execution_id": "exec://finance/abc123",
    "total_usd": 0.42,
    "stages": [
      { "stage_id": "company_identification", "cost_usd": 0.18, "model": "claude-sonnet-4" },
      { "stage_id": "news_analysis", "cost_usd": 0.24, "model": "claude-sonnet-4" }
    ]
  }
```

### 5.4 Budget Enforcement Data

When a Profile specifies a cost budget, the Observability subsystem tracks budget consumption:

```json
{
  "execution_id": "exec://finance/abc123",
  "budget": { "max_per_execution": 2.0, "max_per_task": 0.5 },
  "consumed": { "total": 0.42, "remaining": 1.58 },
  "per_task": [
    { "task_id": "task://001", "budget": 0.5, "consumed": 0.18, "status": "within_budget" },
    { "task_id": "task://002", "budget": 0.5, "consumed": 0.24, "status": "within_budget" }
  ]
}
```

---

## 6. Event Link Tracing

### 6.1 Correlation Chain

A single user action (Goal) may produce dozens of causally linked Events. Event Link Tracing connects them into a chain:

```
Goal: "research Nvidia"
    │
    ▼
Intent:Resolved
    │
    ▼
Plan:Compiled ──► Registry:NegotiationCompleted
    │
    ▼
Execution:Created
    │
    ▼
Task:Created (company_identification)
    │
    ▼
Capability:OutputProduced ──► Span:Completed
    │
    ▼
Task:Completed ──► Reviewer:LocalResult
    │
    ▼
Execution:Completed ──► Execution:GlobalReview ──► Execution Record
```

### 6.2 Link Schema

Every Event carries correlation context (SPEC-0000 §3.9, RFC-0500 §4):

```json
{
  "event_id": "event://store-001/1547",
  "event_type": "Capability:OutputProduced",
  "context": {
    "execution_id": "exec://finance/abc123",
    "task_id": "task://exec_001/001",
    "trace_id": "trace://exec/finance/abc123",
    "span_id": "span://exec/finance/abc123/company_id",
    "causality": {
      "caused_by": "event://store-001/1540",    // Task:Running that triggered this
      "causes": ["event://store-001/1550"]      // Task:WaitingReview that this triggers
    }
  }
}
```

### 6.3 Link Query API

```json
// Forward chain: "what happened after this event?"
GET /observability/v1/links/forward?event_id=event://store-001/1540
→ { "events": [
    { "event_id": "event://store-001/1547", "event_type": "Capability:OutputProduced", "delay_ms": 2800 },
    { "event_id": "event://store-001/1550", "event_type": "Task:WaitingReview", "delay_ms": 3100 }
  ]}


// Backward chain: "what caused this event?"
GET /observability/v1/links/backward?event_id=event://store-001/1550
→ { "events": [
    { "event_id": "event://store-001/1547", "event_type": "Capability:OutputProduced", "delay_ms": -300 },
    { "event_id": "event://store-001/1540", "event_type": "Task:Running", "delay_ms": -3100 }
  ]}
```

---

## 7. Standard Metrics

### 7.1 Metric Categories

Every module must publish metrics in the following categories:

| Category | Metrics | Unit | Source Module |
|----------|---------|------|---------------|
| **Throughput** | executions_per_second, tasks_per_second, events_per_second | count/s | All |
| **Latency** | execution_duration, task_duration, compile_duration, negotiation_duration, review_duration | ms | Engine, Planner, Registry, Reviewer |
| **Error Rate** | execution_failure_rate, task_failure_rate, review_failure_rate, negotiation_failure_rate | ratio | All |
| **Cost** | cost_per_execution, cost_per_task, cost_per_token | USD | Engine, Capability Pool |
| **Quality** | review_score_avg, review_score_p50, review_score_p95 | score | Reviewer |
| **Capacity** | queue_depth, active_executions, active_tasks, pool_utilization | count | Engine, Capability Pool |

### 7.2 Metric Publishing Format

```json
{
  "event_type": "Metric:Published",
  "payload": {
    "module": "execution-engine",
    "instance_id": "ee-001",
    "collected_at": "2026-07-19T10:00:00Z",
    "interval_seconds": 60,
    "metrics": {
      "executions_per_second": { "value": 0.5, "unit": "count/s" },
      "task_duration_ms": {
        "avg": 3200,
        "p50": 2800,
        "p95": 8500,
        "p99": 15000,
        "unit": "ms"
      },
      "task_failure_rate": { "value": 0.02, "unit": "ratio" },
      "active_executions": { "value": 3, "unit": "count" },
      "queue_depth": { "value": 0, "unit": "count" }
    }
  }
}
```

Metrics are published on a **fixed interval** (default: 60 seconds) to avoid overwhelming the Event Bus.

---

## 8. Audit Trail

### 8.1 Audit Events

Certain state changes are **audit-significant** and must be durably recorded with additional metadata:

| Audit Event | Trigger | Additional Fields |
|-------------|---------|-------------------|
| `Rule:Approved` | Governance approval | `approved_by`, `approval_ref`, `justification` |
| `Rule:ExperimentStarted` | Rule enters experiment | `traffic_share`, `duration`, `metric` |
| `Execution:Failed` | Execution terminates with failure | `failure_chain[]`, `failed_span_id` |
| `Capability:Deprecated` | Manifest deprecated | `sunset_date`, `reason`, `migration_path` |
| `Security:AccessDenied` | Security Manager blocks action | `resource`, `action`, `identity`, `reason` |
| `User:CancelledExecution` | User triggers cancel | `user_id`, `execution_id`, `reason` |

### 8.2 Audit Query

```json
GET /observability/v1/audit?from=2026-07-01&entity=rule://finance/sec-filing
→ { "events": [
    { "event_type": "Rule:Approved", "at": "2026-06-01T00:00:00Z", "by": "human:chief-analyst" },
    { "event_type": "Rule:ExperimentStarted", "at": "2026-05-15T00:00:00Z", "traffic_share": 0.1 }
  ]}
```

---

## 9. Dashboard Data Contract

The Observability subsystem provides structured data for rendering in a dashboard or CLI:

```json
// Health overview
GET /observability/v1/dashboard
→ {
    "period": { "from": "...", "to": "..." },
    "health": {
      "system_status": "healthy",     // healthy | degraded | down
      "active_executions": 3,
      "queue_depth": 0,
      "error_budget_remaining": 0.85
    },
    "throughput": {
      "executions_per_hour": 45,
      "tasks_per_hour": 180
    },
    "costs": {
      "total_usd": 60.80,
      "by_workflow": [ ... ],
      "by_model": [ ... ],
      "trend": [ { "date": "07-18", "usd": 58.20 }, { "date": "07-19", "usd": 60.80 } ]
    },
    "quality": {
      "avg_review_score": 0.89,
      "execution_success_rate": 0.97
    },
    "recent_failures": [
      { "execution_id": "exec://...", "failed_at": "...", "reason": "Capability:Timeout" }
    ]
  }
```

---

## 10. Compliance

Any implementation claiming Agent OS Observability compatibility **must**:

1. Produce Execution Traces conforming to §4 for every Execution
2. Support span-level drill-down via the Trace Query API (§4.3)
3. Collect and store Cost Records for every Capability invocation (§5.1)
4. Support cost aggregation along all 6 dimensions (§5.2)
5. Implement Event Link Tracing as defined in §6
6. Publish all standard metrics from §7 on a fixed interval
7. Persist audit-significant events as defined in §8.1
8. Expose the Dashboard endpoint (§9) for system health overview

---

## 11. Open Questions

1. **Trace storage backend** — should traces be stored in the Event Store (simplicity) or a dedicated OLAP store (query performance)?
2. **Metric cardinality** — with many dimensions, how do we prevent metric explosion? (e.g., per-model per-capability per-workflow per-hour)
3. **Alerting** — should this RFC define alert thresholds, or is alerting a separate system that consumes Observability data?
4. **Sampling** — should we support head-based sampling (always trace, sample at store) or tail-based sampling (sample based on span attributes)?

---

## 12. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.10 | Execution entity (traced object) |
| SPEC-0000 §3.11 | Execution Record (trace data feeds into this) |
| RFC-0001 §6 | Event Schema (traces reference event_ids) |
| RFC-0102 §5.2 | Execution Metadata (trace summary fields) |
| RFC-0200 §4.3 | Invocation output metrics (cost record source) |
| RFC-0200 §8 | Cost Report Schema (extended by §5.1) |
| RFC-0500 §4 | Event Envelope (correlation context for link tracing) |
| RFC-0500 §6.2 | Replay API (trace reconstruction from events) |
| Constitution Article 4 | All communication via Event Backbone (traces follow) |
