# P1 Runtime Kernel — Architecture & Technical Design

**Date:** 2026-07-20
**Status:** Design Document
**Target:** Milestone 1 — Runnable Runtime Kernel

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Module Dependency Order](#2-module-dependency-order)
3. [Key Interface Design](#3-key-interface-design)
4. [Development Sequence & Code Size](#4-development-sequence--code-size)
5. [Workflow Walkthrough](#5-workflow-walkthrough)

---

## 1. Project Structure

```
reference/
├── pyproject.toml                          # Python project metadata (hatchling, Python >=3.11)
├── ARCHITECTURE-P1.md                      # This document
├── examples/
│   └── demo_workflow.py                    # End-to-end demo script (creates a Goal → runs the full pipeline)
│
└── src/
    └── agentos/
        ├── __init__.py                     # Top-level package; re-exports key symbols
        │
        ├── backbone/                       # ✅ EXISTS — RFC-0500 Event Backbone
        │   ├── __init__.py                 # Empty (namespace package marker)
        │   ├── event.py                    # Event dataclass (envelope)
        │   ├── schema.py                   # SchemaRegistry (event type validation)
        │   ├── store.py                    # EventStore (SQLite append-only log)
        │   └── bus.py                      # EventBus (in-memory pub/sub)
        │
        ├── task/                           # 🆕 — RFC-0001 Task State Machine
        │   ├── __init__.py
        │   ├── state.py                    # TaskState enum (17 states + transition table)
        │   ├── model.py                    # Task dataclass (task_id, state, metadata, retry policy)
        │   ├── machine.py                  # StateMachine — transition validation + execution
        │   └── errors.py                   # RetryableFailure, FatalFailure, TaskError hierarchy
        │
        ├── planner/                        # 🆕 — RFC-0101 Planner Architecture
        │   ├── __init__.py
        │   ├── intent.py                   # IntentEngine — Goal → Intent translation (rule-based)
        │   ├── workflow.py                 # Workflow registry / loader (in-memory Workflow definitions)
        │   ├── compiler.py                 # 8-pass compiler pipeline orchestrator
        │   ├── passes/
        │   │   ├── __init__.py
        │   │   ├── p1_parse.py             # Pass 1: Parsing (YAML → stage list)
        │   │   ├── p2_graph.py            # Pass 2: Graph Build (adjacency DAG + topological sort)
        │   │   ├── p3_rules.py            # Pass 3: Rule Injection (constraint annotations)
        │   │   ├── p4_conditions.py        # Pass 4: Condition Simplification (keep/prune decisions)
        │   │   ├── p5_prune.py             # Pass 5: Dead Node Elimination (prune graph)
        │   │   ├── p6_bind.py              # Pass 6: Capability Bind (negotiation + assignment)
        │   │   ├── p7_cost.py              # Pass 7: Cost Optimization (profile-based ranking)
        │   │   └── p8_output.py            # Pass 8: Output Format (serialize ExecutionPlan)
        │   ├── negotiation.py              # CapabilityNegotiator — stage ↔ capability matching
        │   └── plan.py                     # ExecutionPlan dataclass (compiler output)
        │
        ├── engine/                         # 🆕 — RFC-0102 Execution Engine
        │   ├── __init__.py
        │   ├── ingestor.py                 # PlanIngestor — validate + ingest ExecutionPlan
        │   ├── factory.py                  # TaskFactory — plan stages → Task instances
        │   ├── tracker.py                  # DependencyTracker — DAG dependency tracking (Ready signals)
        │   ├── scheduler.py                # Scheduler — dispatch + concurrency management
        │   ├── context.py                  # ContextManager — stage output → downstream input
        │   ├── lifecycle.py                # Lifecycle — Execution-level state machine
        │   └── recovery.py                 # StateRecovery — Event Store → rebuild active state
        │
        ├── pool/                           # 🆕 — RFC-0200/0203 Capability Pool
        │   ├── __init__.py
        │   ├── registry.py                 # CapabilityRegistry — discoverable capability metadata
        │   ├── pool.py                     # CapabilityPool — load, invoke, cancel, health
        │   ├── contract.py                 # InvocationContext, ExecutionResult dataclasses
        │   └── errors.py                   # CapabilityError, TimeoutError hierarchy
        │
        ├── capabilities/                   # 🆕 — 3 real Capability implementations
        │   ├── __init__.py
        │   ├── base.py                     # BaseCapability ABC (all capabilities inherit from this)
        │   ├── llm_research.py             # LLM Research capability (wraps OpenAI/Anthropic API)
        │   ├── python_exec.py              # Python Execution capability (sandboxed exec)
        │   └── web_search.py               # Web Search capability (DuckDuckGo / Firecrawl)
        │
        └── kernel.py                       # 🆕 — Main entry point; wires everything together
                                            #   orchestrates: Intent → Planner → Engine → Pool → result
```

### File Count & Breakdown

| Module | Files | Est. LOC | Purpose |
|--------|-------|----------|---------|
| `backbone/` | 4 (done) | ~400 | Event Bus + Store + Schema + Envelope |
| `task/` | 4 | ~220 | Task state machine, 17-state transition engine |
| `planner/` | 12 | ~550 | 8-pass compiler, Intent Engine, Negotiation |
| `engine/` | 7 | ~450 | Plan ingest, DAG tracking, scheduling, lifecycle |
| `pool/` | 4 | ~200 | Capability loading, invoke, cancel |
| `capabilities/` | 4 | ~350 | 3 real capabilities + ABC |
| `kernel.py` | 1 | ~100 | Orchestration entry point |
| `examples/` | 1 | ~80 | Demo workflow |
| **Total** | **37** | **~2,350** | |

---

## 2. Module Dependency Order

The development follows a **bottom-up** order — build the leaf dependencies first, then the orchestrators.

```
Phase 1 ─── backbone/       (done — bus, store, event, schema)
                │
Phase 2 ─── task/           (depends on: nothing — standalone state machine)
                │
Phase 3 ─── pool/           (depends on: backbone for event publishing)
    └── capabilities/       (depends on: pool/base.py for BaseCapability)
                │
Phase 4 ─── planner/        (depends on: backbone, pool/registry for negotiation)
                │
Phase 5 ─── engine/         (depends on: backbone, task, pool, planner/plan)
                │
Phase 6 ─── kernel.py       (wires everything together)
    └── demo_workflow.py    (end-to-end test)
```

### Detailed Order

| Step | Module | Files | Write When | Testable? |
|------|--------|-------|-----------|-----------|
| 0 | `backbone/` | 4 files | ✅ Done | ✅ Unit tests exist |
| 1 | `task/state.py` | Enum + transition table | Phase 2 start | ✅ Immediately (pure data) |
| 2 | `task/model.py` | Task dataclass | After state.py | ✅ Immediately |
| 3 | `task/machine.py` | StateMachine class | After model.py | ✅ Immediately (pure logic) |
| 4 | `task/errors.py` | Error hierarchy | After machine.py | ✅ Immediately |
| 5 | `pool/contract.py` | InvocationContext, ExecutionResult | Phase 3 start | ✅ Immediately (dataclasses) |
| 6 | `pool/registry.py` | CapabilityRegistry | After contract.py | ✅ Standalone |
| 7 | `capabilities/base.py` | BaseCapability ABC | After contract.py | ✅ Standalone |
| 8 | `capabilities/llm_research.py` | LLM capability | After base.py | ✅ With API key |
| 9 | `capabilities/python_exec.py` | Python sandbox | After base.py | ✅ Immediately |
| 10 | `capabilities/web_search.py` | Web search | After base.py | ✅ With network |
| 11 | `pool/pool.py` | CapabilityPool | After registry.py + capabilities | ✅ Can test loading |
| 12 | `planner/plan.py` | ExecutionPlan dataclass | Phase 4 start | ✅ Immediately |
| 13 | `planner/workflow.py` | Workflow registry | After plan.py | ✅ Immediately |
| 14 | `planner/intent.py` | IntentEngine | After workflow.py | ✅ Rule-based |
| 15 | `planner/passes/*` | 8 passes | After plan.py | ✅ Each pass individually |
| 16 | `planner/negotiation.py` | CapabilityNegotiator | After passes | ✅ With registry |
| 17 | `planner/compiler.py` | Pipeline orchestrator | After all passes | ✅ After all passes |
| 18 | `engine/ingestor.py` | PlanIngestor | Phase 5 start | ✅ With plan |
| 19 | `engine/factory.py` | TaskFactory | After ingestor | ✅ With task module |
| 20 | `engine/tracker.py` | DependencyTracker | After factory | ✅ Core scheduling |
| 21 | `engine/scheduler.py` | Scheduler | After tracker | ✅ Core scheduling |
| 22 | `engine/context.py` | ContextManager | After scheduler | ✅ Data flow |
| 23 | `engine/lifecycle.py` | Lifecycle | After context | ✅ Execution machine |
| 24 | `engine/recovery.py` | StateRecovery | After lifecycle | ✅ With Event Store |
| 25 | `kernel.py` | Orchestrator | Phase 6 | ✅ After all modules |
| 26 | `examples/demo_workflow.py` | Demo | After kernel | ✅ End-to-end |

---

## 3. Key Interface Design

### 3.1 Event Bus API

```python
# ── Publish / Subscribe ──────────────────────────────────────────

class EventBus:
    def subscribe(self, event_type_prefix: str,
                  callback: Callable[[Event], bool | None]) -> None
    def unsubscribe(self, event_type_prefix: str,
                    callback: Callable[[Event], bool | None]) -> None
    def publish(self, event: Event) -> list[DeadLetterEntry]

    # ── Batch publish (atomic sequence) ─────────────────────────
    def publish_batch(self, events: list[Event]) -> list[DeadLetterEntry]

    # ── Dead-letter management ──────────────────────────────────
    @property
    def dead_letter_queue(self) -> list[DeadLetterEntry]
    def replay_dead_letter(self) -> list[DeadLetterEntry]

# Design decisions:
# 1. Prefix-based subscription (exact or prefix matching)
# 2. Return False from callback = nack (triggers retry)
# 3. Built-in retry (3 attempts with backoff)
# 4. Dead-letter after max retries exhausted
# 5. Thread-safe via RLock
```

**Status:** ✅ Already implemented in `backbone/bus.py` — the interface above matches the existing code precisely. No changes needed for P1.

### 3.2 Task State Machine API

```python
# ── States (RFC-0001 §3.1) ──────────────────────────────────────

class TaskState(str, enum.Enum):
    CREATED             = "created"              # Initial state
    QUEUED              = "queued"               # In scheduling queue
    ASSIGNED            = "assigned"             # Capability selected
    RUNNING             = "running"              # Capability executing
    WAITING_REVIEW      = "waiting_review"        # Output produced, awaiting reviewer
    REVIEWED            = "reviewed"             # Reviewer result ready
    REVIEW_FAILED       = "review_failed"         # Reviewer rejected output
    COMPLETED           = "completed"            # ✅ Terminal — success
    COMPLETED_WITH_WARNING = "completed_with_warning"
    PARTIAL             = "partial"              # ✅ Terminal — partial output
    FAILED              = "failed"               # Non-terminal until routed
    RETRY_QUEUED        = "retry_queued"          # Will retry
    REPLAN_REQUESTED    = "replan_requested"      # Needs new plan
    CANCEL_QUEUED       = "cancel_queued"         # Cancellation in progress
    CANCELLED           = "cancelled"            # ✅ Terminal — intentional stop
    SKIPPED             = "skipped"              # ✅ Terminal — condition false
    ARCHIVED            = "archived"             # ✅ Terminal — audit trail
    PENDING_REVIEW      = "pending_review"        # Held for downstream failure
    PENDING_QUEUED      = "pending_queued"        # Released from hold

# ── Transition Engine ──────────────────────────────────────────

class TransitionTable:
    """Compile-time transition rules (RFC-0001 §3.2, T1–T27)."""
    def is_valid(self, from_state: TaskState, to_state: TaskState,
                 trigger: str) -> bool

class StateMachine:
    def transition(self, task: Task, to_state: TaskState,
                   trigger: str, metadata: dict | None = None) -> Task
    """Execute a state transition. Validates rules, updates task,
       publishes Task:StateChanged event. Raises on invalid transition."""

# Design decisions:
# 1. Deterministic — same (state, trigger) always produces same next state
# 2. Event-driven — every transition publishes a Task:StateChanged event
# 3. Pure — StateMachine is stateless; Task holds state
# 4. Validation — illegal transitions raise InvalidTransition
```

### 3.3 Planner Compiler Pipeline API

```python
# ── Compiler Pipeline ──────────────────────────────────────────

class CompilerPipeline:
    """8-pass compiler: Workflow → ExecutionPlan."""

    def __init__(self, passes: list[Pass]):
        self.passes = passes

    def compile(self, workflow: Workflow, intent: Intent,
                goal: Goal, registry: CapabilityRegistry,
                rule_manager) -> ExecutionPlan | CompileError
    """Run all passes sequentially. Publish Planner:PassCompleted
       events at each step."""

# Each pass is a callable:
#   Pass = Callable[[CompileContext], CompileContext]
# where CompileContext carries:
#   - input_workflow: Workflow
#   - intent: Intent
#   - goal: Goal
#   - dag: StageGraph (mutable)
#   - rules: list[Rule]
#   - bindings: dict[str, CapabilityManifest]
#   - errors: list[CompileError]

# ── Capability Negotiation ─────────────────────────────────────

class CapabilityNegotiator:
    def negotiate(self, stage_requirements: dict,
                  available: list[CapabilityManifest],
                  profile: Profile | None = None
                  ) -> tuple[str, CapabilityManifest] | None
    """Match requirements → best capability. Returns (stage_id, manifest)
       or None if no match."""

# Design decisions:
# 1. Each pass is a pure function of CompileContext
# 2. CompileContext is the only mutable object; passes write to it sequentially
# 3. Pipeline publishes events per-pass for observability
# 4. Negotiation is pluggable (default: quality-score ranking)
```

### 3.4 Execution Engine API

```python
# ── Plan Ingest ─────────────────────────────────────────────────

class PlanIngestor:
    def ingest(self, plan: ExecutionPlan) -> str
    """Validate plan schema, create execution, return execution_id.
       Publishes Execution:Created."""

# ── Dependency Tracker ─────────────────────────────────────────

class DependencyTracker:
    def initialize(self, tasks: list[Task], plan: ExecutionPlan)
    def on_task_done(self, stage_id: str, state: TaskState) -> list[str]
    """Returns list of newly-ready stage_ids (dependencies satisfied)."""
    def on_task_skipped(self, stage_id: str) -> list[str]
    def on_task_failed(self, stage_id: str) -> list[str]
    """Returns list of downstream stage_ids to cancel."""
    def next_ready(self) -> str | None

# ── Scheduler ──────────────────────────────────────────────────

class Scheduler:
    def enqueue(self, stage_id: str) -> None
    def dequeue(self) -> str | None
    """Priority queue — critical-path stages first, then FIFO."""
    def dispatch(self, stage_id: str,
                 capability_pool: CapabilityPool) -> None
    """Task:Queued → Task:Assigned → CapabilityPool.invoke()"""

# ── State Recovery ─────────────────────────────────────────────

class StateRecovery:
    def recover(self, event_store: EventStore) -> dict[str, ExecutionState]
    """Replay events → rebuild active executions.
       Load latest snapshot, then replay events after snapshot sequence."""

# Design decisions:
# 1. Engine is stateless — all mutable state lives in Tracker/Context
# 2. State is rebuildable from Event Store stream
# 3. CapabilityPool is the ONLY module that invokes external resources
# 4. Scheduler communicates via Event Bus (decoupled)
```

### 3.5 Capability Invoke / Cancel API

```python
# ── Base Capability Interface ──────────────────────────────────

class BaseCapability(ABC):
    capability_id: str           # "cap://agentos/python-exec@1.0.0"
    display_name: str
    version: str
    manifest: CapabilityManifest  # Static metadata

    @abstractmethod
    async def invoke(self, task: Task,
                     context: InvocationContext,
                     cancel_token: CancellationToken) -> ExecutionResult
    """Execute the task. Returns ExecutionResult (sync or async).

    Args:
        task: The Task to execute (carries input in task.input)
        context: Execution context (session, execution, profile config)
        cancel_token: Check .cancelled to respect cancellation

    Returns:
        ExecutionResult with output or error details

    Raises:
        TimeoutError: If execution exceeds max_duration
        CapabilityError: For non-retryable failures
    """

    async def cancel(self, task_id: str) -> bool
    """Signal cancellation to a running invocation.
       Default implementation: set cancel_token. Override per Capability."""
    ...

# ── Invocation Context ─────────────────────────────────────────

@dataclass
class InvocationContext:
    task_id: str
    execution_id: str
    session_id: str
    stage_id: str
    profile_config: dict
    max_duration_ms: int           # Timeout — Capability must respect this
    retry_count: int               # 0 on first attempt

@dataclass
class ExecutionResult:
    success: bool
    output: dict | None            # Structured output per manifest.output_schema
    error: str | None              # Human-readable error
    error_code: str | None         # retryable_error | fatal_error | timeout
    cost: CostAccumulated          # tokens, api_calls, usd
    completeness: float            # 1.0 = full, 0.0–0.999 = partial
    trace: list[str] | None        # Debug trace lines

# ── Cancellation Token ─────────────────────────────────────────

class CancellationToken:
    """Thread-safe cancellation signal."""
    def cancel(self) -> None
    @property
    def cancelled(self) -> bool

# ── CapabilityPool API ─────────────────────────────────────────

class CapabilityPool:
    def load(self, capability_cls: type[BaseCapability],
             config: dict | None = None) -> None
    """Load a capability class into the pool."""

    def unload(self, capability_id: str) -> None
    """Unload from pool (drain in-flight, reject new)."""

    async def invoke(self, task: Task,
                     context: InvocationContext) -> ExecutionResult
    """Find the right capability by task.capability_binding.
       Handles timeout, cancellation, cost tracking."""

    async def cancel(self, execution_id: str,
                     stage_id: str) -> bool
    """Cancel a running invocation."""

    @property
    def loaded(self) -> list[str]
    """List of loaded capability IDs."""

# Design decisions:
# 1. Async invoke with CancellationToken (so Capabilities can be long-running)
# 2. ExecutionResult carries structured output AND cost — no ad-hoc reporting
# 3. CapabilityPool is the single dispatch point — Engine never calls Capabilities directly
# 4. Each Capability declares its manifest (input schema, output schema, cost model)
# 5. Built-in timeout enforcement at Pool level (overrides capability-level timeout)

Design rationale:
- `async` is fundamental — LLM calls take seconds; synchronous blocking wastes threads
- CancellationToken enables graceful shutdown (no thread kills)
- ExecutionResult.completeness enables Partial results (RFC-0001 §4.1)
- Pool handles routing so Engine stays stateless
```

### 3.6 Kernel Orchestrator API

```python
class AgentOSKernel:
    """Top-level entry point. Wires all modules together."""

    def __init__(self, db_path: str = "agentos.db"):
        self.bus = EventBus()
        self.store = EventStore(db_path)
        self.schema_registry = SchemaRegistry()
        self.task_machine = StateMachine()
        self.capability_registry = CapabilityRegistry()
        self.capability_pool = CapabilityPool()
        self.planner = CompilerPipeline(passes=ALL_PASSES)
        self.engine = ExecutionEngine(...)
        self.intent_engine = IntentEngine()
        self.workflow_registry = WorkflowRegistry()

    async def run_goal(self, goal: Goal) -> ExecutionResult
    """Full pipeline: Goal → Intent → Plan → Execute → Result.

    1. IntentEngine.resolve(goal) → Intent
    2. WorkflowRegistry.resolve(intent) → Workflow
    3. Planner.compile(workflow, intent, goal, registry) → ExecutionPlan
    4. Engine.execute(plan, capability_pool) → ExecutionResult
    5. Return final result + cost + audit trail
    """

    def close(self):
        self.store.close()
```

---

## 4. Development Sequence & Code Size

### Phase Breakdown

| Phase | Scope | Files | Est. LOC | Time Est. | Verification |
|-------|-------|-------|----------|-----------|-------------|
| **Phase 1** | Backbone (done) | 4 | ~400 | ✅ Done | Unit tests pass |
| **Phase 2** | Task State Machine | 4 | ~220 | 0.5 day | Test all 27 transitions |
| **Phase 2a** | Pool Contracts + Registry | 2 | ~80 | 0.25 day | Dataclass validation |
| **Phase 3** | Capabilities (3 + base) + Pool | 5 | ~550 | 1.5 days | Each capability testable individually |
| **Phase 4** | Planner (intent → 8 passes → plan) | 12 | ~550 | 2 days | Compile a real workflow → ExecutionPlan |
| **Phase 5** | Engine (ingest → track → schedule → lifecycle → recover) | 7 | ~450 | 1.5 days | Run a plan to completion |
| **Phase 6** | Kernel + Demo | 2 | ~180 | 0.5 day | End-to-end demo runs |
| **Tests** | Per-module + integration | ~20 | ~600 | In parallel | pytest suite |
| **Total** | **37 source + ~20 test** | **~3,000** | **~6 days** | |

### Estimated LOC by Module

```
backbone/          400  (already done)
task/              220  (state enum + transition table + machine)
pool/              ~80  (contract + registry)
capabilities/      350  (base + llm + python + web)
pool/              120  (pool.py)
planner/           550  (intent + workflow + plan + 8 passes + compiler)
engine/            450  (ingest + factory + tracker + scheduler + context + lifecycle + recovery)
kernel.py          100  (orchestrator)
demo_workflow.py    80  (end-to-end demo)
─────────────────
~2,350 source + ~600 test = ~2,950 total
```

### Testing Strategy

| Module | Test Strategy | Key Scenarios |
|--------|--------------|---------------|
| `task/machine.py` | Pure unit tests | All 27 transitions; illegal transitions raise; retry count tracking |
| `planner/passes/*` | Unit per pass | Parse valid/invalid YAML; cycle detection; prune propagation; negotiation match/no-match |
| `planner/compiler.py` | Integration | Full 8-pass pipeline with mock registry |
| `engine/tracker.py` | Unit | Dependency satisfaction; cascade cancel; ready queue ordering |
| `engine/scheduler.py` | Unit + mock | Dispatch order; concurrency limit; task timeout |
| `engine/ingestor.py` | Unit | Valid/invalid plan validation |
| `pool/pool.py` | Unit + mock | Load/unload; invoke routing; timeout; cancel propagation |
| `capabilities/*.py` | Integration | LLM call with real/echo API; python exec sandbox; web search with DuckDuckGo |
| `kernel.py` | Integration | Full `run_goal()` with demo workflow |

---

## 5. Workflow Walkthrough

This traces a complete P1 flow for: **"research Nvidia stock for investment recommendation"**

```
Step   Module              Action                                     Event Published
────   ──────              ──────                                     ───────────────
 1     User                submits Goal("research Nvidia stock")
 2     IntentEngine        resolves goal → Intent(domain=finance,
                            task_type=stock_research, company=NVIDIA)  Intent:Resolved
 3     WorkflowRegistry    resolves intent → Workflow("stock-research")
 4     Planner             Pass 1: Parse workflow YAML → stage list
 5     Planner             Pass 2: Build adjacency DAG, topological sort
 6     Planner             Pass 3: Inject rules (citation_required,
                            max_depth=deep)
 7     Planner             Pass 4: Evaluate conditions (keep all stages)
 8     Planner             Pass 5: Prune (no dead nodes)
 9     Planner             Pass 6: Bind capabilities:
                              research → cap://agentos/llm-research@1.0
                              analyze  → cap://agentos/python-exec@1.0
                              search   → cap://agentos/web-search@1.0
10     Planner             Pass 7: Cost optimize (profile preferences)
11     Planner             Pass 8: Output ExecutionPlan JSON           Planner:PlanReady
12     Engine.Ingestor     validate plan → create Execution            Execution:Created
13     Engine.Factory      stages → Tasks[3] (Created state)           Task:Created (×3)
14     Engine.Tracker      initialize DAG: root = [search, research]
15     Engine.Scheduler    dispatch search → Pool.invoke()             Task:Queued→Assigned→Running
16     Engine.Scheduler    dispatch research → Pool.invoke()           Task:Queued→Assigned→Running
17     WebSearch.cap       execute → return search results             Capability:OutputProduced
18     Engine.Tracker      search done → research still running
19     LLMResearch.cap     execute → return analysis                   Capability:OutputProduced
20     Engine.Tracker      research done → analyze ready
21     Engine.Scheduler    dispatch analyze → Pool.invoke()            Task:Queued→Assigned→Running
22     PythonExec.cap      execute → compute recommendation            Capability:OutputProduced
23     Engine.Tracker      analyze done → all complete
24     Engine.Lifecycle    Execution: Completed                        Execution:Completed
25     Kernel              return final result { output, cost, trace }
```

---

## Appendix: Key Design Decisions

| # | Decision | Rationale | RFC |
|---|----------|-----------|-----|
| 1 | Event sourcing for all state | Enables full audit trail + crash recovery | ADR-0001 / RFC-0500 |
| 2 | Kernel is stateless | Scale horizontally; recover from Event Store on restart | ADR-0002 / RFC-0001 |
| 3 | Prefix-based subscription | Simpler than full regex; matches module boundaries | RFC-0500 §5.1 |
| 4 | In-process Event Bus for P1 | No RPC overhead; can upgrade to Redis/NATS later | RFC-0500 §5 |
| 5 | SQLite for Event Store | Single-file, zero-config, ACID; sufficient for P1 | RFC-0500 §6 |
| 6 | Planner is an 8-pass compiler | Each pass is a pure transformation; debuggable, testable, composable | RFC-0101 §3 |
| 7 | CapabilityPool as sole dispatch boundary | Engine never calls external resources directly | RFC-0200 §4 |
| 8 | Async Capability invoke with CancellationToken | LLM calls are long-running; cancellation must be safe | RFC-0200 §4.5 |
| 9 | 17 states + 27 transitions for Task | Maps directly to RFC-0001; no ambiguity | RFC-0001 §3 |
| 10 | Module-per-file, clear interface boundaries | Readability, testability, contribution-friendliness | — |
