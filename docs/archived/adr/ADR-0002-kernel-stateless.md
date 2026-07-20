# ADR-0002: Why the Kernel Must Be Stateless

**Status:** Accepted
**Date:** 2026-07-19
**Author:** Architecture Team

## Context

Constitution Article 1 states the Kernel must be stateless. This ADR documents why this decision was made over the alternatives.

## Decision

The Kernel (Control Plane) never holds persistent state. All state is written to the Data Plane as Events. The Kernel can be destroyed and recreated at any time by replaying Events from the Event Store.

## Consequences

**Positive:**
- **Horizontal scaling:** Multiple Kernel instances can run behind a load balancer, sharing the same Event Store
- **High availability:** If a Kernel instance crashes, another instance replays the Event stream and resumes
- **Fault isolation:** A corrupted Kernel instance is disposable — destroy it and start a new one
- **No state migration:** Adding or removing Kernel instances requires no state transfer
- **Deterministic rebuild:** The exact system state can be reconstructed from the Event Store at any point

**Negative:**
- Event Store must be highly available (it's the single source of truth)
- Event replay latency affects recovery time
- Snapshot strategy needed for long-running executions with many events

## Alternatives Considered

1. **Kernel with embedded database (e.g., SQLite, BoltDB)** — Rejected because it prevents horizontal scaling and creates state migration problems. Also creates a temptation for modules to hold additional "convenient" state outside the database, violating auditability.

2. **Kernel with in-memory state + checkpoints** — Rejected because checkpoint frequency creates a tradeoff between data loss window and performance. Event Sourcing eliminates data loss entirely.

3. **Distributed Kernel with shared state (e.g., Redis, etcd)** — Rejected for v1 due to operational complexity. Stateless Kernel + Event Store is a simpler starting point that can be upgraded to a distributed state store later without changing the architecture.
