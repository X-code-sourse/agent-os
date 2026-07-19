# TERMS — Agent OS Glossary

Quick reference for Agent OS terminology.

| Term | Definition |
|------|------------|
| Agent OS | An AI-native operating platform specification and reference runtime |
| Goal | A user's declarative end-state description, containing no process details |
| Intent | The system's structured understanding of a Goal (domain, task type, priority) |
| Workflow | A declarative Graph describing Task dependencies and execution order. Contains no domain constraints |
| Task | The smallest schedulable execution unit. The only object the Execution Engine schedules |
| Rule | A Constraint that limits Task behavior or output. Contains no flow information |
| Rule Governance | The version management, approval, and A/B testing process for Rules |
| Profile | A cross-cutting configuration that controls Capability behavior for one execution |
| Capability | A reusable functional unit (Research, Python, Browser...) |
| Capability Requirement | A Workflow's declaration of what it needs from a Capability (type, domain, cost, quality...) |
| Capability Manifest | A Capability's published declaration for Registry-based discovery |
| Capability Negotiation | The process by which the Registry matches Requirements to Manifests |
| Event | An immutable fact record of a state change in the system |
| Event Bus | The message backbone for all cross-module communication |
| Event Store | The persistent storage of all Events, serving as the single source of truth |
| Execution Plan | The compiled DAG produced by the Planner from a Workflow + Rules |
| Execution Graph | The runtime instance of an Execution Plan with per-Task state |
| Execution Record | An auditable, replayable snapshot of one complete execution |
| Planner | The compile-time module that compiles Workflows + Rules into Execution Plans |
| Execution Engine | The runtime module that schedules Tasks. Sole owner of execution control |
| Reviewer | Quality assurance module (local: per-Task; global: per-Execution) |
| Security Manager | Access control module for sensitive resources |
| Memory Manager | Data Plane module managing Knowledge, Memory, Cache, Vector, Event Stores |
| Knowledge | World knowledge — shared, read-only, governed |
| Memory | Running experience — private, read-write, auto-accumulated |
| Experience | Cross-session reusable patterns learned by the Loop |
| Loop | The evolutionary subsystem (Learning, Optimization, Evaluation, Analytics engines) |
| Registry | The Metadata Plane's service for capability/workflow/rule discovery |
