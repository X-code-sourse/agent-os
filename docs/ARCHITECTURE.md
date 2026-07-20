# Agent OS — Architecture

## System Architecture

```mermaid
graph TB
    subgraph "User Plane"
        G[Goal]
    end

    subgraph "Event Backbone"
        EB[Event Bus]
        ES[Event Store]
    end

    subgraph "Control Plane"
        IE[Intent Engine] --> WR[Workflow Resolver]
        WR --> PL[Planner]
        PL --> EE[Execution Engine]
        RM[Rule Manager]
        SM[Security Manager]
    end

    subgraph "Metadata Plane"
        REG[Registry<br/>Workflows / Rules /<br/>Capabilities / Profiles]
    end

    subgraph "Data Plane"
        MM[Memory Manager<br/>Knowledge / Memory / Cache / Vector]
    end

    subgraph "Runtime Plane"
        CP[Capability Pool]
        MP[Model Pool]
        TP[Tool Pool]
        RV[Reviewer]
        LP[Loop Engines]
    end

    G --> IE
    EE --> EB
    EB --> ES
    EB --> RM
    EB --> SM
    EB --> MM
    EB --> CP
    EB --> RV
    EB --> LP
    PL --> REG
    RM --> REG
    CP --> MP
    CP --> TP
    EE --> CP
    RV -.->|Events| EB
    LP -.->|Events| EB
```

## Layers

| Plane | Role |
|-------|------|
| **User Plane** | Goal entry point — users state *what*, not *how* |
| **Event Backbone** | Event bus + event store — the system's nervous system |
| **Control Plane** | Intent → Workflow → Plan → Execution. Rules & security enforcement |
| **Metadata Plane** | Registry of all objects — workflows, rules, capabilities, profiles |
| **Data Plane** | Memory, knowledge, cache, and vector storage |
| **Runtime Plane** | Capability pool, model pool, tool pool, reviewer, loop engines |

## Design Principles

Agent OS follows a layered, event-driven architecture where each plane has a well-defined responsibility. The Kernel (Control Plane) manages orchestration without executing any capability itself — capabilities are pluggable and shared across all workflows.

See [CONSTITUTION.md](vision/CONSTITUTION.md) for the full set of architectural principles and [SPEC-0000](spec/SPEC-0000-core-concepts.md) for the object model.
