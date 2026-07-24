# SPEC-0007: Infrastructure Standardization

> **Status:** Frozen v1.0
> **Scope:** Unified ID hierarchy, Event-as-Universal-State-Change principle, Context Protocol, Evidence interface, Storage abstraction, Replay readiness
> **Editor:** Intent OS Project
> **Last updated:** 2026-07-23

> **Implementation Note:** This spec is frozen. The reference-runtime code (v0.4.3, 731 tests) is the canonical implementation for all interfaces marked FROZEN. Any discrepancy between this document and the running code is a spec bug.

---

## 1. Purpose

This specification defines the **infrastructure standards** that underpin every layer of Intent OS. It answers the following questions:

1. **Identity** -- What is the universal hierarchy of identifiers, and what are their exact formats?
2. **Change** -- What principle governs how all state changes are recorded?
3. **Context** -- What is the formal protocol for sharing execution context across Agents?
4. **Evidence** -- What is the exact interface for verifiable claims, and how do they chain together?
5. **Storage** -- What is the base interface pattern that every store must implement?
6. **Replay** -- What makes an ExecutionRecord deterministic and replayable?

These standards are binding on all layers defined in the Blueprint and all Specs that reference them.

---

## 2. Unified ID Hierarchy

### 2.1 Principle

Every entity in Intent OS has a single, globally-unique, prefixed identifier. The prefix encodes the entity type, making IDs self-describing. IDs are **assigned at creation time** and **never reassigned**.

### 2.2 Hierarchy

```
Org ───────────────────── org_{uuid_hex[0:8]}
  │
  └── Team ────────────── team_{uuid_hex[0:8]}
        │
        └── Agent ─────── agent_{uuid_hex[0:8]}
              │
              └── Context ─ ctx_{uuid_hex[0:12]}
                    │
                    └── Execution ── exec_{uuid_hex[0:8]}  (alias: trace_id)
                          │
                          ├── Event ── UUID v4 (event_id)
                          │
                          └── Evidence ── evi_{uuid_hex[0:8]}
```

**Cardinality rules:**

- One Org contains many Teams.
- One Team contains many Agents.
- One Agent may be assigned to many Contexts (M:N via `context_assignments`).
- One Context hosts many Executions.
- One Execution contains many Events (appended in sequence order).
- One Execution may produce many Evidence records.
- Evidence records may reference parent Evidence records, forming a **directed acyclic graph (DAG)**.

### 2.3 Exact ID Formats

| Entity | Prefix | Format | Example | Status |
|--------|--------|--------|---------|--------|
| **Org** | `org_` | `org_{8 hex}` | `org_a82f91c3` | **Phase 2+** (not yet implemented) |
| **Team** | `team_` | `team_{8 hex}` | `team_a82f91c3` | **Implemented** (v0.4.3) |
| **Agent** | `agent_` | `agent_{8 hex}` | `agent_8f92a1c3` | **Implemented** (v0.4.3) |
| **Context** | `ctx_` | `ctx_{12 hex}` | `ctx_a82f91c3d4e5` | **Implemented** (v0.4.3) |
| **Execution** | (no fixed prefix in code; `trace_id` in model) | UUID v4 (36-char) or `proxy-{12 hex}` | `550e8400-e29b-41d4-a716-446655440000` / `proxy-a82f91c3d4e5` | **Implemented** (v0.4.3) |
| **Event** | (no prefix; `event_id` field) | UUID v4 (36-char) | `550e8400-e29b-41d4-a716-446655440000` | **Implemented** (v0.4.3) |
| **Evidence** | `evi_` | `evi_{8 hex}` | `evi_a82f91c3` | **Implemented** (v0.4.3) |
| **Capability** | (no prefix; composite) | `{name}@{version}` | `web_search@1.0.0` | **Implemented** (v0.4.3) |
| **Policy** | `policy_` | `policy_{8 hex}` | `policy_a82f91c3` | **Implemented** (v0.4.3) |

### 2.4 ID Assignment Rules

1. **Agents** generate IDs as `f"agent_{uuid.uuid4().hex[:8]}"` -- the random component is 8 hex characters (32 bits of entropy). This is assigned in `AgentStore.create()`.

2. **Teams** generate IDs as `f"team_{uuid.uuid4().hex[:8]}"` -- assigned in `AgentStore.create_team()`.

