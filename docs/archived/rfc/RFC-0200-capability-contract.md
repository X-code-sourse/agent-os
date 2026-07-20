# RFC-0200: Capability Contract

**Status:** Draft
**Type:** Runtime RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0001 v1.0, RFC-0002, RFC-0102 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Capability Contract** — the formal interface between the Control Plane (Execution Engine) and the Runtime Plane (Capability Pool). It specifies how Capabilities are invoked, how they return results and errors, how streaming output is handled, how cancellation propagates, and how cost is tracked. This is the boundary interface that enables third-party Capability authors to write compatible implementations.

---

## 2. Motivation

Capabilities are the functional units that do actual work — Research, Python, Browser, Search, Writing, etc. The Execution Engine (RFC-0102) knows that a Plan stage has a `capability_binding` (capability_id + model), but it does not know:

- What format does the input need to be in?
- What format will the output arrive in?
- What error types can occur, and which are retryable?
- How does streaming output work?
- How does cancellation reach a running Capability?
- How is cost reported per invocation?

Without a formal Capability Contract, every Capability author invents their own interface. The Engine would need Capability-specific adapters, breaking the plug-and-play model.

---

## 3. Capability Lifecycle

```
┌─────────────────────────────────────────────────────────────────────┐
│                      CAPABILITY LIFECYCLE                           │
│                                                                     │
│  Manifest published ──► Registry registers ──► Pool loads instance  │
│       │                                                             │
│       ▼                                                             │
│  Instance ready ──► Engine invokes ──► Running ──► Output/Error     │
│       │                                       │                     │
│       ├── Cancel signal ──► Stopped            │                     │
│       │                                       │                     │
│       └── Pool health check ──► Healthy/Unhealthy                   │
│                                                                     │
│  Manifest deprecated ──► Registry marks deprecated                  │
│       │                                                             │
│       └── Pool drains instances ──► No new invocations              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.1 States

| State | Definition |
|-------|------------|
| `Registered` | Capability Manifest is in the Registry, discoverable |
| `Loaded` | Capability Pool has loaded an instance (model + configuration initialized) |
| `Ready` | Instance is available for invocation |
| `Invoking` | Instance is executing a Task |
| `Degraded` | Instance is responding but with errors or high latency |
| `Unhealthy` | Instance is not responding or has crashed |
| `Deprecated` | Manifest marked for removal; existing invocations finish, no new ones accepted |
| `Removed` | Instance unloaded from Pool |

---

## 4. Capability Interface

### 4.1 Core Invocation Interface

Every Capability exposes exactly one execution method. The method is synchronous from the Engine's perspective — the Engine submits and waits (with timeout). The Capability may implement concurrency internally.

```
Capability.execute(input, context) → ExecutionResult
```

### 4.2 Input

```json
{
  "task_id": "task://exec_001/003",
  "input": {
    // Task-specific input, shaped by the Workflow's input_template
    // Schema is defined in the Capability Manifest's input_schema
    "query": "research Nvidia stock",
    "depth": "full",
    "sources": ["sec", "reuters", "bloomberg"]
  },
  "context": {
    "session_id": "session://finance/abc123",
    "profile_config": {
      "preferred_models": ["claude-sonnet-4"],
      "depth": "deep",
      "citation_required": true
    },
    "execution_id": "exec://finance/def456",
    "stage_id": "financial_analysis",
    "previous_stage_outputs": {
      "company_identification": {
        "company": "NVIDIA",
        "ticker": "NVDA",
        "exchange": "NASDAQ"
      }
    }
  },
  "config": {
    // Capability-specific configuration from Profile
    "max_sources": 20,
    "include_metadata": true
  },
  "deadline": "2026-07-19T10:05:00Z"  // Hard deadline; Capability should stop after this
}
```

### 4.3 Output (Success)

```json
{
  "status": "success",
  "output": {
    // Schema is defined in the Capability Manifest's output_schema
    "company": "NVIDIA Corporation",
    "ticker": "NVDA",
    "exchange": "NASDAQ",
    "sources": [
      {
        "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1045810",
        "type": "sec",
        "title": "NVIDIA 10-K Annual Report",
        "accessed_at": "2026-07-19T10:02:15Z"
      }
    ],
    "financial_summary": {
      "revenue_ttm": "130.5B",
      "net_income_ttm": "72.8B",
      "eps_ttm": "29.15"
    }
  },
  "metrics": {
    "tokens_used": 45000,
    "tokens_input": 2000,
    "tokens_output": 3000,
    "api_calls": 12,
    "latency_ms": 3200,
    "cost_usd": 0.18,
    "model": "claude-sonnet-4"
  },
  "confidence": 0.92
}
```

### 4.4 Output (Partial)

When a Capability is interrupted (timeout, rate limit) but has usable output:

```json
{
  "status": "partial",
  "output": {
    // Partial output — may be incomplete
    "company": "NVIDIA Corporation",
    "ticker": "NVDA"
    // financial_summary not yet available
  },
  "completeness": 0.35,
  "usable_for": ["company_identification"],
  "metrics": {
    "tokens_used": 12000,
    "api_calls": 4,
    "latency_ms": 4800,
    "cost_usd": 0.05,
    "model": "claude-sonnet-4",
    "interrupted_by": "rate_limit"
  },
  "confidence": 0.85
}
```

### 4.5 Output (Streaming)

For Capabilities that produce output incrementally (e.g., text generation, long-running research):

```json
// Initial response
{
  "status": "streaming",
  "stream_id": "stream://cap_001/abc123",
  "metrics": { "tokens_used": 500, "latency_ms": 400, "cost_usd": 0.002 }
}

