# SPEC-0000: Core Concepts & Object Model

**Version:** 1.0
**Status:** Proposed
**Type:** Foundation Specification
**Supersedes:** Nothing

---

## 1. Purpose

This specification defines the **Agent OS Object Model** — the universal language used across all RFCs, implementations, and ecosystem contributions. Every term defined here is authoritative. All subsequent documents must reference this specification rather than redefining terms.

---

## 2. Object Classification

Every object in Agent OS belongs to exactly one of four classifications:

| Classification | Description | Lifetime | Examples |
|---------------|-------------|----------|----------|
| **Definition Object** | Metadata that defines behavior, flow, or constraints. Immutable once published. | Until explicitly versioned out | Workflow, Rule, Capability Manifest, Profile |
| **Runtime Object** | Exists during execution. Created, mutated, and destroyed by the Execution Engine. | Duration of execution | Task, Event, Execution |
| **Persistent Object** | Durable data that accumulates over time. Read and written by the Data Plane. | Indefinite (subject to retention policy) | Knowledge, Memory, Experience, Execution Record |
| **Infrastructure Object** | System-level components enabling communication, discovery, and coordination. | System lifetime | Event Bus, Registry |

---

## 3. Entity Definitions

### 3.1 Goal

| Property | Value |
|----------|-------|
| Definition | A user's declarative description of a desired end state, containing no process details |
| Classification | Definition Object (transient — produced by User Plane, consumed by Kernel) |
| Identity | `goal://<session_id>/<sequence>` |
| State | Created → Resolved |
| Owner | User Plane |
| Lifecycle | Created when user submits → Resolved when Intent Engine produces Intent |

**Serialization:**
```json
{
  "goal_id": "goal://session_abc/001",
  "text": "research Nvidia stock for investment recommendation",
  "constraints": {
    "max_cost": 1.0,
    "max_duration": "300s",
    "language": "en"
  },
  "session_id": "session_abc",
  "created_at": "2026-07-19T10:00:00Z"
}
```

---

### 3.2 Intent

| Property | Value |
|----------|-------|
| Definition | The Kernel's structured interpretation of a Goal, including detected domain, task type, and output requirements |
| Classification | Definition Object (transient — produced by Intent Engine, consumed by Workflow Resolver and Planner) |
| Identity | `intent://<execution_id>/<sequence>` |
| State | Created → Resolved |
| Owner | Control Plane (Intent Engine) |
| Lifecycle | Created when Goal is resolved → Consumed when Planner produces Execution Plan |

**Serialization:**
```json
{
  "intent_id": "intent://exec_001/001",
  "goal_id": "goal://session_abc/001",
  "domain": "finance",
  "task_type": "stock_research",
  "priority": "high",
  "output_format": "investment_report",
  "confidence": 0.92,
  "parameters": {
    "company": "NVIDIA",
    "ticker": "NVDA",
    "depth": "deep"
  }
}
```

---

### 3.3 Workflow

| Property | Value |
|----------|-------|
| Definition | A declarative Graph describing Task dependencies and execution order. Contains no domain constraints |
| Classification | Definition Object |
| Identity | `wf://<namespace>/<name>@<version>` |
| State | Draft → Published → Deprecated |
| Owner | Metadata Plane (Registry) |
| Lifecycle | Authored → Versioned → Published → Discovered → Deprecated |

**Serialization:**
```json
{
  "workflow_id": "wf://finance/stock-research",
  "version": "2.1.0",
  "description": "Standard stock research workflow",
  "stages": [
    {
      "id": "news_analysis",
      "type": "task_node",
      "depends_on": [],
      "condition": "input.has_company == true",
      "requirements": {
        "capability_type": "research",
        "domain": ["finance", "news"],
        "language": "en"
      }
    },
    {
      "id": "financial_analysis",
      "type": "task_node",
      "depends_on": ["news_analysis"],
      "condition": "user_intent.depth in ['financial', 'deep']",
      "requirements": {
        "capability_type": "research",
        "domain": ["finance", "sec_filing"],
        "language": "en"
      }
    }
  ],
  "output_schema": { "$ref": "schemas/execution/report.json" }
}
```

