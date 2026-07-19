# ADR-0001: Why We Use Event Sourcing

**Status:** Accepted
**Date:** 2026-07-19
**Author:** Architecture Team

## Context

The Agent OS Kernel must be stateless (Constitution Article 1). This means no in-memory execution state survives a restart. We need a mechanism to:

1. Recover execution state after a Kernel crash
2. Provide a complete audit trail of all system actions
3. Enable Observability without invasive logging
4. Support system replay for debugging and learning

## Decision

We adopt **Event Sourcing** as the core persistence pattern for the Control Plane.

All state changes are published as Events to the Event Bus. The Event Bus delivers events to subscribers and persists them in the Event Store. The Execution Engine's state is a projection of the Event stream — it can be destroyed and rebuilt at any time by replaying events.

## Consequences

**Positive:**
- Kernel becomes fully stateless (no persistent state, no crash recovery code)
- Event Store becomes the single source of truth
- Complete audit trail by default (every state change is recorded)
- Replayability enables debugging and Loop learning
- Multiple Kernel instances can share the same Event Store (horizontal scaling)

**Negative:**
- Event schema evolution must be managed (version field in every Event)
- Event Store becomes a critical infrastructure dependency
- Event replay performance matters for crash recovery speed
- Snapshot mechanism may be needed for long-running executions

## Alternatives Considered

1. **In-memory state with periodic snapshots** — Rejected because it violates Constitution Article 1 (Kernel holds state) and creates a window of data loss between snapshots.
2. **Write-ahead log (WAL)** — Rejected because it couples the state management to a specific execution engine implementation. Event Sourcing provides a protocol-level abstraction.
3. **No persistence (volatile only)** — Rejected because fault tolerance and auditability are requirements, not nice-to-haves.

## Implementation Notes

- v1: In-memory Event Bus with Event Store backed by SQLite or similar
- v2: Replace with distributed Event Backbone (e.g., Kafka, NATS) for HA
- All Events carry a `version` integer for schema evolution
- Event Store supports `replay(execution_id)` to rebuild a single execution state
