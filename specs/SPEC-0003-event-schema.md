# SPEC-0003: Event Schema

> **Status:** Frozen v1.0 -- Implemented in reference-runtime v0.4.3
> **Scope:** Standard format for recording and describing AI execution events
> **Editor:** Intent OS Project

> **Implementation Note:** The `EventType` enum in `core/models.py` is authoritative for the canonical list of event types. If a type appears in this spec but not in the enum (or vice versa), the enum is correct.

---

## 1. Purpose

The Event Schema defines a **standard format for recording execution events** from AI capability and workflow execution. It answers one question:

> **What happened during execution?**

Events serve two distinct but interconnected roles:

1. **Observability** — debugging, tracing, auditing, cost analysis, and monitoring in real time
2. **Learning Backbone** — accumulating execution history that feeds the Planner's Cost Model, Evolution Loop, and system optimization

The Event System is not "just logging." It is the **data flywheel** that enables Intent OS to evolve from a static interpreter into a self-optimizing execution infrastructure.

---

## 2. Design Principles

### P1: Structure, Not Content

Events record the **structure and outcome** of execution — not the content of capability inputs and outputs. They answer "what happened" and "what was the result," not "what was said." Full input/output payloads are recorded as references, not inline, to avoid ballooning event stores with model response data.

### P2: Traceable

All events from a single execution (capability invocation, workflow run, or proxy session) share a common `trace_id`. This enables full reconstruction of the execution path from a single entry point.

### P3: Comparable

Two runtimes executing the same capability with the same input MUST produce events with the same structure, the same event types, and the same metric dimensions. The *values* of metrics (latency, cost) may differ by runtime, but the *schema* of the event MUST be identical.

### P4: Append-Only

Events are immutable records of what happened. They are written once and never modified. Corrections are recorded as new events (e.g., `TaskRetried`).

---

## 3. Event Types

### 3.1 Core Execution Events

Events emitted during task and workflow execution by the orchestrator and recorder.

| Event Type | Status | When Emitted | Payload Summary |
|---|---|---|---|
| `TaskStarted` | Implemented | A task begins execution | task_id, capability, input_ref, depends_on |
| `CapabilityInvoked` | Implemented | A capability is called via adapter | task_id, capability, runtime_id, model_used, adapter_parameters, input_truncated |
| `TaskCompleted` | Implemented | A task completes successfully | task_id, output_ref, latency_ms, token_count, cost_usd, attempt |
| `TaskFailed` | Implemented | A task fails | task_id, error_type, error_message, error_code, attempt, retry_allowed, recovery_action |
| `TaskRetried` | Implemented | A failed task is retried | task_id, attempt, previous_attempt, backoff_ms, retry_reason |
| `TaskSkipped` | Implemented | A task is skipped (condition/failure policy) | task_id, reason |
| `TaskCancelled` | Implemented | A task is cancelled (compensation/user) | task_id, cancel_reason / reason |
| `WorkflowStarted` | Implemented | A workflow begins | workflow_id, goal, task_count, semantic_hash |
| `WorkflowCompleted` | Implemented | A workflow completes (any status) | workflow_id, status, tasks_succeeded, tasks_failed |
| `WorkflowFailed` | Defined | A workflow fails (reserved) | workflow_id, failed_task_id, failure_chain |
| `CostAccumulated` | Defined | Periodic cost update (reserved) | task_id, accumulated_cost, token_count |
| `ReviewRequired` | Defined | Task requires human review (reserved) | task_id, reason, review_token |
| `ReviewCompleted` | Defined | Human review is complete (reserved) | task_id, approved, reviewer, feedback |

**Note on `WorkflowFailed`:** Currently, workflow failure is signaled by emitting `WorkflowCompleted` with `status: "failed"` or `status: "partial"`. The `WorkflowFailed` event type is reserved for future use as a dedicated failure event.

### 3.2 Proxy / Observability Events

Events emitted by the proxy tracer, capturing raw LLM API calls made by external AI agents. These are **completely distinct** from `CapabilityInvoked` (which tracks Manifest-based capability executions).

| Event Type | Status | When Emitted | Payload Summary |
|---|---|---|---|
| `LlmCall` | Implemented | Proxy captures an LLM API call | provider, model, input_tokens, output_tokens, total_tokens, cost_usd, latency_ms, status, source_agent, endpoint, agent_id?, error? |

### 3.3 System Events (Infrastructure)

