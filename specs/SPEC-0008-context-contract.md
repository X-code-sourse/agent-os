# SPEC-0008: Context Contract

> **Status:** Frozen v1.0 — Phase 2 (data model implemented, auto-injection + sharing Phase 2+)
> **Scope:** Defines the portable Context specification — the structured environment an Agent operates within, valid across any Runtime
> **Editor:** Intent OS Project

---

## 1. Purpose

The Context Contract defines **a formal, runtime-agnostic specification of the execution environment an Agent needs to operate**. It answers:

> **What is this Agent supposed to do, under what constraints, with what resources, and informed by what past experience?**

Context is NOT:
- ❌ User-preference memory ("the user likes coffee")
- ❌ Chat history ("what was said last session")
- ❌ A prompt prefix

Context IS:
- ✅ A structured contract of the task environment
- ✅ Shared across Agents (one Context, many Agents)
- ✅ Versioned (changes over time, like a Git commit)
- ✅ Portable (valid on any Runtime)
- ✅ Composable (Contexts can inherit from parent Contexts)

---

## 2. The Role of Context in the Execution Contract

Context is Layer 1 of the 7-layer Execution Contract, but its role is unique: it is the **declarative layer** — the "what" before any "how".

```
Context (Layer 1)  ── "Here is the task, the limits, and what we know."
    │
Identity (Layer 2) ── "Here is who will do it."
    │
Execution ── ... ── Experience (Layer 7)
    │
    └── Experience feeds back into Context for the NEXT execution
```

The feedback loop is the key: Execution produces Experience, Experience updates Context, Context shapes the next Execution. Without Context, Experience has nowhere to land. Without Experience, Context is static.

---

## 3. Specification

### 3.1 Canonical Context Format

```yaml
kind: Context
context_id: ctx_<12hex>       # Globally unique, generated at creation
version: integer               # Monotonically increasing version number
name: string                   # Human-readable identifier
owner: string                  # Agent ID, User ID, or Org ID

spec:
  objective: string            # What this Context is supposed to achieve
  constraints: list[string]    # Hard limits (e.g., "SEC data only", "No trading")
  task_scope: string           # Domain classification (research, trading, coding, ...)
  environment:                 # Runtime environment requirements
    resources: list[string]    # Required data sources, APIs, tools
    variables: map             # e.g., tickers, date ranges, model preferences
    runtime_hints: map         # Non-binding: preferred models, latency targets, ...

  knowledge:                   # References to prior work (not the data itself)
    experience_refs: list[string]  # experience_ids relevant to this Context
    evidence_refs: list[string]    # evidence_ids that established key facts
    execution_refs: list[string]   # trace_ids of related past executions

  governance:                  # Policy boundaries inherited by Agents in this Context
    policy_refs: list[string]

  lifecycle:
    created_at: ISO8601
    created_by: string
    expires_at: ISO8601 | null
    parent_context_id: string | null  # Inheritance chain
```

### 3.2 Context ID

Format: `ctx_<12hex>` — generated at creation, immutable.

The Context ID is the primary key through which all executions, experiences, and evidence records reference the task environment. Without it, you cannot answer "was this execution done under the same constraints as that one?"

### 3.3 Versioning

Every update to a Context increments `version`. A Context version is a snapshot of the task environment at a point in time.

```
ctx_production_us_equities v1 → v2
  + Added constraint: "No pre-market data"
  + Added resource: "Bloomberg Terminal"

ctx_production_us_equities v3
  + Updated objective: "Find value AND growth plays"
```

Versioning enables:
- Reproducibility: "Run this again with the same Context as last month"
- Audit: "What constraints were in effect when this execution happened?"
- Diff: "What changed between v2 and v3?"

### 3.4 Inheritance

A Context can declare a `parent_context_id`. Child Contexts inherit all constraints, resources, and knowledge from their parent, and may add or override.

```
Company Research Context (v1)
  │ constraint: "SEC filings only"
  │ resource: "EDGAR API"
  │
  ├── Tesla Analysis (v1, parent=Company Research)
  │     │ + constraint: "EV market focus"
  │     │ + variable: ticker=TSLA
  │
  ├── Apple Analysis (v1, parent=Company Research)
  │     │ + constraint: "Hardware + Services segments"
  │     │ + variable: ticker=AAPL
  │
  └── Sector Analysis (v1, parent=Company Research)
        │ + objective: "Compare across all holdings"
        │ + resource: "Portfolio database"
```

### 3.5 Context ↔ Agent Binding

A Context is assigned to one or more Agents via a junction table:

```sql
CREATE TABLE context_assignments (
    context_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (context_id, agent_id)
);
```

