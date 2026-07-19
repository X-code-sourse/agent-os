# TERMS — Agent OS Glossary

Quick reference for Agent OS terminology.

| Term | Definition |
|------|------------|
| Agent OS | An AI-native operating platform specification and reference runtime |
| Goal | A user's declarative end-state description, containing no process details |
| Intent | The system's structured understanding of a Goal (domain, task type, priority) |
| Session | A user interaction context grouping related Goals and Executions. Provides resource isolation and Memory scoping |
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
| Event Backbone | The message backbone for all cross-module communication. Also referred to as Event Bus (usage note: Event Backbone in Constitution, Event Bus in code; they are the same concept) |
| Event Bus | See Event Backbone |
| Event Store | The persistent storage of all Events, serving as the single source of truth |
| Execution Plan | The compiled DAG produced by the Planner from a Workflow + Rules + Profile |
| Execution Graph | The runtime instance of an Execution Plan with per-Task state |
| Execution Record | An auditable, replayable snapshot of one complete execution |
| Planner | The compile-time module that compiles Workflows + Rules into Execution Plans |
| Execution Engine | The runtime module that schedules Tasks. Sole owner of execution control |
| Module | A functional component within Agent OS (e.g., Planner, Execution Engine, Reviewer). Modules communicate exclusively through the Event Backbone |
| Reviewer | Quality assurance module (local: per-Task; global: per-Execution) |
| Security Manager | Access control module for sensitive resources |
| Memory Manager | Data Plane module managing Knowledge, Memory, Cache, Vector, Event Stores |
| Knowledge | World knowledge — shared, read-only, governed |
| Memory | Running experience — private, read-write, auto-accumulated |
| Experience | Cross-session reusable patterns learned by the Loop |
| Loop | The evolutionary subsystem (Learning, Optimization, Evaluation, Analytics engines) |
| Registry | The Metadata Plane's service for capability/workflow/rule discovery |
| Kernel | The Control Plane as a whole — all modules (Intent Engine, Workflow Resolver, Planner, Execution Engine, Rule Manager, Security Manager) collectively form the Kernel |
| User Plane | The layer where users state Goals declaratively |
| Control Plane | The Kernel layer — stateless, holds sole scheduling authority |
| Metadata Plane | The registry layer — versioned, discoverable definitions |
| Data Plane | The persistence layer — all durable state lives here |
| Runtime Plane | The execution layer — Capabilities, Models, Tools, Reviewer, Loop |