// Subsequent chunks (delivered via Event Bus)
{
  "event_type": "Capability:StreamChunk",
  "stream_id": "stream://cap_001/abc123",
  "chunk": { "content": "NVIDIA Corporation (NVDA) is..." },
  "sequence": 1,
  "final": false
}

// Final chunk
{
  "event_type": "Capability:StreamChunk",
  "stream_id": "stream://cap_001/abc123",
  "chunk": { "content": "...conclusion." },
  "sequence": 15,
  "final": true
}

// Or, the Engine may request an accumulate:
// Capability.accumulate(stream_id) → full output (as in §4.3)
```

### 4.6 Errors

```json
{
  "status": "error",
  "error": {
    "code": "rate_limit_exceeded",
    "message": "API rate limit reached. Retry after 30 seconds.",
    "retryable": true,
    "retry_after_ms": 30000,
    "details": {
      "limit": 100,
      "reset_at": "2026-07-19T10:02:45Z"
    }
  },
  "metrics": {
    "tokens_used": 500,
    "api_calls": 1,
    "latency_ms": 200,
    "cost_usd": 0.002
  }
}
```

### 4.7 Error Codes

Every Capability must return errors from this classification:

| Error Code | Retryable | Engine Action | Example |
|------------|-----------|---------------|---------|
| `timeout` | Yes | Retry with backoff (RFC-0001 §4.2) | Model inference exceeded deadline |
| `rate_limit_exceeded` | Yes | Retry after `retry_after_ms` | API rate limit hit |
| `temporary` | Yes | Retry with backoff | Network blip, service transient error |
| `model_unavailable` | Yes | Retry (may trigger Capability Negotiation rebind) | Model is overloaded or down |
| `invalid_input` | No | Fail Task; error is in the Plan or Workflow | Input violates Capability schema |
| `authentication_failed` | No | Fail Task; Security Manager issue | API key invalid |
| `capability_crashed` | Yes | Retry (new instance) | Capability process crashed |
| `cancelled` | No | Normal cancellation path | Task was cancelled by Engine |
| `unsupported_feature` | No | Fail Task; Manifest lied | Required feature not actually supported |
| `internal_error` | Configurable | Configurable (default: retry) | Unexpected bug in Capability implementation |

### 4.8 Cancel Interface

```
Capability.cancel(invocation_id) → CancelResult
```

```json
// Engine → Capability
{
  "invocation_id": "invoc://cap_001/task_003",
  "reason": "upstream_dependency_failed",
  "deadline": "2026-07-19T10:00:35Z"  // Hard deadline for cancellation to complete
}

// Capability → Engine (success)
{
  "status": "cancelled",
  "work_saved": {
    "tokens_used": 12000,
    "api_calls": 3,
    "cost_usd": 0.05
  }
}

