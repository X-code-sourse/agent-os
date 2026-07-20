# RFC-0203: Runtime Scheduling

**Status:** Draft
**Type:** Runtime RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0200 v1.0, RFC-0201 v1.0, RFC-0202 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Runtime Scheduling subsystem** — how the Capability Pool (RFC-0200 §5) manages concurrent invocations, queues backlog, allocates instances, scales capacity, and protects against overload. It completes the Runtime Plane by defining the operational behavior of the Pool beyond the invocation interface.

---

## 2. Motivation

RFC-0200 defines the *interface* between the Execution Engine and the Capability Pool (invoke, cancel, stream). RFC-0201 defines the *performance claims* a Capability makes (max_concurrent, queue_depth). But neither defines how the Pool actually schedules work:

- What happens when 20 Tasks arrive for a Capability with `max_concurrent: 5`?
- How does the Pool prioritize a high-priority Execution over a low-priority batch job?
- When a Capability instance crashes, how does the Pool recover?
- How does the Pool scale instances up and down based on demand?
- How does the Pool protect itself from overload when all Queues are full?

---

## 3. Pool Architecture

```
Execution Engine (RFC-0102)
    │
    │ invoke(task_id, capability_id, ...)
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         CAPABILITY POOL                              │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                   Scheduler (dispatcher)                      │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │  │
│  │  │  Priority   │  │  Per-Cap    │  │  Per-Model           │ │  │
│  │  │  Queue      │  │  Queue      │  │  Queue               │ │  │
│  │  └─────────────┘  └─────────────┘  └──────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                   Instance Manager                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │  │
│  │  │  Research   │  │  Python     │  │  Browser             │ │  │
│  │  │  (3 inst.)  │  │  (2 inst.)  │  │  (1 inst.)           │ │  │
│  │  └─────────────┘  └─────────────┘  └──────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                   Health Monitor                              │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │  │
│  │  │  Heartbeat  │  │  Crash      │  │  Graceful            │ │  │
│  │  │  Checker    │  │  Detector   │  │  Drainer             │ │  │
│  │  └─────────────┘  └─────────────┘  └──────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
    │
    │ route to instance
    ▼
Capability Instance (claude-sonnet-4, research)
```

### 3.1 Internal Components

| Component | Responsibility |
|-----------|---------------|
| **Scheduler** | Receives `invoke` requests from Engine, enqueues, applies priority, dispatches to available instances |
| **Instance Manager** | Maintains the pool of loaded Capability instances (start, stop, health check) |
| **Health Monitor** | Periodically checks instance health, detects crashes, coordinates drain |

---

## 4. Queuing Model

### 4.1 Multi-Level Queue Structure

The Pool maintains three levels of queues:

```
Level 1: Global Priority Queue
    │  All incoming invocations enter here first
    │  Sorted by: execution priority (high > normal > low), then FIFO within priority
    │
    ▼
Level 2: Per-Capability Queue
    │  One queue per capability_id
    │  Configurable max depth (from Manifest: throughput.queue_depth)
    │  If full → reject with Pool:QueueFull
    │
    ▼
Level 3: Per-Model Queue
    │  One queue per model (e.g., "claude-sonnet-4")
    │  Ensures per-model concurrency limits are respected
    │  If model overloaded → backpressure to Per-Capability Queue
    │
    ▼
Dispatch to Instance
```

### 4.2 Queue Entry Lifecycle

```
invoke_received
    │
    ├─► Global Priority Queue (sorted by priority)
    │
    ├─► Per-Capability Queue (FIFO within same priority)
    │      │
    │      ├── capacity available → move to Model Queue
    │      │
    │      └── queue full → reject (Pool:QueueFull)
    │
    ├─► Per-Model Queue (FIFO)
    │      │
    │      ├── instance available → dispatch immediately
    │      │
    │      └── all instances busy → wait (polling at 100ms)
    │
    └─► dispatcher assigns to instance → Capability:Running
```

