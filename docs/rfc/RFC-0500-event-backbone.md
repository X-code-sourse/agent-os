# RFC-0500: Event Backbone

**Status:** Draft
**Type:** Infrastructure RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0001 v1.0, ADR-0001
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Event Backbone** — the infrastructure layer enabling all cross-module communication in Agent OS (Constitution Article 4). The Backbone consists of three subsystems:

- **Event Bus** — pub/sub message transport with at-least-once delivery
- **Event Store** — append-only persistent storage with replay capability
- **Schema Registry** — Event type registration, versioning, and compatibility validation

The Backbone is the **only communication channel** between any two modules. No module calls another module directly. Every state transition, every invocation, every decision is published as an Event.

---

## 2. Motivation

The existing RFCs reference Events constantly — as the mechanism for task state transitions (RFC-0001 §6), engine recovery (RFC-0102 §10), capability streaming (RFC-0200 §4.5), negotiation (RFC-0202 §10.2), and rule lifecycle (RFC-0104 §8.3). But none define how the Event system actually works.

Without RFC-0500:

- Every module publishes Events with inconsistent guarantees (fire-and-forget? at-least-once?)
- The Event Store has no standard replay API — RFC-0102's state recovery may not work
- Event type evolution is unmanaged — a new version of a module publishes a changed Event schema, and consumers silently break
- ADR-0001's Event Sourcing pattern has no concrete implementation contract

---

## 3. System Overview

```
Module A                    Event Backbone                        Module B
   │                            │                                      │
   │── publish(Event) ────────►│                                      │
   │                            │                                      │
   │                            ├─ 1. Validate event against schema   │
   │                            ├─ 2. Store in Event Store             │
   │                            ├─ 3. Route to subscribers             │
   │                            │                                      │
   │                            │── deliver(Event) ──────────────────►│
   │                            │                                      │
   │                            │◄── ack(sequene_id) ─────────────────│
   │                            │                                      │
   │                            └─ 4. Mark delivered (at-least-once)  │
```

### 3.1 Three Subsystems, One Backbone

```
┌─────────────────────────────────────────────────────────────────────┐
│                         EVENT BACKBONE                              │
│                                                                     │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────┐  │
│  │      Event Bus       │  │     Event Store      │  │   Schema    │  │
│  │                     │  │                      │  │  Registry   │  │
│  │  Pub/sub routing    │  │  Append-only storage │  │  Type reg    │  │
│  │  At-least-once      │  │  Replay API          │  │  Compat     │  │
│  │  Delivery retry     │  │  Snapshot/compaction │  │  Validation  │  │
│  │  Subscriber mgmt    │  │  Retention policies  │  │  Evolution   │  │
│  └─────────────────────┘  └─────────────────────┘  └─────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              Common: Event Envelope (SPEC-0000 §3.9)          │  │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Event Envelope

### 4.1 Canonical Envelope

Every Event in the system uses the following envelope (extending SPEC-0000 §3.9):

```json
{
  "event_id": "event://store-001/01AR...Z3",
  "event_type": "Task:Completed",
  "version": 1,

  "source": {
    "module": "execution-engine",
    "instance_id": "ee-001",
    "execution_id": "exec://finance/abc123"
  },

  "payload": { /* type-specific content */ },

  "metadata": {
    "timestamp": "2026-07-19T10:00:30.123456Z",
    "sequence_id": 1547,
    "publisher_clock": { "wall": "2026-07-19T10:00:30.123Z", "logical": 42 },
    "content_type": "application/json",
    "size_bytes": 2048
  },

  "context": {
    "execution_id": "exec://finance/abc123",
    "session_id": "session://finance/xyz789",
    "workflow_ref": "wf://finance/stock-research@2.1.0"
  },

  "signature": {
    "algorithm": "ed25519",
    "value": "base64..."     // Optional: enables non-repudiation
  }
}
```

### 4.2 Field Definitions

| Field | Always Present? | Description |
|-------|----------------|-------------|
| `event_id` | Yes | Globally unique, monotonically increasing |
| `event_type` | Yes | Namespaced type string: `Domain:Action` |
| `version` | Yes | Event schema version (integer, starts at 1) |
| `source` | Yes | Publishing module identity |
| `payload` | Yes | Type-specific data (schema defined in Schema Registry) |
| `metadata.timestamp` | Yes | Publisher's wall clock at publish time (UTC, nanosecond precision) |
| `metadata.sequence_id` | Yes | Monotonically increasing per-partition sequence |
| `metadata.content_type` | Yes | Payload serialization format |
| `context` | No | Cross-cutting context for correlation and filtering |
| `signature` | No | Optional cryptographic signature for audit integrity |

### 4.3 Event ID Generation

```
event_id = event://<store_id>/<sequence_id>