---

### 3.4 Task

| Property | Value |
|----------|-------|
| Definition | The smallest schedulable execution unit in Agent OS. **The only object the Execution Engine schedules** |
| Classification | Runtime Object |
| Identity | `task://<execution_id>/<sequence>` |
| State | Created → Queued → Assigned → Running → WaitingReview → Reviewed → Completed / Failed / Cancelled |
| Owner | Control Plane (Execution Engine) |
| Lifecycle | Created by Planner in Execution Plan → Scheduled by Execution Engine → Executed by Capability → Reviewed → Completed |

**State Machine:**
```
[Created] → [Queued] → [Assigned] → [Running] → [WaitingReview] → [Reviewed]
                                                          │              │
                                                          │         ┌────┴────┐
                                                          │         │         │
                                                     [Completed]  [Failed]  [ReplanRequest]
                                                          │         │         │
                                                          │         ├── [Retry] → [Running]
                                                          │         └── [Skip] → [Skipped]
                                                          │                   │
                                                     [Archived]     [Cancelled]
```

**Serialization:**
```json
{
  "task_id": "task://exec_001/003",
  "workflow_stage_id": "financial_analysis",
  "execution_id": "exec_001",
  "type": "research",
  "requirements": {
    "capability_type": "research",
    "domain": ["finance", "sec_filing"],
    "language": "en"
  },
  "input": {
    "company": "NVIDIA",
    "ticker": "NVDA",
    "depth": "full"
  },
  "context": {
    "session_id": "session_abc",
    "profile_id": "profile://finance/deep"
  },
  "state": "queued",
  "retry_count": 0,
  "max_retries": 3,
  "created_at": "2026-07-19T10:00:05Z"
}
```

---

### 3.5 Rule

| Property | Value |
|----------|-------|
| Definition | A Constraint that limits Task behavior, input, or output. Contains no flow information |
| Classification | Definition Object |
| Identity | `rule://<namespace>/<name>@<version>` |
| State | Draft → Review → Experiment → Approved → Superseded |
| Owner | Rule Governance |
| Lifecycle | Authored → Reviewed → (Optional: Experiment) → Approved → Active → Superseded |

**Serialization:**
```json
{
  "rule_id": "rule://finance/sec-filing",
  "version": "1.2.0",
  "description": "Financial research must use SEC filings as primary source",
  "scope": {
    "workflows": ["wf://finance/*"],
    "task_types": ["research"],
    "domain": ["finance", "sec_filing"]
  },
  "constraints": [
    {
      "field": "output.sources",
      "condition": "contains_source_type('sec') == true",
      "severity": "required"
    },
    {
      "field": "output.sources.sec",
      "condition": "count >= 1 && within_quarters(4)",
      "severity": "required"
    }
  ],
  "governance": {
    "status": "approved",
    "approved_by": "human:chief-analyst",
    "approved_at": "2026-06-01T00:00:00Z"
  }
}
```

---

### 3.6 Profile

| Property | Value |
|----------|-------|
| Definition | A cross-cutting configuration that controls Capability behavior, model preferences, and Rule overrides for one execution |
| Classification | Definition Object |
| Identity | `profile://<namespace>/<name>@<version>` |
| State | Draft → Published → Deprecated |
| Owner | Metadata Plane (Registry) |
| Lifecycle | Authored → Published → Referenced by Execution Engine |

**Serialization:**
```json
{
  "profile_id": "profile://finance/deep",
  "version": "1.0.0",
  "capability_configs": {
    "research": {
      "preferred_models": ["claude-sonnet-4", "gpt-4o"],
      "depth": "deep",
      "citation_required": true,
      "source_priority": ["sec", "reuters", "bloomberg"]
    }
  },
  "rule_overrides": [],
  "cost_budget": { "max_per_execution": 2.0, "max_per_task": 0.5 },
  "quality_threshold": 0.9
}
```