// Capability → Engine (acknowledge — may not be immediate)
{
  "status": "cancelling",
  "estimated_completion_ms": 2000
}
```

---

## 5. Capability Pool Interface

The Engine does not call Capabilities directly. It goes through the **Capability Pool**, which manages instances, concurrency, and health.

### 5.1 Pool → Engine Events

The Pool publishes the following events to the Event Bus (consumed by the Execution Engine):

| Event | Trigger | Payload |
|-------|---------|---------|
| `Capability:OutputProduced` | Successful execution | `invocation_id`, `output`, `metrics` |
| `Capability:PartialOutput` | Interrupted with partial output | `invocation_id`, `output`, `completeness`, `usable_for`, `metrics` |
| `Capability:Error` | Execution error | `invocation_id`, `error`, `metrics` |
| `Capability:StreamChunk` | Streaming output | `stream_id`, `chunk`, `sequence`, `final` |
| `Capability:Timeout` | Deadline exceeded with no output | `invocation_id`, `deadline`, `metrics` |
| `Capability:CancelAcknowledged` | Cancellation complete | `invocation_id`, `work_saved` |

### 5.2 Engine → Pool Commands

| Command | Trigger | Parameters |
|---------|---------|------------|
| `Pool.invoke` | Scheduler dispatches Task | `task_id`, `capability_id`, `input`, `context`, `config`, `deadline` |
| `Pool.cancel` | Engine needs to stop a running Task | `invocation_id`, `reason`, `deadline` |
| `Pool.status` | Engine health check | `invocation_id` |

### 5.3 Pool Responsibilities

```
CapabilityPool
├── Instance lifecycle management
│   ├── Load instances on Registry notification
│   ├── Health check (periodic ping)
│   ├── Unload on deprecation
│   └── Restart on crash
│
├── Concurrency control
│   ├── Per-Capability concurrency limit
│   ├── Per-model concurrency limit
│   └── Queue when limit reached; notify Engine of delay
│
├── Invocation routing
│   ├── Match invocation to an available instance
│   ├── Verify instance health before routing
│   └── Fallback to alternative model if primary unavailable
│
└── Metrics collection
    ├── Per-invocation cost tracking
    ├── Per-model latency percentiles
    ├── Error rate monitoring
    └── Publish to Event Bus for Observability and Loop
```

### 5.4 Pool Invocation Flow

```
Engine: Scheduler.dequeue() → stage ready
    │
    ▼
Pool.invoke(task_id, capability_id, input, context, config, deadline)
    │
    ├─ 1. Resolve capability_id to an instance
    │       Lookup in instance registry
    │       Verify instance is Ready
    │
    ├─ 2. Check concurrency
    │       if instance busy AND queue not full: queue invocation
    │       if instance busy AND queue full: return Pool:Busy immediately
    │       if instance available: route to instance
    │
    ├─ 3. Execute
    │       instance.execute(input, context, config)
    │       Start deadline timer
    │
    ├─ 4. Handle result
    │       on complete → publish Capability:OutputProduced
    │       on partial  → publish Capability:PartialOutput
    │       on error    → publish Capability:Error, evaluate retryable
    │       on timeout  → publish Capability:Timeout
    │       on cancel   → instance.cancel(invocation_id)
    │
    └─ 5. Report metrics
            Publish metrics event to Event Bus
```

---

## 6. Contract Validation

### 6.1 Registration-Time Validation

When a Capability Manifest is registered in the Registry, the following are validated:

| Check | Rule |
|-------|------|
| Input schema validity | `input_schema` must be valid JSON Schema (draft 2020-12) |
| Output schema validity | `output_schema` must be valid JSON Schema |
| Error code coverage | At least `timeout`, `invalid_input`, `internal_error` must be declared as possible errors |
| Performance claims | `quality_score` ∈ [0, 1]; `avg_latency_ms` > 0; `cost_per_call` ≥ 0 |
| Model compatibility | Declared models must exist in Model Registry |
| Feature consistency | `required_features` in Manifest must be a subset of features the implementation actually supports |

### 6.2 Invocation-Time Validation

Before dispatching a Task to a Capability, the Pool validates:

| Check | Rule |
|-------|------|
| Input conformance | Input JSON validates against `input_schema` |
| Capability freshness | Manifest has not been deprecated since Plan compilation |
| Model availability | Bound model is loaded and ready |
| Quota check | Invocation would not exceed Execution-level cost budget |

### 6.3 Output-Time Validation

After a Capability returns output, the Pool or Engine may validate:

| Check | Rule | Severity |
|-------|------|----------|
| Output conformance | Output JSON validates against `output_schema` | Required (fail if violates) |
| Confidence threshold | `confidence >= quality_threshold` (from Profile) | Warning (pass to Reviewer) |
| Source attribution | If citation feature required, output must include sources | Required (fail if missing) |
| Cost budget | `metrics.cost_usd <= cost_max` from Requirement | Warning (flag for Loop) |

---

## 7. Timeout Semantics

### 7.1 Deadline Propagation

```
Engine sets deadline = now + stage.max_execution_duration (from Plan)

1. Engine passes deadline to Pool in the invoke call
2. Pool passes deadline to Capability instance
3. Capability is expected to:
   a) Monitor wall-clock time
   b) Stop processing when deadline is reached
   c) Return partial output if available (status: "partial")
   d) If no partial output available, return Capability:Timeout