| Event Type | Status | When Emitted | Payload Summary |
|---|---|---|---|
| `RuntimeRegistered` | Defined | A new runtime adapter is registered (reserved) | runtime_id, name, version |
| `CapabilityRegistered` | Defined | A capability is registered (reserved) | capability_id, name, version |
| `PolicyEvaluated` | Implemented | A security/execution policy is checked | policy_id, task_id, result, reason |
| `ResourceWarning` | Defined | Token/rate/cost limit approaching (reserved) | resource_type, current, limit, threshold |

### 3.4 Security Events (SPEC-0004)

Events defined for the security model. Enumerated here for completeness; full semantics are specified in SPEC-0004.

| Event Type | Status | When Emitted | Payload Summary |
|---|---|---|---|
| `PermissionGranted` | Defined | Permission approved by user/policy (reserved) | permission_id, principal, resource, action |
| `PermissionDenied` | Defined | Permission denied by user/policy (reserved) | permission_id, principal, resource, action, reason |
| `ReviewExpired` | Defined | Human review window expired (reserved) | review_id, task_id, expired_at |
| `PolicyViolation` | Defined | A policy was violated during execution (reserved) | policy_id, task_id, violation_detail |

### 3.5 Evolution Loop Events

Events that drive self-optimization. Reserved for future phases.

| Event Type | Status | When Emitted | Payload Summary |
|---|---|---|---|
| `SuggestionGenerated` | Defined | Evolution Loop suggests a change (reserved) | suggestion_id, target, evidence, confidence |
| `SuggestionAutoApplied` | Defined | Suggestion auto-applied by system (reserved) | suggestion_id, target, change_description |
| `SuggestionDismissed` | Defined | Suggestion dismissed by reviewer (reserved) | suggestion_id, reviewer, reason |
| `LoopIteration` | Defined | One complete cycle of evolution (reserved) | iteration_id, suggestions_count, applied_count |

---

## 4. Event Record Structure

### 4.1 Common Fields

Every event has the following fields:

```yaml
event:
  spec_version: "1.0"               # Event Schema version (REQUIRED, always "1.0")
  trace_id: string                  # Execution trace identifier (UUID recommended)
  event_id: string                  # Unique event identifier (UUID v4)
  event_type: string                # From the EventType enum
  timestamp: ISO8601                # Event occurrence time (UTC)
  source: string                    # Component that emitted the event
                                   #   "runtime", "adapter", "scheduler", "proxy", "security"
  sequence: integer                 # Monotonic sequence within trace

  # Execution context (optional, present on task-level events)
  workflow_id: string | null
  task_id: string | null
  capability: string | null         # Capability identifier (name@version)

  # Runtime context (optional -- may be null for proxy events)
  runtime: string | null            # Runtime identifier (e.g., "openai", "anthropic")
  adapter_version: string | null    # Adapter version (null for proxy events)

  payload: dict                     # Event-specific data (see Section 5)
  metrics: dict | null              # Numeric performance metrics (see Section 6)
```

**Field notes:**

- `spec_version` is **always** `"1.0"` — it identifies this version of the event schema, not the capability or runtime version.
- `runtime` and `adapter_version` **may be `null`** — for proxy-captured `LlmCall` events, there is no adapter involved; the `provider` field in `payload` identifies the upstream service instead.
- `source` distinguishes which system component produced the event. Values seen in v0.4.3:
  - `"runtime"` — default, used by `Event.create()` and `ExecutionRecorder`
  - `"adapter"` — `CapabilityInvoked` events emitted by the recorder
  - `"scheduler"` — workflow-level events emitted by the scheduler
  - `"proxy"` — `LlmCall` events emitted by the proxy tracer
  - `"security"` — `PolicyEvaluated` events emitted by the security module
  - `"test"` — test fixtures

### 4.2 Event ID Uniqueness

Each `event_id` MUST be globally unique. UUID v4 is used throughout the reference runtime.

### 4.3 Trace ID

The `trace_id` is the single identifier that links all events from a single execution root (capability invocation, workflow run, or proxy session). It MUST be propagated to all child events.

- For capability executions: trace_id is generated by `ExecutionRecorder`
- For workflow executions: trace_id is generated by `Scheduler`
- For proxy sessions: trace_id is a `proxy-` prefix followed by a 12-char hex suffix

---

## 5. Payload Schemas by Event Type

### 5.1 TaskStarted

```yaml
payload:
  task_id: string
  capability: string                 # name@version
  input_ref: string                  # Reference to input record (URI or hash)
  depends_on: string[]               # Task IDs this task depends on
```