---

### 3.7 Capability Manifest

| Property | Value |
|----------|-------|
| Definition | A Capability's published declaration used by the Registry for discovery and Capability Negotiation |
| Classification | Definition Object |
| Identity | `cap://<namespace>/<name>@<version>` |
| State | Registered → Active → Deprecated |
| Owner | Metadata Plane (Registry) |
| Lifecycle | Published by Capability author → Registered in Registry → Discovered and invoked |

**Serialization:**
```json
{
  "capability_id": "cap://nous-research/research-v2",
  "version": "2.3.0",
  "provider": "nous-research",
  "type": "research",
  "supported_domains": ["finance", "technology", "science", "general"],
  "supported_languages": ["en", "zh", "ja"],
  "interfaces": {
    "execute": {
      "input_schema": { "$ref": "schemas/capability/research-input.json" },
      "output_schema": { "$ref": "schemas/capability/research-output.json" }
    }
  },
  "performance": {
    "quality_score": 0.94,
    "avg_latency_ms": 2500,
    "cost_per_call": 0.02,
    "cost_per_token": 0.000003
  },
  "requirements": {
    "models": ["claude-sonnet-4", "gpt-4o"],
    "tools": ["browser", "search"],
    "memory_types": ["knowledge", "cache"]
  }
}
```

---

### 3.8 Capability Requirement

| Property | Value |
|----------|-------|
| Definition | A declarative specification of what a Task needs from a Capability. Not bound to a specific implementation |
| Classification | Definition Object (transient — embedded in Workflow stages or Task definitions) |
| Identity | N/A (embedded, not independently addressable) |
| State | N/A |
| Owner | Workflow / Planner |
| Lifecycle | Authored as part of Workflow → Resolved via Capability Negotiation |

**Serialization:**
```json
{
  "capability_type": "research",
  "domain": ["finance", "sec_filing"],
  "language": "en",
  "quality_min": 0.85,
  "cost_max": 0.5,
  "latency_max_ms": 5000,
  "required_features": ["citation", "source_attribution"]
}
```

---

### 3.9 Event

| Property | Value |
|----------|-------|
| Definition | An immutable record of a state change in the system. The sole mechanism for cross-module communication |
| Classification | Runtime Object (transient on Bus, persistent in Store) |
| Identity | `event://<event_store>/<uuid>` |
| State | Published → Delivered → (Optionally) Replayed |
| Owner | Event Store (persisted) |
| Lifecycle | Published by any module → Delivered to subscribers → Stored in Event Store → (Optionally) Replayed |

**Serialization:**
```json
{
  "event_id": "event://store-001/a1b2c3d4-...",
  "event_type": "Task:Completed",
  "version": 1,
  "source": {
    "module": "execution-engine",
    "instance_id": "ee-001"
  },
  "payload": {
    "task_id": "task://exec_001/003",
    "status": "completed",
    "result_summary": "SEC filings found for NVIDIA 2025-Q1 through 2025-Q4"
  },
  "context": {
    "execution_id": "exec_001",
    "session_id": "session_abc"
  },
  "timestamp": "2026-07-19T10:00:30.123Z"
}
```

---

### 3.10 Execution

| Property | Value |
|----------|-------|
| Definition | A single run of an Execution Plan from start to terminal state |
| Classification | Runtime Object |
| Identity | `exec://<namespace>/<uuid>` |
| State | Created → Running → Reviewing → Completed / Failed / Cancelled |
| Owner | Control Plane (Execution Engine) |
| Lifecycle | Created when Execution Plan is instantiated → Runs through Tasks → Terminates |

**Serialization:**
```json
{
  "execution_id": "exec://finance/550e8400-...",
  "plan_hash": "sha256:abc123...",
  "workflow": { "id": "wf://finance/stock-research", "version": "2.1.0" },
  "rules_applied": [
    { "id": "rule://finance/sec-filing", "version": "1.2.0" }
  ],
  "profile": { "id": "profile://finance/deep", "version": "1.0.0" },
  "state": "running",
  "task_count": 4,
  "tasks_completed": 2,
  "tasks_failed": 0,
  "started_at": "2026-07-19T10:00:00Z"
}
```

