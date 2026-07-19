# PHILOSOPHY — Design Philosophy of Agent OS

**Status: Accepted**

Agent OS follows a set of design beliefs that guide every architectural decision. These are not rules — they are values. When faced with a tradeoff, the option that aligns with more of these principles wins.

---

## Everything is a Task

The Execution Engine schedules one thing and one thing only: Tasks. Review is a Task. Learning is a Task. Memory sync is a Task. Report generation is a Task. Just as Linux treats everything as a process, Agent OS treats everything as a Task.

## Everything is Declarative

Users write what they want, not how to do it. Workflow authors define flow and constraints, not implementations. The Planner compiles declarations into executable plans; the Execution Engine runs plans. Declarative inputs produce predictable, auditable outputs.

## Everything is Discoverable

No hardcoded capability references. Workflows declare Capability Requirements; the Registry resolves them via Capability Negotiation. A Workflow never says "call Research v1.8" — it says "I need research, finance domain, English, cost < 0.5." The platform finds the best match at runtime.

## Everything is Versioned

Workflows have versions. Rules have versions. Capabilities have versions. Execution Records capture every version used. Any execution can be replayed exactly because every dependency is pinned in the record.

## Everything is Observable

No black boxes. Every state transition publishes an Event. Every Event is stored in the Event Store. The Execution Engine's entire state can be reconstructed by replaying Events. Cost, latency, token usage, and failure reasons are always available.

## Everything is Replayable

An Execution Record contains everything needed to reproduce an execution: workflow version, rule versions, capability versions, model versions, input hash. If something went wrong, you don't debug — you replay.

## Everything is Governed

AI can suggest. AI can experiment. But Rules are always approved by humans. The Rule Governance process follows a Git-like model: propose, review, approve (or experiment), merge. Loop only has suggestion rights, never modification rights.

## Everything has a Single Owner

Every object has exactly one owner plane. Workflows belong to Metadata. Tasks belong to the Execution Engine. Events belong to the Event Store. Rules belong to Governance. Capabilities belong to Runtime. Clear ownership prevents responsibility creep.