### 5.2 CapabilityInvoked

Emitted by `ExecutionRecorder.record_invoked()`. Source is `"adapter"`.

```yaml
payload:
  task_id: string
  capability: string                 # name@version
  runtime_id: string                 # Which runtime adapter was selected
  model_used: string                 # Which model was actually used
  adapter_parameters:                # Parameters passed to the adapter
    model: string
    max_tokens: integer
    temperature: number | null
    # ... additional provider-specific parameters
  input_truncated: boolean           # Whether input was truncated due to context limits
```

**Implementation note:** `input_schema_version` was in earlier drafts of this spec but is **not implemented** in the v0.4.3 recorder. The recorder writes exactly the six fields listed above.

### 5.3 TaskCompleted

Emitted by `ExecutionRecorder.record_completed()`. **Both `token_count` and `cost_usd` are in `payload`** (not solely in `metrics`), so consumer code has a single place to read execution results.

```yaml
payload:
  task_id: string
  output_ref: string                 # Reference to output record (may be empty string)
  output_schema_valid: boolean       # Whether output conformed to Manifest schema
  latency_ms: integer
  token_count:
    input: integer
    output: integer
    total: integer
  cost_usd: number
  attempt: integer                   # Which attempt succeeded (1 = first)

metrics:
  latency_ms: integer                # Duplicated from payload for aggregation convenience
  cost_usd: number                   # Duplicated from payload for aggregation convenience
```

### 5.4 TaskFailed

```yaml
payload:
  task_id: string
  error_type: string                 # Python exception class name or semantic type
                                     # e.g., "TimeoutError", "RateLimitError", "ConnectionError"
  error_message: string
  error_code: string | null          # Provider-specific error code
  attempt: integer                   # Which attempt failed
  retry_allowed: boolean             # Whether retry is possible
  recovery_action: string            # "retry" if retry_allowed, "fail" otherwise

metrics:
  latency_ms: integer                # Always 0 for failure events
  cost_usd: number                   # Always 0.0 for failure events
```

### 5.5 TaskRetried

```yaml
payload:
  task_id: string
  attempt: integer                   # The retry attempt number (2+)
  previous_attempt: integer          # Which attempt preceded this retry
  backoff_ms: integer                # How long we waited before retrying
  retry_reason: string               # Why the retry was triggered
```

### 5.6 TaskSkipped

```yaml
payload:
  task_id: string
  reason: string                     # "skip_on_failure", "skip_on_timeout", or condition name
```

### 5.7 TaskCancelled

```yaml
payload:
  task_id: string                    # May be "_workflow" for workflow-level cancellation
  reason: string                     # "compensation_rollback", "compensation_not_implemented", etc.
  # When emitted by scheduler cancellation:
  cancel_reason: string              # Alternative field name used by scheduler cancel path
```

### 5.8 WorkflowStarted

```yaml
payload:
  workflow_id: string
  goal: string                       # The user's original goal (may be empty string)
  task_count: integer                # Number of tasks in the workflow
  semantic_hash: string              # Hash of the Execution Semantics in effect
```

### 5.9 WorkflowCompleted

Emitted for **all** workflow outcomes — success, partial, and failure. (The `WorkflowFailed` event type exists in the enum but is not currently emitted; workflow failures are recorded as `WorkflowCompleted` with a failure status.)

```yaml
payload:
  workflow_id: string
  status: "success" | "partial" | "failed"
  tasks_succeeded: integer
  tasks_failed: integer
  tasks_skipped: integer
  tasks_retried: integer
  # Extensible — additional fields added by _build_completion_payload()
```

### 5.10 LlmCall

Emitted by the proxy tracer (`proxy/tracer.py`) for captured LLM API calls. This is **not** a Manifest-based capability invocation — it records raw provider API telemetry.

```yaml
payload:
  provider: string                   # "openai" | "anthropic" | "openrouter" | ...
  model: string                      # Model identifier string (e.g., "gpt-4o", "claude-sonnet-4")
  input_tokens: integer              # Prompt tokens
  output_tokens: integer             # Completion tokens
  total_tokens: integer              # input_tokens + output_tokens
  cost_usd: number                   # Estimated cost (6 decimal places)
  latency_ms: number                 # Round-trip latency (2 decimal places)
  status: string                     # "success" | "failure"
  source_agent: string               # Detected AI agent (see below)
  endpoint: string                   # API endpoint path (may be empty string)
  agent_id: string | null            # Registered agent ID, if known
  error: string | null               # Error message, if status is "failure"

metrics:
  latency_ms: number
  token_count:
    input: integer
    output: integer
    total: integer
  cost_usd: number
```