### 4.3 Rejection Behavior

When a queue is full:

```json
// Pool rejects the invocation
{
  "status": "rejected",
  "reason": "queue_full",
  "capability_id": "cap://nous-research/research-v2",
  "queue_depth": 50,
  "queue_limit": 50,
  "retry_after_ms": 5000,
  "alternative": "cap://community-research/research-lite"  // If available
}
```

The Engine may react by:
1. Retrying after `retry_after_ms`
2. Re-negotiating (RFC-0202) to find an alternative Capability
3. Failing the Task gracefully (if no alternative and retries fail)

---

## 5. Priority Scheduling

### 5.1 Priority Levels

| Level | Default Source | Preempts Lower? | Use Case |
|-------|---------------|-----------------|----------|
| `critical` | Security Manager, user-interactive | Yes | Security scan, user-facing response |
| `high` | Execution priority from Intent | Yes | Paid users, time-sensitive tasks |
| `normal` | Default | No | Standard execution |
| `low` | Batch processing, Loop analysis | No | Overnight analytics, non-urgent tasks |

### 5.2 Priority Assignment

Priority is assigned by the Execution Engine when invoking:

```json
{
  "invocation_id": "invoc://pool_001/task_003",
  "task_id": "task://exec_001/003",
  "capability_id": "cap://nous-research/research-v2",
  "priority": "high",          // From Execution's priority
  "deadline": "2026-07-19T10:05:00Z",
  "estimated_duration_ms": 5000
}
```

### 5.3 Priority Inversion Protection

To prevent priority inversion (a high-priority Task waiting on a low-priority one occupying the only available instance):

```python
def dispatch(instance, queue):
    """Pick the next invocation from the queue hierarchy."""
    # Check Model Queue first — if a high-priority task is waiting,
    # it must not be blocked by a low-priority task holding the instance.

    queued = queue.per_model[instance.model].peek_all()

    # If a high-priority item is waiting AND the running task is low-priority:
    if any(item.priority == "high" for item in queued) \
       and instance.current_invocation.priority == "low":
        # Preempt: pause the low-priority task (if Capability supports it)
        instance.pause(instance.current_invocation.invocation_id)
        instance.current_invocation = None
        # Move paused task back to queue
        queue.per_model[instance.model].re_enqueue(paused_task)
        # Dispatch high-priority task
        return dispatch_high_priority(instance, queue)

    return queue.per_model[instance.model].dequeue()
```

Preemption is **optional** (Capability must declare `supports_preemption: true` in Manifest). If not supported, the high-priority task waits for the current invocation to complete.

---

## 6. Concurrency Control

### 6.1 Concurrency Limits Hierarchy

```
Limit Type               Source                  Default
─────────────────────────────────────────────────────────────
Global pool limit        System config            100 instances
Per-capability limit     Manifest throughput.max_concurrent
Per-model limit          Model Registry config    20 instances/model
Per-user/session limit   Profile / Security config Unlimited (v1)
```

### 6.2 Limit Enforcement

```
invoke(task)
    │
    ├─ Check Global: active_instances >= global_limit → Queue (level 1)
    │
    ├─ Check Per-Capability: active_for_capability >= manifest.max_concurrent → Queue (level 2)
    │
    ├─ Check Per-Model: active_on_model >= model_limit → Queue (level 3)
    │
    └─ All checks pass → dispatch immediately
```

### 6.3 Backpressure Propagation

When a lower-level queue fills up, backpressure propagates upward:

```
Per-Model Queue full
    │ → backpressure to Per-Capability Queue
    │     → Per-Capability Queue stops pulling from this model
    │     → if all models for this capability are blocked:
    │         → Per-Capability Queue fills up
    │         → backpressure to Global Priority Queue
    │             → Engine receives Pool:QueueFull
```

---

## 7. Instance Lifecycle

### 7.1 Instance States