---

### 3.11 Execution Record

| Property | Value |
|----------|-------|
| Definition | An auditable, replayable snapshot of one complete execution, pinning all versions and inputs |
| Classification | Persistent Object |
| Identity | `record://<execution_id>` |
| State | Created → Archived |
| Owner | Data Plane (Event Store) |
| Lifecycle | Created when Execution completes → Stored permanently (subject to retention) → Used for replay and analysis |

**Serialization:**
```json
{
  "execution_id": "exec://finance/550e8400-...",
  "record_id": "record://finance/550e8400-e29b-41d4-a716-446655440000",
  "execution_ref": "exec://finance/550e8400-e29b-41d4-a716-446655440000",
  "goal_hash": "sha256:...",
  "workflow": { "id": "wf://finance/stock-research", "version": "2.1.0" },
  "rules": [
    { "id": "rule://finance/sec-filing", "version": "1.2.0" },
    { "id": "rule://finance/risk-check", "version": "3.0.1" }
  ],
  "capability_invocations": [
    {
      "capability_id": "cap://nous-research/research-v2",
      "version": "2.3.0",
      "model": "claude-sonnet-4",
      "task_id": "task://exec_001/001",
      "input_hash": "sha256:...",
      "output_ref": "event://store-001/event_045",
      "cost": { "tokens": 45000, "api_calls": 12, "usd": 0.18 },
      "latency_ms": 3200,
      "review_result": { "passed": true, "score": 0.92 }
    }
  ],
  "result": { "status": "completed", "summary": "..." },
  "total_cost_usd": 0.42,
  "total_latency_ms": 18500,
  "completed_at": "2026-07-19T10:01:18Z"
}
```

---

### 3.12 Knowledge

| Property | Value |
|----------|-------|
| Definition | World knowledge — documents, data, and facts that are shared across all executions. Read-only to AI, write-governed by humans |
| Classification | Persistent Object |
| Identity | `knowledge://<store>/<uuid>` |
| State | Ingested → Indexed → Available → (Optionally) Superseded |
| Owner | Data Plane (Memory Manager) |
| Lifecycle | Ingested → Indexed → Queried → Updated via governance |

---

### 3.13 Memory

| Property | Value |
|----------|-------|
| Definition | Running experience — private to an execution or session. Read-write, auto-accumulated, auto-expired |
| Classification | Persistent Object |
| Identity | `memory://<session_id>/<key>` |
| State | Created → Accessed → (Optionally) Archived |
| Owner | Data Plane (Memory Manager) |
| Lifecycle | Written during execution → Retrieved when context matches → Expired |

---

### 3.14 Experience

| Property | Value |
|----------|-------|
| Definition | Cross-session reusable patterns learned by the Loop subsystem. Used for optimization suggestions |
| Classification | Persistent Object |
| Identity | `exp://<loop_engine>/<uuid>` |
| State | Discovered → Validated → Suggested → (Optionally) Incorporated |
| Owner | Loop Manager (Learning Engine) |
| Lifecycle | Discovered by Learning Engine → Validated by Evaluation Engine → Suggested via Rule Suggestion → (Optionally) Approved by Human → Incorporated |

### 3.15 Session

| Property | Value |
|----------|-------|
| Definition | A user interaction context that groups one or related Goals and Executions. Provides resource isolation, Memory scoping, and continuity across multi-turn interactions |
| Classification | Runtime Object |
| Identity | `session://<namespace>/<uuid>` |
| State | Created → Active → Expired |
| Owner | Control Plane |
| Lifecycle | Created when user starts interaction → Active while Goals are being resolved → Expired after idle timeout or explicit close |