3. **Contexts** generate IDs as `f"ctx_{uuid.uuid4().hex[:12]}"` -- assigned in `ContextStore.create()`. Contexts use 12 hex characters (48 bits of entropy) to reduce collision probability in multi-tenant scenarios where contexts may outnumber agents by an order of magnitude.

4. **Events** generate IDs as `str(uuid.uuid4())` -- a full UUID v4. Assigned by `Event.create()` via the `event_id` field default factory on the `Event` dataclass.

5. **Executions** (trace_id) generate IDs via `str(uuid.uuid4())` for Manifest-based executions (assigned by `ExecutionRecorder.__init__`), or `f"proxy-{uuid.uuid4().hex[:12]}"` for proxy-captured sessions (assigned by `AgentTracer`). The `trace_id` is the linking key that binds all Events within one execution.

6. **Evidence** records generate IDs as `f"evi_{uuid.uuid4().hex[:8]}"` -- assigned in `commands/evidence.py` at creation time.

7. **Orgs** (Phase 2+) will generate IDs as `f"org_{uuid.uuid4().hex[:8]}"`. The `org_id` column does not yet exist on the `agents` or `teams` tables. When implemented, an Org will be a required parent of every Team.

### 2.5 Foreign Key Relationships (Current State)

```sql
-- Agent → Team (optional)
-- agents.team_id may reference teams.team_id (no FK constraint in SQLite,
-- enforced at the application layer by AgentStore)

-- Context ←→ Agent (M:N via junction table)
CREATE TABLE context_assignments (
    context_id TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (context_id, agent_id)
);

-- Execution → Agent (optional)
-- execution_records.agent_id references agents.agent_id (no FK constraint)

-- Execution → Context (optional)
-- execution_records.context_id references execution_contexts.context_id (no FK constraint)

-- Evidence → Execution (required at application layer)
-- evidence.execution_id references execution_records.trace_id (no FK constraint in SQLite)

-- Event → Execution (via trace_id, no FK constraint)
-- events.trace_id references execution_records.trace_id (logical only)
```

**Design note:** Intent OS deliberately avoids SQLite `FOREIGN KEY` constraints in favor of application-layer validation. This keeps cross-database references (e.g., evidence in `evidence.db` referencing an execution in `events.db`) possible without attaching databases, and aligns with the project's principle that the Control Plane owns validation logic, not the Data Plane's storage engine.

---

## 3. Event-as-Universal-State-Change Principle

### 3.1 Principle Statement

> **Every state change in Intent OS is an Event. Events are not limited to execution telemetry -- they are the universal record of every create, update, delete, and transition across all six layers.**

This principle extends CONSTITUTION Article II Section 2 R3 ("Event Bus is the Single Source of Truth") from *execution state* to *all system state*. The Event Store becomes the authoritative record not only of what Agents *did*, but of what the platform *is*.

### 3.2 EventType Values for CRUD Operations

The following event types extend the existing `EventType` enum (`core/models.py`) to cover identity, context, governance, and interop lifecycle events.

#### 3.2.1 Identity Layer Events (Layer 2)

| Event Type | Status | Emitted When | Payload Keys |
|------------|--------|-------------|--------------|
| `AgentCreated` | **Phase 2+** | `AgentStore.create()` succeeds | `agent_id`, `name`, `created_by` |
| `AgentUpdated` | **Phase 2+** | `AgentStore.update_agent()` succeeds | `agent_id`, `changed_fields[]` |
| `AgentDeleted` | **Phase 2+** | `AgentStore.delete()` succeeds | `agent_id` |
| `AgentStatusChanged` | **Phase 2+** | Agent status transitions (`active` -> `paused` / `revoked`) | `agent_id`, `old_status`, `new_status` |
| `TeamCreated` | **Phase 2+** | `AgentStore.create_team()` succeeds | `team_id`, `name`, `owner` |
| `TeamUpdated` | **Phase 2+** | Team membership changes | `team_id`, `action` (`add_member` / `remove_member`), `agent_id` |
| `TeamDeleted` | **Phase 2+** | Team deletion | `team_id` |
| `CapabilityGranted` | **Phase 2+** | `AgentStore.update_agent(capabilities=[...])` adds a capability | `agent_id`, `capability` |
| `CapabilityRevoked` | **Phase 2+** | A capability is removed from an agent | `agent_id`, `capability` |