```
[Unloaded] ──► [Loading] ──► [Ready] ──► [Busy] ──► [Idle] ──► [Draining] ──► [Unloaded]
                    │                        │                           │
                    ▼                        ▼                           ▼
               [Failed]                [Failed (crash)]            [Unloaded (done)]
```

| State | Description |
|-------|-------------|
| `Unloaded` | Not loaded in the Pool |
| `Loading` | Instance being initialized (model loading, config) |
| `Ready` | Available for invocation |
| `Busy` | Currently executing a Task |
| `Idle` | Loaded but idle; eligible for unload after idle_timeout |
| `Draining` | Shutting down; no new invocations; finishing current |
| `Failed` | Instance crashed or unhealthy |
| `Failed (crash)` | Instance crashed while Busy; recovery triggered |

### 7.2 Instance Loading

Instances are loaded on demand or pre-warmed:

```python
def ensure_instances(capability_id, model, min_ready=1):
    """Ensure at least min_ready instances are Ready."""
    ready_count = count_ready_instances(capability_id, model)

    if ready_count < min_ready:
        instances_needed = min_ready - ready_count
        for _ in range(instances_needed):
            load_instance(capability_id, model)
```

**Loading triggers:**
1. Registry notifies Pool of a newly registered Manifest
2. Queue depth exceeds threshold (demand-based scaling)
3. Pre-warming: Profile specifies `min_warm_instances`

### 7.3 Instance Unloading

Instances are unloaded after an idle period:

```python
def unload_idle_instances():
    for instance in pool.instances:
        if instance.state == "idle":
            idle_duration = now() - instance.last_active_at
            if idle_duration > instance.manifest.idle_timeout_ms:
                if count_ready_instances(instance.capability_id) > min_instances:
                    instance.drain()
```

**Default idle_timeout:** 300 seconds (configurable in Manifest).

---

## 8. Health Monitoring

### 8.1 Health Check Protocol

The Health Monitor pings every loaded instance at a fixed interval:

```json
// Health check request (Pool → Instance)
{
  "type": "health_check",
  "check_id": "health://pool_001/check_047",
  "sent_at": "2026-07-19T10:00:30.000Z",
  "deadline_ms": 2000
}

// Health check response (Instance → Pool)
{
  "check_id": "health://pool_001/check_047",
  "status": "healthy",            // healthy | degraded | unhealthy
  "latency_ms": 150,
  "load": {                       // Optional: instance-reported load
    "active_invocations": 1,
    "queue_depth": 0,
    "memory_usage_pct": 62,
    "model_loaded": "claude-sonnet-4"
  }
}
```

### 8.2 Health Status

| Status | Definition | Pool Action |
|--------|------------|-------------|
| `healthy` | Instance responding normally | Normal dispatch |
| `degraded` | Instance responding but with high latency or errors | Dispatch with lower priority; flag for Observation |
| `unhealthy` | Instance not responding or returning errors | Stop dispatching; trigger drain; load replacement |

### 8.3 Crash Recovery

When a Busy instance crashes:

```
1. Health Monitor detects missed heartbeat (2 consecutive misses)
2. Instance state → Failed (crash)
3. Capability Pool publishes Capability:Error { error: "instance_crashed", retryable: true }
4. Engine receives error → evaluates retry (RFC-0001 §4.2)
5. Pool loads a replacement instance
6. If crash rate exceeds threshold (5 crashes/hour) → Flag for Loop analysis
```

---

## 9. Demand-Based Scaling

### 9.1 Scaling Algorithm

```
Every 60 seconds:
    For each capability_id:
        queue_depth = per_capability_queue[capability_id].depth()
        active = count_busy_instances(capability_id)

        if queue_depth > active * 2 AND active < manifest.max_concurrent:
            # Demand exceeds capacity: scale up
            scale_up(capability_id, by=min(2, manifest.max_concurrent - active))

        if queue_depth == 0 AND idle_time > idle_timeout:
            # No demand and idle: scale down
            scale_down(capability_id, by=1)
```

### 9.2 Scale Constraints