**Serialization:**
```json
{
  "session_id": "session://finance/550e8400-...",
  "user_id": "user://haihao",
  "state": "active",
  "created_at": "2026-07-19T10:00:00Z",
  "last_active_at": "2026-07-19T10:15:00Z",
  "execution_ids": ["exec://finance/..."],
  "memory_scope": "session",
  "idle_timeout_seconds": 900
}
```

### 3.16 Execution Plan

| Property | Value |
|----------|-------|
| Definition | The compiled output of the Planner — a frozen, executable DAG derived from a Workflow + Rules + Profile. Contains the minimally-viable set of stages, each bound to a specific Capability |
| Classification | Definition Object (transient — produced by Planner, consumed by Execution Engine) |
| Identity | `plan://<namespace>/<uuid>` |
| State | Created → Activated → (Optionally) Superseded |
| Owner | Control Plane (Planner) |
| Lifecycle | Created by Planner compilation → Activated by Execution Engine → Superseded on Replan |

**Serialization:**
```json
{
  "plan_id": "plan://finance/550e8400-...",
  "workflow_ref": "wf://finance/stock-research@2.1.0",
  "execution_id": "exec://finance/...",
  "compiled_at": "2026-07-19T10:00:02Z",
  "stages": [
    {
      "stage_id": "company_identification",
      "type": "task_node",
      "depends_on": [],
      "capability_binding": {
        "capability_id": "cap://nous-research/research-v2@2.3.0",
        "model": "claude-sonnet-4"
      }
    }
  ],
  "pruned_stages": ["financial_analysis", "valuation_analysis"],
  "rules_applied": ["rule://finance/sec-filing@1.2.0"],
  "profile_ref": "profile://finance/deep@1.0.0"
}
```

---

## 4. Relationship Graph

```
                            ┌─────────────┐
                            │    Goal     │
                            └──────┬──────┘
                                   │ resolves to
                                   ▼
                            ┌─────────────┐
                            │   Intent    │
                            └──────┬──────┘
                                   │ selects
                                   ▼
                   ┌──────────────────────────────┐
                   │          Workflow             │
                   │  (contains Stage[ ] nodes)    │
                   └──────┬───────────────────────┘
                          │ compiled by
                          ▼
                   ┌──────────────────────────────┐
                   │      Execution Plan           │
                   │  (Workflow + Rules + Profile  │
                   │   → compiled Execution Graph) │
                   └──────┬───────────────────────┘
                          │ instantiated by
                          ▼
                   ┌──────────────────────────────┐
                   │         Execution             │
                   │  (contains Task[ ] instances) │
                   └──────┬───────────────────────┘
                          │ each Task requires
                          ▼
              ┌──────────────────────────┐
              │ Capability Requirement   │
              └──────────┬───────────────┘
                         │ resolved via
                         ▼
              ┌──────────────────────────┐
              │ Capability Manifest      │
              │ (found in Registry)      │
              └──────────────────────────┘

  Each Task state change ──── publishes ────► Event
                                                  │
                                                  ▼
                                          ┌──────────────┐
                                          │  Event Store  │────────► Execution Record
                                          └──────────────┘

  Workflow ── referenced by ──► Rule (constrains Task behavior)
  Execution ── uses ──► Profile (configures Capability behavior)
  Execution ── produces ──► Experience (learned by Loop)
  Knowledge ──► Capability (consumed as input)
  Memory ──► Capability (consumed as context)
```

---

## 5. Identity Convention

All Agent OS object identities follow a URI-like convention:

```
<scheme>://<namespace>/<path>@<version>
```

| Object | Scheme | Namespace | Path | Version |
|--------|--------|-----------|------|---------|
| Session | `session` | Namespace | UUID | — |
| Execution Plan | `plan` | Namespace | UUID | — |
| Workflow | `wf` | Domain/org | Name | Semver |
| Rule | `rule` | Domain/org | Name | Semver |
| Profile | `profile` | Domain/org | Name | Semver |
| Capability Manifest | `cap` | Provider | Name | Semver |
| Task | `task` | Execution ID | Sequence | — |
| Event | `event` | Store ID | UUID | — |
| Execution | `exec` | Namespace | UUID | — |
| Execution Record | `record` | Namespace | UUID | — |
| Knowledge | `knowledge` | Store ID | UUID | — |
| Memory | `memory` | Session ID | Key | — |
| Experience | `exp` | Loop Engine | UUID | — |