**Detected source_agent values** (from HTTP User-Agent and header heuristics):

| Agent String | Detected From |
|---|---|
| `"claude-code"` | `User-Agent` contains `claude-code` or `ClaudeCode` |
| `"cursor"` | `User-Agent` contains `Cursor` or `cursor` |
| `"github-copilot"` | `User-Agent` contains `GitHubCopilot` or `Copilot` |
| `"openai-sdk"` | `User-Agent` contains `openai-python` or `OpenAI` |
| `"python-sdk"` | `User-Agent` contains `python-requests` or `Python` |
| `"custom-agent"` | Header-based detection fallback |
| `"unknown"` | No recognizable agent signature found |

**Cost estimation** uses a built-in pricing table in `proxy/tracer.py` with per-model input/output pricing per 1M tokens. Unknown models default to `$2.50 / $10.00` per 1M tokens (input/output).

### 5.11 PolicyEvaluated

Emitted by `core/security.py` when a security policy is evaluated.

```yaml
payload:
  policy_id: string
  task_id: string
  result: string                     # "allow" | "deny" | "ask_user"
  reason: string
```

---

## 6. Metrics Schema

Metrics are a `dict` of numeric values attached to outcome events (`TaskCompleted`, `TaskFailed`, `LlmCall`). They serve as a **read-optimized copy** of key payload fields for aggregation queries.

```yaml
metrics:
  latency_ms: number                # Wall-clock execution time
  cost_usd: number                  # Estimated execution cost
  token_count:                      # Present on LlmCall events
    input: integer
    output: integer
    total: integer
```

**Note:** For `TaskCompleted` events, `token_count` is in `payload` only (not duplicated in `metrics`). The `metrics` field on `TaskCompleted` contains only `latency_ms` and `cost_usd`. `LlmCall` events include the full `token_count` in both `payload` and `metrics`.

---

## 7. Event Stream Format

Events are transmitted as a sequence of JSON objects, one per line (JSON Lines format).

```
{"event_type": "WorkflowStarted", "trace_id": "abc-123", "timestamp": "...", ...}
{"event_type": "TaskStarted", "trace_id": "abc-123", "task_id": "search", ...}
{"event_type": "CapabilityInvoked", "trace_id": "abc-123", "task_id": "search", ...}
{"event_type": "TaskCompleted", "trace_id": "abc-123", "task_id": "search", ...}
{"event_type": "TaskStarted", "trace_id": "abc-123", "task_id": "analyze", ...}
{"event_type": "WorkflowCompleted", "trace_id": "abc-123", ...}
```

### 7.1 Execution Record (Complete Bundle)

A complete `ExecutionRecord` bundles the event stream with metadata for compatibility verification across runtimes.

```yaml
execution_record:
  spec_version: "1.0"
  trace_id: string

  manifest:
    name: string
    version: string

  runtime:
    id: string
    adapter: string
    adapter_version: string

  input: any                         # Original input
  output: any                        # Final output

  events: Event[]                    # The event stream
  metrics:                           # Aggregated summary
    total_latency_ms: number
    total_cost_usd: number
    total_tokens: integer

  status: "success" | "failure" | "partial"
  error: string | null               # Error message if status != success
```

### 7.2 Compatibility Verification

The `compare_records()` function in `core/recorder.py` implements three-level compatibility checking:

1. **L1 - Schema Compatibility:** Same `manifest_name@manifest_version`
2. **L2 - Event Structure Match:** Same sequence of event types (order and count)
3. **L3 - Metric Dimensions Match:** Same metric keys across both records (subset relationship is acceptable)

```
Event Record from Runtime A:              Event Record from Runtime B:
  trace_id: "abc-123"                       trace_id: "def-456"
  events:                                   events:
    - type: "TaskStarted"                     - type: "TaskStarted"
    - type: "CapabilityInvoked"               - type: "CapabilityInvoked"
    - type: "TaskCompleted"                   - type: "TaskCompleted"
  metrics:                                  metrics:
    latency_ms: 3200                          latency_ms: 1800
    cost_usd: 0.04                            cost_usd: 0.02

  -> L1: PASS (same manifest)
  -> L2: PASS (same event type sequence)
  -> L3: PASS (same metric dimensions; different values expected)
```