4. If Capability does not respond by deadline + grace_period (5s):
   Pool forces abort and returns Capability:Timeout
```

### 7.2 Default Timeouts by Capability Type

| Capability Type | Default Max Duration | Grace Period |
|----------------|---------------------|--------------|
| `research` | 120s | 5s |
| `python` | 60s | 5s |
| `browser` | 30s | 5s |
| `search` | 15s | 3s |
| `writing` | 120s | 5s |
| `reasoning` | 60s | 5s |

---

## 8. Cost Tracking Interface

Every invocation must report cost metrics. These are consumed by:

- **Execution Engine** — to enforce per-Execution budget (RFC-0100 §3.1 `cost_budget`)
- **Event Store** — to persist in Execution Record (SPEC-0000 §3.11)
- **Loop (Optimization Engine)** — to suggest cheaper alternatives
- **Analytics Engine** — to generate cost reports

### 8.1 Cost Report Schema

```json
{
  "invocation_id": "invoc://cap_001/task_003",
  "task_id": "task://exec_001/003",
  "capability_id": "cap://nous-research/research-v2",
  "model": "claude-sonnet-4",
  "metrics": {
    "tokens": {
      "input": 2000,
      "output": 3000,
      "total": 5000
    },
    "api_calls": 12,
    "latency_ms": 3200,
    "cost_usd": 0.18,
    "cost_breakdown": {
      "model_inference": 0.15,
      "tool_calls": 0.03
    },
    "retry_attempts": 0
  },
  "quota": {
    "remaining_budget_usd": 0.82,
    "budget_exceeded": false
  }
}
```

---

## 9. Capability Contract Compliance

### 9.1 For Capability Implementors

An implementation claiming Agent OS Capability compatibility **must**:

1. Implement the `execute(input, context, config) → ExecutionResult` interface (§4)
2. Return all output in one of the status formats: `success`, `partial`, `streaming`, `error` (§4.3–4.6)
3. Use only the error codes defined in §4.7; classify each error as retryable or not
4. Implement the `cancel(invocation_id)` interface (§4.8)
5. Respect the `deadline` field; return `partial` or `timeout` when deadline is reached (§7)
6. Report cost metrics per invocation per §8.1
7. Publish a Manifest (RFC-0201) that accurately describes supported inputs, outputs, and performance

### 9.2 For the Execution Engine / Pool

An implementation that consumes Capabilities **must**:

1. Invoke Capabilities through the Pool interface defined in §5, never directly
2. Validate input against `input_schema` before invocation (§6.2)
3. Apply deadline and grace period semantics from §7
4. Report all cost metrics to the Event Store (§8)
5. Handle all error codes from §4.7 (retryable → retry, non-retryable → fail)

---

## 10. Graceful Degradation

When a Capability fails or degrades, the system should degrade gracefully:

```
Capability fails (all retries exhausted)
    │
    ├─ Pool marks instance as Unhealthy
    │
    ├─ Engine triggers replan if replan_allowed
    │
    ├─ Planner re-binds to an alternative Capability (if available)
    │   └─ e.g., primary research-capability crashes → fall back to research-capability-lite
    │
    └─ If no alternative available:
        Execution continues with reduced scope (partial outputs)
        or Execution fails with clear error message
```

---

## 11. Open Questions

1. **Streaming output buffering** — should the Engine buffer stream chunks for replayability, or only store the final accumulated output in the Event Store?
2. **Pool distribution** — in a multi-node deployment, should the Pool be centralized or per-node? (Deferred to RFC-0203: Runtime Scheduling)
3. **Capability hot-reload** — when a Manifest is updated (patch version), can running instances be hot-reloaded or must they drain first?
4. **Cross-Capability state sharing** — should the Engine support passing large binary outputs (e.g., images, dataframes) between Capabilities without going through the Event Store?

---

## 12. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.7 | Capability Manifest entity |
| SPEC-0000 §3.8 | Capability Requirement entity |
| RFC-0001 §3 | Task State Machine (invocation drives Task states) |
| RFC-0001 §4 | Execution Result Semantics (error → retryable/fatal) |
| RFC-0001 §4.2 | Retry Policy (drives retry-eligible errors) |
| RFC-0102 §4.5 | Capability Invocation (Engine ↔ Pool) |
| RFC-0102 §7 | Replan Protocol (triggers rebind) |
| RFC-0102 §9 | Reviewer Integration (validates output post-invocation) |
| Constitution Article 7 | Capability implements ability only |
| Constitution Article 12 | Model selection is a Capability internal concern |