**Rules:**
- All IDs are case-sensitive
- Namespaces are lowercase with hyphens
- Versions follow Semantic Versioning (MAJOR.MINOR.PATCH)
- Runtime Object IDs do not carry versions (versions are captured in Execution Record)

---

## 6. Ownership Matrix

| Object | Classifies As | Owner Plane | Owner Module |
|--------|---------------|-------------|--------------|
| Goal | Definition (transient) | User Plane | — |
| Intent | Definition (transient) | Control Plane | Intent Engine |
| Session | Runtime | Control Plane | Execution Engine |
| Execution Plan | Definition (transient) | Control Plane | Planner |
| Workflow | Definition | Metadata Plane | Registry |
| Task | Runtime | Control Plane | Execution Engine |
| Rule | Definition | Metadata Plane | Rule Governance |
| Profile | Definition | Metadata Plane | Registry |
| Capability Manifest | Definition | Metadata Plane | Registry |
| Event | Runtime | Infrastructure | Event Bus / Store |
| Execution | Runtime | Control Plane | Execution Engine |
| Execution Record | Persistent | Data Plane | Event Store |
| Knowledge | Persistent | Data Plane | Memory Manager |
| Memory | Persistent | Data Plane | Memory Manager |
| Experience | Persistent | Data Plane | Loop Manager |

---

## 7. State Models Summary

| Object | Has State? | State Machine |
|--------|-----------|---------------|
| Goal | Transient | Created → Resolved |
| Intent | Transient | Created → Resolved |
| Session | Yes | Created → Active → Expired |
| Execution Plan | Transient | Created → Activated → Superseded |
| Workflow | Yes | Draft → Published → Deprecated |
| Task | Yes | Created → Queued → Assigned → Running → WaitingReview → Reviewed → Completed / CompletedWithWarning / Partial / Failed / Cancelled → Archived |
| Rule | Yes | Draft → Review → Experiment → Approved → Superseded |
| Profile | Yes | Draft → Published → Deprecated |
| Capability Manifest | Yes | Registered → Active → Deprecated |
| Event | Immutable | Published → (Stored) → (Replayed) |
| Execution | Yes | Created → Running → Reviewing → Completed / Failed / Cancelled |
| Execution Record | Append-only | Created → Archived |
| Knowledge | Yes | Ingested → Indexed → Available → Superseded |
| Memory | Yes | Created → Accessed → Archived |
| Experience | Yes | Discovered → Validated → Suggested → Incorporated |

---

## 8. Serialization Conventions

### 8.1 JSON

- All serialized objects use JSON (RFC 8259) as the canonical format
- Timestamps: ISO 8601 with UTC (suffix `Z`)
- IDs: strings following the Identity Convention (§5)
- Hashes: `sha256:<hex>` format
- Version fields: semantic versioning strings (`MAJOR.MINOR.PATCH`)
- Monetary amounts: USD as number (float)

### 8.2 Event

- Events are serialized as JSON and published to the Event Bus
- Event Store stores events as append-only JSON records
- Event type names follow PascalCase with colon separator for hierarchy: `Task:Completed`, `Execution:Failed`

### 8.3 Storage

- Long-term storage: Data Plane modules may use any backend (SQL, NoSQL, object storage)
- Cross-module exchange always uses the JSON representations defined in this SPEC
- Schema validation files live in `/schemas/` at the repository root

---

## 9. Reserved & Deprecated Terms

The following terms are **not used** in Agent OS to avoid confusion:

| Term | Reason | Replacement |
|------|--------|-------------|
| Agent | Overloaded; implies autonomous decision-making outside governance | Task, Capability, or Application |
| Prompt | User-level concept; Kernel never handles prompts | Goal, Intent |
| Plugin | Too generic; implies no contract | Capability (with Manifest) |
| Skill | Ambiguous (could mean Workflow, Capability, or Rule) | Use specific term |
| Tool | Reserved for low-level execution (browser, Python, terminal) | — |