---

## 8. Event Bus Architecture

The Event Bus is the communication backbone of the Intent OS runtime. All Planes communicate through it.

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  Control │     │ Metadata │     │ Runtime  │
│  Plane   │────▶│  Plane   │────▶│  Plane   │
└──────────┘     └──────────┘     └──────────┘
      │               │               │
      └───────────────┼───────────────┘
                      │
                      ▼
                 Event Bus
                      │
                      ▼
              ┌──────────────┐
              │   Data Plane │
              │ (Event Store)│
              └──────────────┘
```

### 8.1 Bus Properties

1. **Ordered**: Events from a single trace are delivered in sequence order
2. **Durable**: Events are persisted before being consumed
3. **Observable**: The Event Bus itself is observable -- its throughput and latency are monitored
4. **Decoupled**: Producers and consumers do not know about each other

---

## 9. Validation Rules

### 9.1 Required Fields

Every event MUST include:
- `spec_version`, `trace_id`, `event_id`, `event_type`, `timestamp`, `source`, `sequence`
- `payload` (at minimum an empty dict `{}`)

Optional context fields (`workflow_id`, `task_id`, `capability`, `runtime`, `adapter_version`) are omitted from the serialized dict when they are `None`/null.

### 9.2 Type Constraints

- `trace_id` and `event_id` MUST be strings (UUID v4 recommended for `event_id`)
- `timestamp` MUST be ISO 8601 with timezone (UTC in practice)
- `sequence` MUST be a monotonically increasing integer within a trace
- `payload` MUST be a JSON object (dict)
- `metrics`, if present, MUST be a JSON object (dict)

### 9.3 Sequence Constraints

Within a single trace:
- `TaskStarted` SHOULD precede `CapabilityInvoked` for the same task
- `TaskCompleted` or `TaskFailed` SHOULD follow `CapabilityInvoked`
- `WorkflowCompleted` SHOULD be the last event for a workflow trace
- `TaskRetried` SHOULD follow `TaskFailed` and precede the next `TaskStarted` for the same task

---

## 10. Event Store (Data Plane)

The Event Store is a **SQLite-backed persistent storage** for execution events. It is part of the Data Plane and provides the foundation for observability, replay, analytics, and cost model training.

### 10.1 Technology

- **Database:** SQLite (WAL mode, `PRAGMA synchronous=NORMAL`)
- **Location:** `~/.intent-os/events.db` (configurable via `EventStore(db_path)`)
- **Schema version:** 2 (tracked in `meta` table)

### 10.2 Events Table

```sql
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    trace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'runtime',
    sequence INTEGER NOT NULL DEFAULT 0,
    workflow_id TEXT,
    task_id TEXT,
    capability TEXT,
    runtime TEXT,
    adapter_version TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    metrics TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Key design points:**
- `payload` and `metrics` are stored as **TEXT** (JSON strings), not native JSON — this is SQLite, not PostgreSQL.
- `event_id` has a UNIQUE constraint — duplicate events are rejected with `EventStoreError`.
- `id` is an auto-increment INTEGER primary key; `event_id` is the domain-level UUID.
- Separate columns exist for `workflow_id`, `task_id`, `capability`, `runtime`, and `adapter_version` to enable indexed queries without `json_extract()`.

**Indexes:**

```sql
CREATE INDEX IF NOT EXISTS idx_events_trace_id ON events(trace_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_capability ON events(capability);
CREATE INDEX IF NOT EXISTS idx_events_workflow_id ON events(workflow_id);
```

### 10.3 Execution Records Table