#### 3.2.2 Context Layer Events (Layer 1)

| Event Type | Status | Emitted When | Payload Keys |
|------------|--------|-------------|--------------|
| `ContextCreated` | **Phase 2+** | `ContextStore.create()` succeeds | `context_id`, `name`, `goal`, `created_by` |
| `ContextDeleted` | **Phase 2+** | `ContextStore.delete()` succeeds | `context_id` |
| `ContextAssigned` | **Phase 2+** | `ContextStore.assign_agent()` succeeds | `context_id`, `agent_id` |

#### 3.2.3 Governance Layer Events (Layer 5)

| Event Type | Status | Emitted When | Payload Keys |
|------------|--------|-------------|--------------|
| `PolicyChanged` | **Phase 2+** | A policy is created, updated, or deleted | `policy_id`, `change_type` (`created` / `updated` / `deleted`), `version` |
| `PolicyEvaluated` | **Implemented** (v0.4.3) | `SecurityManager.evaluate()` runs | `policy_id`, `task_id`, `result`, `reason` |
| `PermissionGranted` | **Defined** (Phase 2+) | Permission approved by user/policy | `permission_id`, `principal`, `resource`, `action` |
| `PermissionDenied` | **Defined** (Phase 2+) | Permission denied by user/policy | `permission_id`, `principal`, `resource`, `action`, `reason` |
| `ReviewExpired` | **Defined** (Phase 2+) | Human review window expired | `review_id`, `task_id`, `expired_at` |
| `PolicyViolation` | **Defined** (Phase 2+) | A policy was violated during execution | `policy_id`, `task_id`, `violation_detail` |

#### 3.2.4 Interoperability Layer Events (Layer 6)

| Event Type | Status | Emitted When | Payload Keys |
|------------|--------|-------------|--------------|
| `CapabilityPublished` | **Phase 2+** | `Registry.publish()` succeeds | `capability_id`, `publisher`, `visibility` |
| `CapabilityRegistered` | **Defined** (Phase 2+) | A capability is registered locally | `capability_id`, `name`, `version` |
| `RuntimeRegistered` | **Defined** (Phase 2+) | A new runtime adapter is registered | `runtime_id`, `name`, `version` |
| `CapabilityInstalled` | **Phase 2+** | `Registry.install()` succeeds | `capability_id`, `installed_by`, `target_agent` |
| `CapabilityRated` | **Phase 2+** | `Registry.rate()` is called | `capability_id`, `rating`, `rated_by` |

### 3.3 Existing Execution Events (Already Implemented)

For completeness, the execution events that **are** implemented and emit in v0.4.3:

| Event Type | Source | Module |
|------------|--------|--------|
| `TaskStarted` | `"runtime"` | `ExecutionRecorder.record_started()` |
| `CapabilityInvoked` | `"adapter"` | `ExecutionRecorder.record_invoked()` |
| `TaskCompleted` | `"runtime"` | `ExecutionRecorder.record_completed()` |
| `TaskFailed` | `"runtime"` | `ExecutionRecorder.record_failed()` |
| `TaskRetried` | `"scheduler"` | `Scheduler` |
| `TaskSkipped` | `"scheduler"` | `Scheduler` |
| `TaskCancelled` | `"scheduler"` | `Scheduler` |
| `WorkflowStarted` | `"scheduler"` | `Scheduler` |
| `WorkflowCompleted` | `"scheduler"` | `Scheduler` |
| `LlmCall` | `"proxy"` | `AgentTracer` |
| `PolicyEvaluated` | `"security"` | `SecurityManager.evaluate()` |

### 3.4 Emission Protocol

For each CRUD event type, the emitting store MUST:

1. **Write the entity first** -- persist to the store's own SQLite database.
2. **Construct the Event** -- with `event_type` from the enum, `source` set to the layer name (`"identity"`, `"context"`, `"governance"`, `"interop"`), and `payload` containing the entity's ID and the relevant delta.
3. **Write the Event** -- call `EventStore.save_event()`.