---

## 10. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-07-19 | Initial specification |
| 1.1 | 2026-07-20 | Added §11 Error Code Directory — 6 namespaces, 37 codes |

## 11. Error Code Directory

Every error in Agent OS carries a structured error code from one of six namespaces. Codes are **stable** — once assigned, a code is never repurposed or removed (deprecated codes are retired in the registry but remain reserved).

### 11.1 Error Envelope

```json
{
  "code": "PLAN_ERR_004",
  "severity": "fatal",
  "message": "No capability matches requirements for stage '{stage_id}'",
  "detail": "type=research, domain=[finance, sec_filing], quality_min=0.85",
  "suggested_action": "Lower quality_min, remove sec_filing domain, or register a matching capability",
  "source": { "module": "planner", "stage_id": "financial_analysis" }
}
```

### 11.2 WF_ERR — Workflow Validation

| Code | Severity | Message | Suggested Action |
|------|----------|---------|-----------------|
| WF_ERR_001 | fatal | Workflow '{workflow_id}' has a cyclic dependency at stage '{stage_id}' | Break the cycle in depends_on |
| WF_ERR_002 | fatal | Workflow '{workflow_id}' references unknown stage '{stage_id}' in depends_on | Add the missing stage definition or fix the reference |
| WF_ERR_003 | fatal | Stage '{stage_id}' has no root ancestor (unreachable) | Ensure the stage is reachable from at least one root stage |
| WF_ERR_004 | error | Stage '{stage_id}' has no capability_type in requirements | Add capability_type field |
| WF_ERR_005 | warning | Stage '{stage_id}' condition expression '{expr}' failed to parse | Valid operators: ==, !=, in, not in, >, <, >=, <=, contains, starts_with |
| WF_ERR_006 | warning | Stage '{stage_id}' condition '{expr}' references unknown variable '{var}' | Available: user_intent.*, input.* |

### 11.3 MAN_ERR — Manifest Registration

| Code | Severity | Message | Suggested Action |
|------|----------|---------|-----------------|
| MAN_ERR_001 | fatal | Manifest '{manifest_id}@{version}' is already registered | Bump the version or use a different manifest_id |
| MAN_ERR_002 | fatal | Manifest '{manifest_id}' input_schema is invalid JSON Schema | Validate against draft 2020-12 |
| MAN_ERR_003 | fatal | Manifest '{manifest_id}' output_schema is invalid JSON Schema | Validate against draft 2020-12 |
| MAN_ERR_004 | error | Manifest '{manifest_id}' does not declare required error codes {missing} | At minimum declare: timeout, invalid_input, internal_error |
| MAN_ERR_005 | warning | Manifest '{manifest_id}' quality_score {actual} exceeds 1.0 or is below 0.0 | Set quality_score in [0.0, 1.0] |
| MAN_ERR_006 | warning | Manifest '{manifest_id}' references unknown model '{model}' in required_environment.models | Register the model first or fix the model ID |

### 11.4 PLAN_ERR — Planner Compilation

| Code | Severity | Message | Suggested Action |
|------|----------|---------|-----------------|
| PLAN_ERR_001 | fatal | Workflow YAML parsing failed at line {line}: {detail} | Fix the YAML syntax error |
| PLAN_ERR_002 | fatal | Workflow '{workflow_id}' has no stages with empty depends_on | At least one root stage is required |
| PLAN_ERR_003 | fatal | No Workflow found for ref '{workflow_ref}' | Check workflow_id spelling or register the workflow |
| PLAN_ERR_004 | fatal | No capability matches requirements for stage '{stage_id}' | Lower quality_min, broaden domain, or register a matching capability |
| PLAN_ERR_005 | error | Capability Negotiation failed: no Registry response after {timeout}ms | Check Registry availability |
| PLAN_ERR_006 | error | Profile '{profile_ref}' not found | Register the profile or fix the reference |
| PLAN_ERR_007 | warning | Budget warning: estimated cost {estimated} exceeds Profile cap {limit}' | Reduce stage count, lower quality_min, or raise budget |