<store_id> = unique identifier of the Event Store instance
<sequence_id> = monotonically increasing 64-bit integer per partition
```

This encoding makes `event_id` both globally unique and ordered within a partition — enabling efficient replay from any point.

---

## 5. Event Bus

### 5.1 Delivery Guarantees

| Guarantee | Supported? | Notes |
|-----------|-----------|-------|
| At-least-once | **Required** | Default delivery mode |
| At-most-once | Optional | For high-throughput, loss-tolerant events |
| Exactly-once | Not required | At-least-once + idempotent consumers achieves the same effect |
| Ordered per partition | **Required** | Events from the same source within the same execution maintain order |
| Cross-partition ordering | Not required | No global ordering guarantee |

### 5.2 Delivery Lifecycle

```
publish(event)
    │
    ├─ 1. Validate against Schema Registry (§7)
    │      If invalid → reject with Registry:SchemaViolation error
    │
    ├─ 2. Persist to Event Store (§6)
    │      If store write fails → reject with Store:WriteError
    │
    ├─ 3. Route to subscribers
    │      a. Match event_type against subscription filters
    │      b. Fan-out to all matching subscribers (in parallel)
    │
    ├─ 4. Deliver to subscriber
    │      a. Push via Event Bus channel
    │      b. Start delivery timer (default: 30s timeout)
    │
    ├─ 5. Await ack
    │      ├── ack(sequence_id) → mark delivered, record latency
    │      └── timeout or nack → retry (up to max_retries=3)
    │                           → if exhausted: move to dead-letter queue
    │
    └─ 6. Dead-letter queue
           Events that cannot be delivered after max_retries
           are moved to a dead-letter topic for manual inspection