If step 3 fails, the entity write (step 1) is NOT rolled back -- the entity exists; the event emission failed. This is an acceptable trade-off in the current architecture. Future phases may introduce an outbox pattern or transactional event emission.

### 3.5 Event Source Values

The `source` field on each Event identifies which layer emitted it. The following values are reserved:

| Source | Layer | Usage |
|--------|-------|-------|
| `"runtime"` | Execution | Manifest-based capability executions (default) |
| `"adapter"` | Execution | `CapabilityInvoked` events |
| `"scheduler"` | Execution | Workflow-level events |
| `"proxy"` | Execution | Proxy-captured LLM API calls |
| `"security"` | Governance | `PolicyEvaluated` events |
| `"identity"` | Identity | **Phase 2+** Agent/Team CRUD events |
| `"context"` | Context | **Phase 2+** Context CRUD events |
| `"interop"` | Interop | **Phase 2+** Registry/Capability events |
| `"test"` | (any) | Test fixtures only |

---

## 4. Context Protocol

### 4.1 Principle

> **Context is a formal specification shared across Agents. It is not owned by any single Agent -- it is a contract that all assigned Agents agree to respect.**

Context answers: *Under what constraints, for what goal, with what scope, and with what variables is this Agent operating?*

### 4.2 Context vs. Memory

| Context | Memory |
|---------|--------|
| What the Agent is supposed to do | Who the user is |
| Project-level constraints | User preferences |
| Shared across Agents | Per-user |
| Immutable once execution begins | Can evolve |
| Stored in `contexts.db` | Future product (Phase 3+) |

### 4.3 Context Data Model (Canonical)

```python
@dataclass
class ExecutionContext:
    context_id: str              # ctx_{12 hex}
    name: str                    # Human-readable label
    goal: str = ""               # What the Agent should achieve
    constraints: list[str] = []  # Hard limits (e.g., "SEC sources only")
    task_scope: str = ""         # Domain: "research" | "trading" | "analysis"
    variables: dict = {}         # Structured data (e.g., {"tickers": ["AAPL"]})
    parent_context_id: str | None = None  # Inheritance chain
    created_by: str = ""         # Agent ID or user ID
    created_at: str = ""         # ISO 8601
    expires_at: str | None = None
```

### 4.4 Context Manifest Format (Phase 2+)

For inter-Agent portability, a Context may be serialized as a YAML Manifest. This is **not yet implemented** but defined here as the forward-compatible format:

```yaml
kind: Context
metadata:
  context_id: ctx_a82f91c3d4e5
  name: "US Stock Analysis Q2 2026"
  version: "1.0"
  created_by: agent_8f92a1c3
  created_at: "2026-07-23T10:00:00Z"
  expires_at: "2026-09-30T00:00:00Z"

spec:
  goal: "Find undervalued companies in the S&P 500 with strong free cash flow"
  task_scope: "research"

  constraints:
    - "Use only SEC EDGAR filings as primary sources"
    - "No forward-looking speculation -- only historical data"
    - "Confidence floor: 0.7 for all claims"

  variables:
    tickers:
      - AAPL
      - MSFT
      - GOOGL
    period: "Q2 2026"
    benchmark: "SPY"
    max_companies: 10

  inheritance:
    parent_context_id: null
    inherited_constraints: []
```

### 4.5 Context Sharing Protocol

1. A Context is **created** by a user or an Agent.
2. Agents are **assigned** to the Context via `ContextStore.assign_agent(context_id, agent_id)`.
3. An Execution **declares** its Context by setting `ExecutionRecord.context_id`.
4. All Agents assigned to a Context **share** the same constraints, goal, and variables.
5. When an Agent executes within a Context, the Context ID is propagated to the Execution Record and all downstream Events.

### 4.6 Context Assignment

The `context_assignments` table is the authoritative record of which Agents are bound to which Contexts:

```sql
CREATE TABLE context_assignments (
    context_id TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (context_id, agent_id)
);
```

Querying "all Contexts for an Agent" and "all Agents in a Context" is symmetric, enabled by the junction table.

---

## 5. Evidence Interface

### 5.1 Purpose

Evidence backs every Agent claim with an auditable source trail. It answers: *Why should I believe this output?*

### 5.2 Exact Field Definitions