### 11.5 CAP_ERR — Capability Invocation

| Code | Severity | Retryable | Message | Suggested Action |
|------|----------|-----------|---------|-----------------|
| CAP_ERR_001 | error | yes | Capability '{cap_id}' timed out after {timeout}ms | Retry with backoff; increase deadline if persistent |
| CAP_ERR_002 | error | yes | Rate limit exceeded for capability '{cap_id}'; retry after {retry_after_ms}ms | Wait before retrying |
| CAP_ERR_003 | error | yes | Capability '{cap_id}' returned transient error: {detail} | Retry with exponential backoff |
| CAP_ERR_004 | error | yes | Model '{model}' unavailable for capability '{cap_id}' | Retry; may trigger Capability Negotiation rebind |
| CAP_ERR_005 | fatal | no | Invalid input for capability '{cap_id}': {detail}' | Fix the Workflow's input_template or stage requirements |
| CAP_ERR_006 | fatal | no | Authentication failed for capability '{cap_id}' | Check API keys in Security Manager configuration |
| CAP_ERR_007 | fatal | no | Capability '{cap_id}' does not support required feature '{feature}' | Use a different capability or remove the feature requirement |
| CAP_ERR_008 | error | no | Invocation cancelled: {reason} | Normal cancellation path; no action needed |

### 11.6 POOL_ERR — Pool Scheduling

| Code | Severity | Message | Suggested Action |
|------|----------|---------|-----------------|
| POOL_ERR_001 | error | Capability '{cap_id}' queue is full (limit: {limit}) | Retry after {retry_after_ms}ms; consider a different capability |
| POOL_ERR_002 | warning | All instances of capability '{cap_id}' are unhealthy | Check instance health; may trigger automatic replacement |
| POOL_ERR_003 | error | Rate limit exceeded for capability '{cap_id}' at pool level | Reduce dispatch rate or increase pool capacity |
| POOL_ERR_004 | warning | Instance '{instance_id}' heartbeat missed ({missed_count} consecutive) | Instance may be unhealthy; replacement in progress |

### 11.7 SYS_ERR — System-Level

| Code | Severity | Message | Suggested Action |
|------|----------|---------|-----------------|
| SYS_ERR_001 | fatal | Event Store connection failed: {detail} | Check Event Store availability |
| SYS_ERR_002 | fatal | Event type '{event_type}' version {version} is not registered in Schema Registry | Register the event type before publishing |
| SYS_ERR_003 | error | Event '{event_id}' failed schema validation: {detail} | Fix the event payload to match the registered schema |
| SYS_ERR_004 | fatal | Event signature verification failed for event '{event_id}' | Possible tampering; investigate immediately |
| SYS_ERR_005 | error | Registry object '{object_id}' not found | Check object_id spelling and status (may be deprecated) |
| SYS_ERR_006 | error | Authorization denied: principal '{principal}' may not perform '{action}' on '{resource}' | Check security policy configuration |
| SYS_ERR_007 | warning | Key '{key_id}' expires in {days} days | Rotate key before expiry |

### 11.8 Code Assignment Rules

1. **Codes are permanent.** Once assigned, a code is never deleted. If a code becomes obsolete, it is marked `retired` in the registry but remains reserved.
2. **New codes are assigned sequentially** within their namespace. Do not reuse retired codes.
3. **Every module publishes the error codes it may emit** in its defining RFC. Consumers use this list for error handling.
4. **Severity levels:** `fatal` (execution cannot proceed), `error` (execution fails but system continues), `warning` (execution continues with degraded state).
5. **Capability authors** must use CAP_ERR codes from §11.5. Custom codes not in this table are mapped to `CAP_ERR_003` (transient) or `CAP_ERR_007` (unsupported) at the Pool boundary.