```

### 5.3 Subscription Model

```json
// Subscribe
{
  "subscription_id": "sub://event-bus/ee-001-task-events",
  "subscriber": { "module": "execution-engine", "instance_id": "ee-001" },
  "filters": [
    { "event_type_prefix": "Task:" },     // All Task events
    { "event_type_prefix": "Execution:" } // All Execution events
  ],
  "delivery": {
    "mode": "push",                        // push or poll
    "max_retries": 3,
    "deadline_ms": 30000,
    "batch_size": 10,                      // Max events per delivery batch
    "batch_timeout_ms": 100                // Max wait to fill a batch
  },
  "qos": {
    "priority": "normal",                  // high, normal, low
    "max_delivery_rate": 100               // Events per second (rate limiting)
  }
}
```

| Delivery Mode | Description | Use Case |
|---------------|-------------|----------|
| `push` | Backbone pushes events to subscriber's endpoint | Engine, Reviewer, Pool |
| `poll` | Subscriber pulls events from the Backbone | Loop, Analytics (batch consumers) |

### 5.4 Dead-Letter Queue

Events that exhaust delivery retries are moved to a dead-letter queue:

```json
{
  "event_id": "event://store-001/1547",
  "event_type": "Task:Completed",
  "dead_letter": {
    "reason": "delivery_retries_exhausted",
    "delivery_attempts": [
      { "subscriber": "ee-001", "attempt": 1, "error": "timeout", "at": "..." },
      { "subscriber": "ee-001", "attempt": 2, "error": "nack", "at": "..." },
      { "subscriber": "ee-001", "attempt": 3, "error": "timeout", "at": "..." }
    ],
    "moved_at": "2026-07-19T10:01:00Z"
  }
}
```

---

## 6. Event Store

### 6.1 Storage Model

The Event Store is an **append-only log** indexed by:

- `event_id` — point lookup
- `(execution_id, sequence)` — ordered replay per execution
- `event_type + time_range` — filtered scan
- `source.module` — module-specific audit

```sql
-- Logical schema (not necessarily SQL)
CREATE TABLE events (
    event_id        TEXT PRIMARY KEY,          -- event://<store>/<seq>
    event_type      TEXT NOT NULL,             -- "Task:Completed"
    version         INTEGER NOT NULL,          -- Schema version
    source_module   TEXT NOT NULL,             -- "execution-engine"
    source_instance TEXT,
    execution_id    TEXT,                      -- NULL for system events
    session_id      TEXT,
    payload         JSONB NOT NULL,
    metadata        JSONB NOT NULL,
    published_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    ingested_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Required indexes
CREATE INDEX idx_events_execution ON events(execution_id, metadata->>'sequence_id');
CREATE INDEX idx_events_type_time ON events(event_type, published_at);
CREATE INDEX idx_events_source ON events(source_module, published_at);
```

### 6.2 Replay API

The replay API is critical for RFC-0102 §10 (Engine State Recovery):

```json
// Replay all events for an execution, in order
GET /store/v1/replay?execution_id=exec://finance/abc123
→ stream of Event[]

// Replay from a specific sequence (for checkpoint resumption)
GET /store/v1/replay?execution_id=exec://finance/abc123&from_sequence=1200
→ stream of Event[from 1200..latest]

// Replay events of a specific type within a time range
GET /store/v1/replay?event_type=Task:Failed&from=2026-07-19T10:00:00Z&to=2026-07-19T11:00:00Z
→ stream of Event[]
```

**Replay guarantees:**
1. Events are returned in **exactly the same order** they were published
2. Replay is **idempotent** — replaying the same range produces identical results
3. Replay supports **offset pagination** (cursor-based for large result sets)
4. Replay throughput: **minimum 10,000 events/second** per execution

### 6.3 Snapshot and Compaction

For long-running Executions with many events (RFC-0102 §10.4):

```json
// Create a snapshot of engine state at a sequence point
POST /store/v1/snapshot
{
  "execution_id": "exec://finance/abc123",
  "at_sequence": 1200,
  "state": { /* Engine's in-memory state serialized */ }
}

// Later: recover from snapshot + remaining events
GET /store/v1/replay?execution_id=exec://finance/abc123&from_sequence=1201
```

**Compaction rules:**
- Events older than the retention period (configurable, default: 30 days) are eligible for compaction
- Compaction merges fine-grained events into summary records (e.g., 50 `Task:Heartbeat` → 1 `Task:HeartbeatSummary`)
- Compaction never deletes Execution Records (SPEC-0000 §3.11) — they are permanent
- Compacted events are moved to cold storage (retained for audit but not indexed for replay)

### 6.4 Retention Policies

| Event Category | Default Retention | Compaction Eligible? | Can Delete? |
|---------------|-------------------|---------------------|-------------|
| Task lifecycle | 30 days | After 7 days | No (audit) |
| Execution lifecycle | 90 days | After 30 days | No (audit) |
| Execution Record | Permanent | No | No |
| Capability metrics | 7 days | After 1 day | Yes |
| Negotiation events | 1 day | No | Yes |
| Heartbeat / health | 1 hour | After 5 min | Yes |
| Dead-letter | 30 days | No | Manual |

---

## 7. Schema Registry

### 7.1 Event Type Registration

Every event type must be registered in the Schema Registry before publishing:

```json
POST /schema/v1/register
{
  "event_type": "Task:Completed",
  "version": 1,
  "schema": {
    "type": "object",
    "required": ["task_id", "output_ref", "duration_ms", "cost"],
    "properties": {
      "task_id": { "type": "string", "pattern": "^task://" },
      "output_ref": { "type": "string" },
      "duration_ms": { "type": "integer", "minimum": 0 },
      "cost": {
        "type": "object",
        "properties": {
          "tokens": { "type": "integer" },
          "api_calls": { "type": "integer" },
          "usd": { "type": "number" }
        }
      }
    }
  },
  "description": "Published when a Task completes successfully",
  "producer": "execution-engine",
  "consumers": ["loop", "analytics", "event-store"]
}
```

### 7.2 Validation at Publish Time

Every event is validated against its registered schema before being accepted:

```
publish(event)
    │
    ├─ 1. Lookup schema: SchemaRegistry.get(event_type, version)
    │      If not found → reject (event type not registered)
    │
    ├─ 2. Validate payload against schema
    │      If invalid → reject with SchemaViolation, include validation errors
    │
    └─ 3. Proceed to store and route
```

### 7.3 Schema Evolution

Event schemas evolve. Compatibility is enforced at registration:

```json
// Register a new version
POST /schema/v1/register
{
  "event_type": "Task:Completed",
  "version": 2,
  "schema": { /* new schema */ },
  "compatibility": {
    "mode": "backward",       // See below
    "previous_version": 1,
    "validation": "pass"      // checked by Schema Registry
  },
  "change_log": "Added output_confidence field"
}
```

| Compatibility Mode | Consumer Can Read | Producer Can Publish |
|--------------------|------------------|---------------------|
| `backward` | v2 events with v1 reader | v1 events with v2 schema |
| `forward` | v1 events with v2 reader | v2 events with v1 schema |
| `full` | Both directions compatible | Both directions |
| `none` | No compatibility guaranteed | Breaking change |

**Default mode: `backward`.** A new version must be readable by consumers written for the old version. This means:
- Fields can be added (optional)
- Fields cannot be removed or made required
- Field types cannot change in a breaking way

### 7.4 Event Type Naming Convention

```
event_type ::= <Domain>:<Action>

<Domain> ::= PascalCase module or entity name
<Action> ::= PascalCase past-tense verb

Examples:
  Task:Created         Task:Queued          Task:Running
  Task:WaitingReview   Task:Completed       Task:Failed
  Execution:Created    Execution:Running    Execution:Completed
  Capability:OutputProduced   Capability:Error
  Registry:ObjectRegistered   Registry:ObjectDeprecated
  Rule:StatusChanged   Rule:ExperimentCompleted
  Scheduler:QueueDeep
```

---

## 8. Backbone Topology (v1)

In v1, the Event Backbone is an **embedded in-process backbone** — all three subsystems run in the same process as the Kernel:

```
┌──────────────────────────────────────────────────┐
│                  Kernel Process                   │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ Planner  │  │  Engine  │  │  Capability     │  │
│  │          │  │          │  │  Pool           │  │
│  └────┬─────┘  └────┬─────┘  └───────┬────────┘  │
│       │              │                │           │
│       ▼              ▼                ▼           │
│  ┌──────────────────────────────────────────┐    │
│  │           Event Bus (in-memory)           │    │
│  │           + Event Store (SQLite)          │    │
│  │           + Schema Registry (in-memory)   │    │
│  └──────────────────────────────────────────┘    │
│                                                    │
│  ┌──────────────────────────────────────────┐    │
│  │         External Subscribers              │    │
│  │  (Loop, Analytics — same process)        │    │
│  └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

**Why in-process for v1:**
- Zero network overhead — events are function calls to the in-memory bus
- Simplified deployment — one process to start
- Event Store backed by SQLite — fast single-node replay
- Migration path: extract to separate service when multi-node is needed

**v2 target (not specified in this RFC):** Distributed Event Backbone (e.g., Kafka, NATS, or a custom service) for HA and horizontal scaling.

---

## 9. Compliance

Any implementation claiming Agent OS Event Backbone compatibility **must**:

1. Implement the canonical Event envelope from §4
2. Provide at-least-once delivery guarantees (§5.1)
3. Support both push and poll subscription modes (§5.3)
4. Implement a dead-letter queue for undeliverable events (§5.4)
5. Implement the Event Store with append-only semantics and the required indexes (§6.1)
6. Provide the Replay API (§6.2) with minimum 10,000 events/second throughput
7. Implement snapshot and compaction as defined in §6.3
8. Implement the Schema Registry with publish-time validation (§7.2)
9. Enforce schema evolution compatibility (§7.3)
10. Reject events with unregistered or incompatible types (§7.2)

---

## 10. Open Questions

1. **Partitioning strategy** — should the Bus partition by `execution_id` (natural ordering) or by `event_type` (load balancing)?
2. **Event deduplication** — does the Store need exactly-once deduplication, or is at-least-once + idempotent consumers sufficient?
3. **Cross-process Backbone** — should v2 use an existing system (Kafka, NATS, RabbitMQ) or a custom implementation?
4. **Event retention enforcement** — who enforces retention policies? The Store (actively delete) or a separate housekeeping process?
5. **Dead-letter alerting** — should dead-lettered events trigger alerts? To whom?

---

## 11. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.9 | Event entity definition |
| RFC-0001 §6 | Event Schema (concrete event types the Backbone must carry) |
| RFC-0102 §10 | Engine State Recovery (depends on Event Store Replay API) |
| RFC-0200 §4.5 | Streaming output (depends on Event Bus delivery) |
| RFC-0202 §10.2 | Negotiation events (published via Backbone) |
| RFC-0104 §8.3 | Rule lifecycle events (published via Backbone) |
| ADR-0001 | Event Sourcing pattern (architectural justification) |
| Constitution Article 4 | All cross-module communication via Event Backbone |