```python
@dataclass
class Evidence:
    evidence_id: str             # evi_{8 hex} -- unique identifier
    execution_id: str            # trace_id of the Execution this backs
    claim: str                   # The Agent's claim being backed
                                 #   e.g., "Tesla's operating margin decreased to 15%"
    source_type: str = ""        # Category of source (see Section 5.3)
    source_ref: str = ""         # Human-readable pointer to the source
                                 #   e.g., "SEC 10-K filing, page 43, line 12"
    raw_data_ref: str = ""       # URI or hash pointing to raw source data
    confidence: float = 0.0      # 0.0 -- 1.0, Agent's self-assessed confidence
    verified: bool = False       # Has a human or system verified this?
    verified_by: str | None = None  # Who verified it
    verified_at: str | None = None  # ISO 8601 timestamp of verification
    created_at: str = ""         # ISO 8601 timestamp of evidence creation
```

### 5.3 Source Type Enum

The `source_type` field MUST be one of exactly four values:

| Value | Meaning | Example |
|-------|---------|---------|
| `"data"` | A direct data point retrieved from an external source | Stock price from Yahoo Finance API |
| `"calculation"` | A derived value computed from other data | Margin = (Revenue - Cost) / Revenue |
| `"model_inference"` | A conclusion reached by an AI model's reasoning | "The company is undervalued based on DCF analysis" |
| `"external_api"` | Data retrieved from an external API call | SEC EDGAR filing text |

The set of valid source types is enforced by `EvidenceStore.save_evidence()`, which raises `EvidenceStoreError` on invalid values. The frozen set `{"data", "calculation", "model_inference", "external_api"}` is defined in `core/evidence_store.py` as `_VALID_SOURCE_TYPES`.

### 5.4 Evidence Chain (DAG)

Evidence records form a **directed acyclic graph (DAG)** where:

- Nodes are `Evidence` records.
- Edges are `source_ref` pointers: when `evidence_b.source_ref == evidence_a.evidence_id`, that means Evidence B *depends on* Evidence A.
- The graph is acyclic by construction: evidence records are ordered by `created_at`, and topological sort guarantees that a dependency appears before the record that depends on it.

```
Evidence Chain Example:
                                                        
    evi_001 (source_type: "data")                      
    ┌──────────────────────────────┐                   
    │ claim: "Tesla Q2 revenue     │                   
    │        was $25.5B"           │                   
    │ source_ref: "SEC 10-Q p.32"  │                   
    └──────────────┬───────────────┘                   
                   │                                   
                   │ depends on                        
                   ▼                                   
    evi_002 (source_type: "calculation")               
    ┌──────────────────────────────┐                   
    │ claim: "Tesla gross margin   │                   
    │        is 18.2%"             │                   
    │ source_ref: "evi_001"  ◄─────┤── edge to evi_001 
    └──────────────┬───────────────┘                   
                   │                                   
                   │ depends on                        
                   ▼                                   
    evi_003 (source_type: "model_inference")           
    ┌──────────────────────────────┐                   
    │ claim: "Tesla is efficiently │                   
    │        managed"              │                   
    │ source_ref: "evi_002"  ◄─────┤── edge to evi_002 
    └──────────────────────────────┘                   
```

### 5.5 Topological Ordering

`EvidenceStore.get_evidence_chain(execution_id)` returns evidence records in topological order. The algorithm:

1. Retrieve all evidence records for the given `execution_id`.
2. Build a map of `evidence_id -> record`.
3. Perform a depth-first walk starting from each record, visiting dependencies first.
4. Return records in dependency order (dependencies before dependents).

This guarantees that an audit trail can be read from raw data through derived calculations to final conclusions.

### 5.6 SQLite Schema

```sql
CREATE TABLE evidence (
    evidence_id   TEXT PRIMARY KEY,
    execution_id  TEXT NOT NULL,
    claim         TEXT NOT NULL,
    source_type   TEXT NOT NULL DEFAULT '',
    source_ref    TEXT NOT NULL DEFAULT '',
    raw_data_ref  TEXT NOT NULL DEFAULT '',
    confidence    REAL NOT NULL DEFAULT 0.0,
    verified      INTEGER NOT NULL DEFAULT 0,    -- boolean: 0 or 1
    verified_by   TEXT,
    verified_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%Sf','now'))
);
```

---

## 6. Storage Abstraction