A single Context can be shared by multiple Agents (e.g., Research Agent, Trading Agent, and Risk Agent all operate under the same "Q3 US Equities" Context). This is what enables multi-agent collaboration: they all operate under the same declared rules.

### 3.6 Context ↔ Execution Binding

Every Execution Record can carry a `context_id`:

```sql
ALTER TABLE execution_records ADD COLUMN context_id TEXT;
```

This links every execution to the Context it was performed under, enabling:
- "Show me all executions done for this project"
- "Compare what Agent A and Agent B did under the same Context"
- "What Context was this execution done under? Was it v3 or v4?"

---

## 4. Context Injection Protocol (Phase 2+)

The Context should be **injected** into the Agent's runtime, not manually provided by the user.

```
Agent starts
    │
    ▼
Intent OS resolves context (by agent_id, by name, or by task matching)
    │
    ▼
Context is serialized into a runtime-neutral representation
    │
    ▼
Adapter translates into runtime-specific format
    │
    ▼
Agent executes with context-constrained behavior
```

The injection protocol is defined here, but auto-injection is **Phase 2+**. Today, Context can be manually loaded via CLI.

---

## 5. Context + Experience Loop

The most valuable Context is one that evolves with experience.

```
Execution 1 (ctx_v1)
    │
    ├── Failure: "EDGAR API times out during market open"
    │   └── Experience: exp_001 (failure_pattern, confidence: 0.91)
    │
    ├── Context evolves to v2
    │   └── + constraint: "Queue EDGAR requests during 9:30-10:00 ET"
    │   └── + experience_ref: exp_001
    │
Execution 2 (ctx_v2)
    │
    └── Success: avoided EDGAR timeout by queuing
```

The Experience reference in Context is the bridge: it tells the Agent *what we already learned about this task environment* before it starts executing.

---

## 6. CLI Interface

```bash
# Create a Context
intent-os context create --name "Q3 Research" \
  --goal "Find undervalued S&P 500 stocks" \
  --constraint "SEC filings only" \
  --scope research \
  --created-by "agent_research_001"

# Assign an Agent to a Context
intent-os context assign ctx_abc123 --agent agent_research_001

# List Contexts for an Agent
intent-os context list --agent agent_research_001

# Inspect a Context (including version, assignments, related experiences)
intent-os context inspect ctx_abc123

# List Agents assigned to a Context
intent-os context agents ctx_abc123

# Delete a Context
intent-os context delete ctx_abc123

# Future Phase 2+:
# intent-os context diff ctx_abc123 v1 v3
# intent-os context share ctx_abc123 --team team_research
# intent-os context inject --agent agent_research_001
```

---

## 7. Current Implementation Status

| Capability | Status | Notes |
|-----------|--------|-------|
| Context storage (SQLite) | ✅ Implemented | `context_store.py`, `~/.intent-os/contexts.db` |
| Context ID system | ✅ Implemented | `ctx_<12hex>` format |
| Agent binding | ✅ Implemented | `context_assignments` junction table |
| Context CLI | ✅ Implemented | 7 commands |
| Context Schema (SPEC-0008) | ✅ Frozen v1.0 | This document |
| Context Versioning | ⏳ Phase 2+ | Schema defined, not auto-incremented yet |
| Context Inheritance | ⏳ Phase 2+ | `parent_context_id` column exists |
| Context Auto-Injection | ⏳ Phase 2+ | Protocol defined, not implemented |
| Context Sharing (team-level) | ⏳ Phase 2+ | Team model exists, sharing rules not |
| Runtime adapter translation | ⏳ Phase 2+ | Adapters exist, Context serialization not |
| Context + Experience loop | ⏳ Phase 2+ | Both stores exist, auto-linking not |

---

## 8. Relationship to Other Specs

| Spec | Relationship |
|------|-------------|
| SPEC-0001 (Capability Manifest) | Context defines *what* to do; Manifest defines *how* to do it |
| SPEC-0003 (Event Schema) | Execution records carry `context_id` |
| SPEC-0007 (Infrastructure Standard) | Context ID is part of the unified ID hierarchy |
| SPEC-0004 (Security Model) | Context governs which policies apply to Agents within it |

---

## 9. Freeze Declaration

The Context Contract is **FROZEN v1.0** as a specification. This means:

- The **data model** (fields, types, relationships) is stable — no breaking changes without a major version bump.
- The **ID format** (`ctx_<12hex>`) is stable.
- The **CLI interface** is stable.
- **Phase 2+ features** (auto-injection, versioning, sharing) are documented but not yet required for compatibility.

Any implementation that reads and writes the canonical Context format defined in Section 3 is compliant with SPEC-0008.