```sql
CREATE TABLE IF NOT EXISTS execution_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL UNIQUE,
    spec_version TEXT NOT NULL DEFAULT '1.0',
    manifest_name TEXT NOT NULL,
    manifest_version TEXT NOT NULL,
    runtime_id TEXT NOT NULL,
    adapter TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    input TEXT,
    output TEXT,
    status TEXT NOT NULL DEFAULT 'success',
    error TEXT,
    total_latency_ms REAL NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    agent_id TEXT,
    agent_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Key design points:**
- `total_tokens` is INTEGER, `total_latency_ms` and `total_cost_usd` are REAL.
- `agent_id` and `agent_name` associate the execution with a registered agent (used for proxy-captured calls).
- `input` and `output` are stored as TEXT (JSON-serialized).

**Indexes:**

```sql
CREATE INDEX IF NOT EXISTS idx_records_manifest ON execution_records(manifest_name, manifest_version);
CREATE INDEX IF NOT EXISTS idx_records_runtime ON execution_records(runtime_id);
CREATE INDEX IF NOT EXISTS idx_records_status ON execution_records(status);
CREATE INDEX IF NOT EXISTS idx_records_created ON execution_records(created_at);
```

### 10.4 Task State Table

Used by the Scheduler to persist task outputs and errors (Data Plane owns all state per CONSTITUTION Article II).

```sql
CREATE TABLE IF NOT EXISTS task_state (
    trace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL DEFAULT '',
    field_name TEXT NOT NULL,
    field_value TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (trace_id, task_id, field_name)
);
```

### 10.5 Query Capabilities

The `EventStore` class supports:
- `save_event(event)` / `save_events_batch(events)` — append-only write
- `get_events_by_trace(trace_id)` — full trace replay in sequence order
- `get_events_by_type(event_type)` — filter by event type
- `get_events_by_time_range(start, end)` — time-range queries
- `get_events_by_capability(capability)` — filter by capability name@version
- `query_events(...)` — flexible multi-filter query
- `save_execution_record(record)` — persist an ExecutionRecord
- `get_record(trace_id)` / `query_records(...)` — read execution records
- `get_capability_stats()` / `get_runtime_stats()` — aggregation for analytics
- `get_recent_traffic(since_iso)` — proxy-captured API call counts by status
- `get_agent_summary()` — per-agent traffic summary from proxy events
- `delete_events_before(cutoff)` / `delete_records_before(cutoff)` — data lifecycle

---

## 11. v0.4.3 Implementation Scope

### What is implemented:

1. **Event types emitted:** `TaskStarted`, `CapabilityInvoked`, `TaskCompleted`, `TaskFailed`, `TaskRetried`, `TaskSkipped`, `TaskCancelled`, `WorkflowStarted`, `WorkflowCompleted`, `LlmCall`, `PolicyEvaluated`
2. **Event types defined but not emitted:** `WorkflowFailed` (workflow failures use `WorkflowCompleted` with `status: "failed"`), `CostAccumulated`, `ReviewRequired`, `ReviewCompleted`, `RuntimeRegistered`, `CapabilityRegistered`, `ResourceWarning`, all Security events (`PermissionGranted`, `PermissionDenied`, `ReviewExpired`, `PolicyViolation`), all Evolution Loop events (`SuggestionGenerated`, `SuggestionAutoApplied`, `SuggestionDismissed`, `LoopIteration`)
3. **ExecutionRecorder** — in-memory event collection with optional JSON Lines output to stdout
4. **EventStore** — SQLite-backed persistent storage with query and aggregation support
5. **AgentTracer** — proxy-side tracer that captures LLM API calls as `LlmCall` events
6. **Compatibility verification** — `compare_records()` for cross-runtime event structure comparison
7. **Event Store CLI** — `intent-os event list|trace|query` for inspecting stored events

### What is NOT yet implemented (future phases):

- Real-time event streaming / pub-sub (events are written synchronously)
- Event replay engine (raw SQL queries are used; no replay DSL)
- Automatic anomaly detection from event patterns
- Cost Model automatic training from accumulated events
- Federated events (cross-registry sharing)
- `PlanGenerated` / `PlanDeviation` event types (removed — these were in the v0.1 draft but are not in the `EventType` enum)

---

## 12. Future Extensions

| Extension | Description | Phase |
|---|---|---|
| **Event Store** | Durable, queryable event storage | Implemented (v0.4.3) |
| **Proxy Tracer** | LLM API call capture and agent identification | Implemented (v0.4.3) |
| **Event Stream Processing** | Real-time analysis of event streams | Phase 2 |
| **Cost Model Feed** | Events automatically feed Planner's Cost Model | Phase 3 |
| **Anomaly Detection** | Automatic detection of execution anomalies | Phase 3 |
| **Audit Trail** | Immutable, verifiable event chain for compliance | Phase 3 |
| **Federated Events** | Cross-registry event sharing | Phase 4 |
| **Event Replay Engine** | Deterministic re-execution from stored events | Phase 2 |

---

## 13. References

- CloudEvents — event format inspiration
- OpenTelemetry — trace and span concepts
- JSON Lines — event stream serialization format
- Apache Kafka / AWS Kinesis — event bus architecture patterns
- Database query logs — the analogy for Cost Model training data