### 6.1 Principle

> **Every store follows the same abstract pattern. The pattern is not a formal interface class -- it is a set of conventions. Consistency, not inheritance, is the goal.**

### 6.2 The Store Interface Pattern

Every Intent OS store implements the following pattern:

```python
class XxxStore:
    """SQLite-backed store for <entity>."""

    # ── Construction ──
    def __init__(self, db_path: str | None = None) -> None:
        """Open or create the database at ``db_path`` (or default path).
        Creates parent directories if needed. Runs schema migration.
        """

    # ── Connection ──
    def _get_conn(self) -> sqlite3.Connection:
        """Return a SQLite connection with row_factory = sqlite3.Row.
        May be thread-local or new-per-operation depending on the store.
        """

    # ── Schema ──
    def _init_db(self) -> None:
        """Execute CREATE TABLE IF NOT EXISTS for all tables.
        Run schema migrations for columns added in newer versions.
        """

    # ── CRUD ──
    def create(self, ...) -> <Entity>:
        """Insert a new row and return the created entity."""

    def get(self, id: str) -> <Entity> | None:
        """Look up by primary key. Returns None if not found."""

    def list(self, ...) -> list[<Entity>]:
        """List all entities, with optional filters."""

    def delete(self, id: str) -> bool:
        """Remove by primary key. Returns True if a row was deleted."""

    # ── Domain Methods (store-specific) ──
    # Each store adds methods specific to its domain:
    #   AgentStore: create_team, add_team_member, record_execution
    #   ContextStore: assign_agent, get_contexts_for_agent
    #   EventStore: save_event, get_events_by_trace, get_capability_stats
    #   EvidenceStore: verify_evidence, get_evidence_chain
```

### 6.3 The Five Stores

| Store | Database File | Module | Layer |
|-------|--------------|--------|-------|
| `AgentStore` | `~/.intent-os/agents.db` | `core/agent_store.py` | Identity (Layer 2) |
| `ContextStore` | `~/.intent-os/contexts.db` | `core/context_store.py` | Context (Layer 1) |
| `EventStore` | `~/.intent-os/events.db` | `core/event_store.py` | Execution (Layer 3) |
| `EvidenceStore` | `~/.intent-os/evidence.db` | `core/evidence_store.py` | Verification (Layer 4) |
| `PolicyStore` | (in-memory via `core/security.py`) | `core/security.py` | Governance (Layer 5) |

### 6.4 Conventions

1. **Default paths** are in `~/.intent-os/` and are defined as module-level constants (e.g., `AGENT_STORE_DB`, `CONTEXT_DB`, `EVIDENCE_DB`). The `EventStore` default path is `intent_os_store.db` (relative to CWD), overridable via constructor.

2. **Connection strategy** varies by store:
   - `AgentStore` and `EventStore` use **thread-local connections** (one connection per thread, kept open).
   - `ContextStore` and `EvidenceStore` use **new connection per operation** (open, execute, close).
   - `EventStore` additionally uses `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` for write throughput.

3. **JSON fields** (`capabilities`, `policy_ids`, `member_ids`, `constraints`, `variables`) are stored as TEXT and serialized/deserialized with `json.dumps`/`json.loads` at the store boundary. The application layer never sees raw JSON strings.

4. **Schema migration** is handled by checking `PRAGMA table_info(...)` and issuing `ALTER TABLE ADD COLUMN` for missing columns. There is no formal migration framework -- each store handles its own additive migrations.

5. **Error types** use store-specific exception classes (`AgentStoreError`, `ContextStoreError`, `EventStoreError`, `EvidenceStoreError`). No common base exception class is shared across stores.

6. **Thread safety** varies:
   - `AgentStore` and `EventStore` use `threading.Lock` for write serialization.
   - `ContextStore` and `EvidenceStore` are not explicitly thread-safe (new connection per operation provides implicit isolation).

---

## 7. Replay Readiness

### 7.1 Principle

> **An ExecutionRecord is replayable when a different runtime, given the same Manifest, input, and Context, can reproduce a *structurally equivalent* event stream.**

Replay does not guarantee identical output (AI is probabilistic). It guarantees identical structure: same event types, same sequence, same metric dimensions.

### 7.2 Required Fields for Replay