| Constraint | Source | Behavior |
|------------|--------|----------|
| Min instances | Manifest or System config | Never scale below this |
| Max instances | Manifest `performance.throughput.max_concurrent` | Never scale above this |
| Scale-up cooldown | 30 seconds | Wait 30s between scale-up events |
| Scale-down cooldown | 120 seconds | Wait 2min between scale-down events |
| Instance startup time | Manifest-dependent | During startup, queue accumulates |

---

## 10. Rate Limiting

### 10.1 Rate Limit Hierarchy

| Level | Limit | Enforced At |
|-------|-------|-------------|
| Global | Max invocations/second (configurable, default: 1000) | Global Priority Queue |
| Per-Capability | Manifest-defined or system default | Per-Capability Queue |
| Per-Model | Model Registry limit | Per-Model Queue |
| Per-Execution | Profile `cost_budget.max_per_execution` | Engine (before invoking) |

### 10.2 Rate Limit Response

When a rate limit is hit:

```json
{
  "status": "rate_limited",
  "limit_type": "per_capability",
  "capability_id": "cap://nous-research/research-v2",
  "limit": 50,
  "current_rate": 52,
  "retry_after_ms": 2000
}
```

---

## 11. Pool API (Complete)

Extending RFC-0200 §5.2 with scheduling-specific fields:

```json
// invoke — now includes priority and scheduling hints
{
  "invocation_id": "invoc://pool_001/task_003",
  "task_id": "task://exec_001/003",
  "capability_id": "cap://nous-research/research-v2",
  "priority": "high",
  "deadline": "2026-07-19T10:05:00Z",
  "scheduling_hints": {
    "estimated_duration_ms": 5000,
    "preemption_allowed": false,
    "max_queue_wait_ms": 30000
  },
  "input": {...},
  "config": {...}
}

// response — may include scheduling metadata
{
  "status": "queued",
  "queue_position": 3,
  "estimated_wait_ms": 4000,
  "dispatched_to": null
}

// or, on dispatch:
{
  "status": "dispatched",
  "instance_id": "inst://pool/research-v2-003",
  "model": "claude-sonnet-4",
  "estimated_duration_ms": 5000
}
```

---

## 12. Compliance

Any implementation claiming Agent OS Runtime Scheduling compatibility **must**:

1. Implement the three-level queue model (§4) with Global, Per-Capability, and Per-Model queues
2. Support the four priority levels: critical, high, normal, low (§5.1)
3. Implement priority inversion protection (§5.3)
4. Enforce concurrency limits at all three levels (§6)
5. Implement backpressure propagation (§6.3)
6. Implement the full instance lifecycle: Loading → Ready → Busy → Idle → Draining → Unloaded (§7)
7. Implement health monitoring with the three health statuses (§8)
8. Implement demand-based scaling with cooldown constraints (§9)
9. Implement rate limiting at all four levels (§10)

---

## 13. Open Questions

1. **Instance pooling across models** — can a single instance serve multiple models (model multiplexing), or is it strictly one model per instance?
2. **Predictive scaling** — should the Pool use historical patterns to pre-warm instances before demand spikes?
3. **Instance locality** — in a distributed deployment, should the Pool prefer instances on the same node as the Engine to reduce latency?
4. **Cost-aware scheduling** — should the Scheduler consider per-invocation cost when choosing between instances of the same Capability but different models?

---

## 14. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.7 | Capability Manifest (performance.throughput fields) |
| RFC-0200 §5 | Capability Pool interface (invoke, cancel, subscribe) |
| RFC-0200 §5.4 | Pool Invocation Flow (this RFC fills in the scheduling details) |
| RFC-0201 §4.5 | Performance fields (max_concurrent, queue_depth used here) |
| RFC-0201 §4.4 | Features (supports_preemption flag) |
| RFC-0202 §4.2 | Profile preferences (priority level from Intent) |
| RFC-0102 §4.5 | Engine ↔ Pool contract (invocation lifecycle) |
