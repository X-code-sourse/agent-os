# CONSTITUTION — Architectural Constitution of Agent OS

**Status: Accepted**

This document defines the **Architectural Constitution** — principles that must never be violated. They are organized in three layers by severity. Violations of Layer I are architecture bugs. Violations of Layer II are design flaws. Violations of Layer III should trigger an ADR.

---

## Layer I: Core Constitution (Inviolable)

### Article 1: The Kernel Must Be Stateless
The Kernel (Control Plane) must never hold persistent state. All state must be written to the Data Plane as Events. The Kernel can be destroyed and recreated at any time by replaying Events from the Event Store. This enables horizontal scaling, high availability, and fault recovery.

### Article 2: The Execution Engine Is the Sole Scheduler
No module other than the Execution Engine may dispatch a Task. Capabilities must never call other Capabilities. All execution must flow through the Execution Engine. This guarantees that every action is observable, auditable, and governable from a single point.

### Article 3: All Persistent State Must Live in the Data Plane
No module may hold its own persistent state. No in-memory maps, no local files, no hidden databases. Every module that needs durable state must write it to the Data Plane. This prevents modules from becoming opaque stateful black boxes.

### Article 4: All Cross-Module Communication Must Go Through the Event Backbone
No module may directly call another module's method. No shared memory. No direct function calls across module boundaries. All communication must be published as Events on the Event Bus. This ensures the Event Store remains the single source of truth.

---

## Layer II: Boundary Constitution (Responsibility Isolation)

### Article 5: Workflow Describes Flow Only
A Workflow defines the order and dependency of Tasks. It must never contain domain-specific constraints (e.g., "must use SEC filings"). That is the responsibility of Rules.

### Article 6: Rule Describes Constraint Only
A Rule defines constraints on Task behavior or output. It must never describe flow (e.g., "run research before analysis"). That is the responsibility of Workflows.

### Article 7: Capability Implements Ability Only
A Capability provides a functional unit (Research, Python, Browser). It must never contain business process logic (e.g., "after research, run risk analysis"). That is the responsibility of Workflows and Rules.

### Article 8: Workflow Depends on Capability Requirements, Not Implementations
A Workflow declares what it needs via Capability Requirements (type, domain, quality, cost). It must never reference a specific Capability by name or version. Resolution is the job of the Registry.

---

## Layer III: Evolution Constitution (Growth Principles)

### Article 9: Planner Optimizes at Compile Time Only (v1)
The Planner generates the Execution DAG at compile time. At runtime (v1), the Execution Engine must not structurally modify the DAG. If modification is needed, the Engine must emit a ReplanRequest and the Planner generates a new DAG.

### Article 10: Loop Has Suggestion Rights Only
The Loop Manager and its sub-engines (Learning, Optimization, Evaluation, Analytics) may analyze data, detect patterns, and suggest changes. They must never modify Rules, Workflows, or Configurations directly. All changes must pass through Human Governance.

### Article 11: The Metadata Registry Is the Only Discovery Entry Point
No hardcoded Capability references. No hardcoded Workflow references. All discovery must go through the Registry. This enables hot-swapping Capabilities, Workflows, and Rules without code changes.

### Article 12: Model Selection Is a Capability Internal Concern
The Execution Engine must never know which model a Capability uses. Model selection, swapping, and optimization are internal decisions of each Capability. The Engine only knows that a Capability met its declared Requirements.

---

## Amendment Process

The Constitution is not immutable. To amend:
1. File an ADR proposing the change
2. The ADR must explain why the existing Article is insufficient
3. Maintainers review and vote
4. If accepted, the Article version increments
5. All affected specifications are updated accordingly