For an `ExecutionRecord` to be replayable, the following fields MUST be present and non-empty:

| Field | Required | Purpose |
|-------|----------|---------|
| `trace_id` | Yes | Unique identifier for the replay attempt |
| `manifest_name` | Yes | Which capability to execute |
| `manifest_version` | Yes | Which version of the capability |
| `runtime_id` | Yes | Which runtime adapter to use |
| `adapter` | Yes | Which adapter class |
| `adapter_version` | Yes | Which adapter version |
| `input` | Yes | The exact input data (JSON-serializable) |
| `spec_version` | Yes | Event Schema version (always `"1.0"`) |
| `status` | Yes | The outcome of the original execution |
| `events` | Yes | The original event stream (for comparison) |
| `context_id` | Recommended | The Context under which execution occurred |

### 7.3 Replay Procedure

```
Original Execution (Runtime A)          Replay Execution (Runtime B)
─────────────────────────────           ─────────────────────────────
1. Parse Manifest                       1. Parse same Manifest
2. Prepare input                        2. Load original input
3. Assign trace_id = uuid4()            3. Assign new trace_id
4. Execute capability                   4. Execute same capability
5. Record events in sequence            5. Record events in sequence
6. Build ExecutionRecord                6. Build ExecutionRecord
7. Store in EventStore                  7. Store in EventStore
                                        8. compare_records(orig, replay)
```

### 7.4 Compatibility Verification (Four Levels)

`compare_records()` in `core/recorder.py` checks three levels (L4 is inferred):

| Level | Check | Description |
|-------|-------|-------------|
| **L1** | Schema Compatibility | Same `manifest_name@manifest_version` |
| **L2** | Event Structure Match | Same sequence of event types (order and count) |
| **L3** | Metric Dimensions Match | Same metric keys across both records (subset relation accepted) |
| **L4** | Structure Compatibility | Inferred from L1+L2+L3 passing -- both runtimes produce structurally equivalent records |

### 7.5 What Replay Does NOT Require

- Identical output values (AI is probabilistic)
- Identical latency or cost (hardware/runtime differences)
- Identical token counts (model sampling differences)
- Identical event payload values (only *structure* must match)

### 7.6 Determinism Requirements

For a capability to be replayable, its Manifest must declare all inputs that affect its behavior. Implicit inputs (environment variables, system clock, random seeds) that affect output SHOULD be declared in `spec.input` or `spec.constraints` (Phase 2+).

---

## 8. Freeze Declaration

### 8.1 FROZEN v1.0 Interfaces

The following interfaces are **frozen** as of v0.4.3. Breaking changes require a major version increment of this spec (SPEC-0007 v2.0) and a documented migration path per CONSTITUTION Article III Section 2 P2.

| Interface | Frozen Since | Canonical Source |
|-----------|-------------|------------------|
| `Event` dataclass (all fields, `to_dict()` serialization) | v0.4.3 | `core/models.py` |
| `EventType` enum (all 26 values) | v0.4.3 | `core/models.py` |
| `ExecutionRecord` dataclass (all fields, `to_dict()`) | v0.4.3 | `core/models.py` |
| `Evidence` dataclass (all fields) | v0.4.3 | `core/models.py` |
| `ExecutionContext` dataclass (all fields) | v0.4.3 | `core/models.py` |
| `Agent.agent_id` format (`agent_{8 hex}`) | v0.4.3 | `core/agent_store.py` |
| `Team.team_id` format (`team_{8 hex}`) | v0.4.3 | `core/agent_store.py` |
| `context_id` format (`ctx_{12 hex}`) | v0.4.3 | `core/context_store.py` |
| `evidence_id` format (`evi_{8 hex}`) | v0.4.3 | `commands/evidence.py` |
| `source_type` enum (`data`, `calculation`, `model_inference`, `external_api`) | v0.4.3 | `core/evidence_store.py` |
| `EventStore` public API (all query and write methods) | v0.4.3 | `core/event_store.py` |
| `AgentStore` public API (Agent + Team CRUD) | v0.4.3 | `core/agent_store.py` |
| `ContextStore` public API (Context CRUD + assignment) | v0.4.3 | `core/context_store.py` |
| `EvidenceStore` public API (CRUD + chain + verification) | v0.4.3 | `core/evidence_store.py` |
| Execution Record compatibility levels (L1-L4) | v0.4.3 | `core/recorder.py` |
| Event `source` values (`runtime`, `adapter`, `scheduler`, `proxy`, `security`, `test`) | v0.4.3 | `core/models.py` / `core/event_store.py` |
| Store interface pattern (Section 6) | v0.4.3 | All `*_store.py` modules |

### 8.2 Phase 2+ Interfaces (NOT Frozen)

The following are **defined but not yet implemented**. Their exact signatures, payload schemas, and IDs may change before implementation.

| Interface | Target Phase | Notes |
|-----------|-------------|-------|
| `Org` entity and `org_id` format | Phase 2.2 | Will require adding `org_id` column to `teams` and `agents` tables |
| CRUD event types (`AgentCreated`, `TeamCreated`, `ContextCreated`, `PolicyChanged`, `CapabilityPublished`, etc.) | Phase 2.1 | Emission protocol defined in Section 3.4 |
| `source` values `"identity"`, `"context"`, `"interop"` | Phase 2.1 | Reserved but not yet emitted |
| Context Manifest YAML format (Section 4.4) | Phase 2.2 | The `kind: Context` serialization format |
| `CapabilityEntry` registry model | Phase 3.1 | Defined in `models.py` but not backed by a dedicated store |
| Federated Registry (SPEC-0006) | Phase 3.2 | Stub exists in `core/federated.py` |
| Security events beyond `PolicyEvaluated` | Phase 3.1 | `PermissionGranted`, `PermissionDenied`, `ReviewExpired`, `PolicyViolation` are defined in enum but never emitted |
| Evolution Loop events | Phase 3+ | `SuggestionGenerated`, `SuggestionAutoApplied`, `SuggestionDismissed`, `LoopIteration` are defined but never emitted |
| Layered policy overrides (Org -> Team -> User -> Runtime) | Phase 3.1 | Documented in SPEC-0004 Section 12 |
| Manifest signing (Ed25519) | Phase 3.2 | Documented in BLUEPRINT Section 3.2 |
| Cross-database foreign key enforcement | Phase 2+ | Currently application-layer only |

### 8.3 Adding New Event Types

New event types may be added to the `EventType` enum without a spec version bump, provided they:

1. Are added to the **end** of the enum (preserving existing value ordinals).
2. Follow the `ALL_CAPS = "PascalCase"` naming convention.
3. Do not change the meaning or payload schema of any existing event type.

Adding new CRUD event types for the Phase 2 emission protocol (Section 3.2) is the expected first extension of this spec.

---

## 9. Summary: What This Spec Standardizes

| Section | What It Defines | Binding On |
|---------|----------------|------------|
| 2. Unified ID Hierarchy | Exact prefix formats, entropy sizes, assignment rules | All six layers |
| 3. Event-as-Universal-State-Change | Which CRUD operations emit which events, emission protocol | All five stores |
| 4. Context Protocol | Context Manifest format, sharing protocol, assignment model | Context layer + Execution layer |
| 5. Evidence Interface | Exact field definitions, source_type enum, chain DAG algorithm | Verification layer |
| 6. Storage Abstraction | Store interface pattern, connection strategies, conventions | All five stores |
| 7. Replay Readiness | Required fields, replay procedure, four-level compatibility | Execution layer |
| 8. Freeze Declaration | Which interfaces are FROZEN v1.0 vs Phase 2+ | All contributors |

---

## 10. References

- **CONSTITUTION.md** Article II (Five-Plane Architecture, Hard Constraints)
- **CONSTITUTION.md** Article II Section 2 R3 (Event Bus as Single Source of Truth)
- **BLUEPRINT.md** Six-Layer Architecture, Phase boundaries, dependency graph
- **SPEC-0001** Capability Manifest (ID format: `name@version`)
- **SPEC-0003** Event Schema (Event type enum, record structure, Event Store)
- **SPEC-0004** Security Model (Policy evaluation events, Phase 2+ roadmap)
- **`core/models.py`** Canonical dataclass definitions for Event, ExecutionRecord, Evidence, ExecutionContext
- **`core/evidence_store.py`** `_VALID_SOURCE_TYPES` frozen set
- **`core/recorder.py`** `compare_records()` four-level compatibility check
