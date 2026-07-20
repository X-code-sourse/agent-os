# RFC-0101: Planner Architecture

**Status:** Proposed
**Type:** Control Plane RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0001 v1.0, RFC-0002, RFC-0100 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Planner Architecture** — the internal structure of the Planner module, its compiler pass pipeline, Capability Negotiation protocol, Replan handling, and caching strategy. The Planner is the bridge between declarative Workflows (RFC-0100) and executable Tasks (RFC-0001).

---

## 2. Motivation

The Planner is not a script that "processes YAML." It is a **compiler** — it takes a declarative Workflow Graph, applies Rules, resolves Capabilities, optimizes the execution order, and produces an executable Execution Plan. Without a defined internal architecture:

- The boundary between Planner and Execution Engine blurs (who does what?)
- Capability Negotiation logic scatters across modules
- Replan becomes ad-hoc error handling instead of a protocol
- The system loses its deterministic compilation guarantee

---

## 3. Compiler Pass Pipeline

The Planner compiles a Workflow into an Execution Plan through a sequence of **passes**. Each pass transforms the representation, one step at a time.

### 3.1 Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PLANNER PIPELINE                             │
│                                                                     │
│  ┌──────────┐   ┌──────────┐   ┌────────────┐   ┌──────────────┐  │
│  │  Parsing │   │  Graph   │   │   Rule     │   │  Condition   │  │
│  │   Pass   │──►│  Build   │──►│  Injection │──►│Simplification│  │
│  └──────────┘   └──────────┘   └────────────┘   └──────────────┘  │
│                                                           │        │
│                                                           ▼        │
│  ┌──────────┐   ┌──────────┐   ┌────────────┐   ┌──────────────┐  │
│  │  Output  │   │  Cost    │   │ Capability │   │  Dead Node   │  │
│  │  Format  │◄──│Optimize  │◄──│   Bind     │◄──│  Elimination │  │
│  └──────────┘   └──────────┘   └────────────┘   └──────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Pass Definitions

#### Pass 1: Parsing Pass

**Input:** Workflow YAML + Intent + Goal
**Output:** Unvalidated Stage Graph (raw AST)
**Operations:**
1. Parse YAML into an in-memory stage list
2. Validate all fields against RFC-0100 §3 schema
3. Validate condition expressions against the DSL grammar (RFC-0100 §5.2)
4. Validate dependency references (every `depends_on` target exists)
5. **Fail on:** invalid YAML, missing required fields, bad condition syntax, dangling dependency references

**Stateless guarantee:** Pass 1 does not read or write any external state. It is a pure function of (Workflow YAML, Intent).

---

#### Pass 2: Graph Build

**Input:** Parsed Stage List
**Output:** Adjacency-list DAG (Maximal Graph with adjacency metadata)
**Operations:**
1. Build adjacency list for forward traversal: `graph[node] = [stages that depend on node]`
2. Build reverse adjacency list: `reverse[node] = [stages that node depends on]`
3. Compute topological ordering (Kahn's algorithm)
4. **Fail on:** cycle detected (DAG validation fails at registration)—this is a Workflow bug, not a Planner bug

---

#### Pass 3: Rule Injection

**Input:** DAG + Rule Set (from Rule Manager)
**Output:** DAG with per-stage constraint annotations
**Operations:**
1. Rule Manager provides a set of applicable rules based on:
   - Workflow ID match (`scope.workflows`)
   - Stage type match (`scope.task_types`)
   - Domain match (`scope.domains`)
2. Each matched Rule's constraints are injected into the corresponding stage
3. Constraints are attached to stages as metadata, not as executable logic
4. Rule injection happens over the **maximal graph** (before pruning), so constraints are available even for stages that may be pruned later

**Stateless guarantee:** Pass 3 queries Rule Manager (via Event or direct call, depending on v1 implementation detail). The Rule Manager is a Metadata Plane module; the Planner caches nothing from this pass.

---

#### Pass 4: Condition Simplification

**Input:** Rule-annotated DAG + Intent + Input
**Output:** Decision vector: `{ stage_id: keep | prune }` for every stage
**Operations:**
1. Evaluate each stage's `condition` expression against `user_intent.*` and `input.*`
2. For `condition: "always"`, evaluate to true immediately (no expression parse needed)
3. For compound conditions, evaluate left-to-right with short-circuit
4. Produce a decision vector: which stages survive, which are pruned

**Pruning propagation (RFC-0100 §7.3):**
```
for each stage in topological_order:
    if stage.decision == prune:
        for each downstream_stage that has stage in its depends_on:
            remove stage from downstream_stage.depends_on
            if downstream_stage.depends_on becomes empty:
                if downstream_stage.condition != "always":
                    mark downstream_stage as prune (no input to process)
                else:
                    keep downstream_stage (its condition is unconditional)
```

---

#### Pass 5: Dead Node Elimination

**Input:** DAG + Decision Vector
**Output:** Pruned DAG (Minimal Viable Graph)
**Operations:**
1. Remove all stages marked `prune` from the graph
2. Remove all edges referencing pruned stages
3. For `parallel_gate` and `join_gate` nodes:
   - If zero children survive, replace with a pass-through (if in a chain) or remove entirely
   - If one child survives, replace with a direct connection (gate is unnecessary)
4. Re-validate that the resulting graph is connected (no orphaned stages with unsatisfiable dependencies)
5. Recompute topological ordering on the pruned graph

---

#### Pass 6: Capability Bind

**Input:** Pruned DAG with Requirements
**Output:** DAG with resolved Capability IDs
**Operations:**

This pass performs **Capability Negotiation** — the most complex pass.

```
For each stage with a requirements block:

    1. Planner sends CapabilityNegotiationRequest to Registry:
       {
         "stage_id": "financial_analysis",
         "requirements": {
           "capability_type": "research",
           "domain": ["finance", "sec_filing"],
           "language": "en",
           "quality_min": 0.85
         }
       }

    2. Registry returns CapabilityNegotiationResponse:
       {
         "stage_id": "financial_analysis",
         "matches": [
           {
             "capability_id": "cap://nous-research/research-v2@2.3.0",
             "quality": 0.94,
             "cost_per_call": 0.02,
             "avg_latency_ms": 2500,
             "model": "claude-sonnet-4"
           },
           {
             "capability_id": "cap://community-research/research-lite@1.1.0",
             "quality": 0.80,
             "cost_per_call": 0.005,
             "avg_latency_ms": 800,
             "model": "gpt-4o-mini"
           }
         ]
       }

    3. Planner applies Profile preferences:
       - If Profile specifies preferred_models, filter matches to those models
       - If Profile specifies cost_budget, filter matches within budget
       - If Profile does not specify preference, use quality score ranking (descending)

    4. Planner selects the best match and binds it:
       {
         "stage_id": "financial_analysis",
         "bound_capability": {
           "capability_id": "cap://nous-research/research-v2@2.3.0",
           "model": "claude-sonnet-4",
           "estimated_cost": 0.02,
           "estimated_latency_ms": 2500
         }
       }
```

**Negotiation failure handling:**
- If NO capability matches, Planner **fails the compilation** (does not proceed to execution)
- The failure is returned to the user/system as a `CompilationError` with detail:
  ```json
  {
    "error": "CompilationError",
    "stage_id": "financial_analysis",
    "reason": "No capability matches requirements: type=research, domain=[finance, sec_filing], quality_min=0.85",
    "suggestions": ["Lower quality_min to 0.7", "Check if research capability is registered"]
  }
  ```

**Stateless guarantee:** Pass 6 queries the Registry. The Planner does not cache Registry responses (caching is the Registry's responsibility).

---

#### Pass 7: Cost Optimization

**Input:** Capability-bound DAG
**Output:** DAG with cost estimates and parallelization hints
**Operations:**
1. Compute estimated cost for each stage: `capability.cost_per_call + (capability.cost_per_token * estimated_tokens)`
2. Estimate total execution cost (sum of all stages)
3. Compare against `Profile.cost_budget.max_per_execution`
4. If over budget: return a `BudgetExceeded` warning (not a failure; the Execution Engine will enforce the hard limit)
5. Identify stages with no transitive dependencies for parallel execution hints
6. Attach optimization metadata: `{ stage_id, estimated_cost, estimated_latency, parallelizable_with: [stage_ids] }`

---

#### Pass 8: Output Format

**Input:** Optimized, capability-bound DAG
**Output:** Final Execution Plan (JSON, per RFC-0100 §10)
**Operations:**
1. Serialize the DAG into the Execution Plan format
2. Attach compilation metadata:
   - `compiled_at` timestamp
   - Plan hash (for caching)
   - All pruned stages with reasons
   - Resolved capability bindings
3. Return the Execution Plan

**Plan hash computation:**
```
plan_hash = sha256(concat(
    workflow_id + workflow_version,
    sorted(rule_ids + rule_versions),
    profile_id + profile_version,
    intent_hash,
    input_hash
))
```

---

## 4. Capability Negotiation Protocol

### 4.1 Roles

| Role | Module | Responsible For |
|------|--------|-----------------|
| **Requester** | Planner (Pass 6) | Sending Requirements, applying Profile preferences, selecting match |
| **Resolver** | Metadata Registry | Matching Requirements against Manifests, returning ranked candidates |
| **Decider** | Execution Engine (optional override) | Selecting final Capability at runtime (if multiple valid matches exist) |

### 4.2 Protocol Flow

```
Planner                              Registry                        Capability Pool
   │                                    │                                │
   │── CapabilityNegotiationRequest ──► │                                │
   │    { stage_id, requirements }      │                                │
   │                                    │── query(Manifests) ────────► │
   │                                    │◄── matched Manifests ────────│
   │                                    │                                │
   │◄── CapabilityNegotiationResponse ──│                                │
   │    { matches: [ranked list] }      │                                │
   │                                    │                                │
   │  [Apply Profile preferences]       │                                │
   │  [Select best match]              │                                │
   │                                    │                                │
   │── CompilationResult ────────────► │                                │
   │    { plan_id, bindings[] }         │                                │
   │                                    │                                │
```

### 4.3 Match Ranking Algorithm

When multiple Manifests match, the ranking algorithm (implemented by Registry) is:

```
score(capability) = (
    0.50 * normalize(quality_score, 0, 1) +
    0.25 * (1 - normalize(cost_per_call, min_cost, max_cost)) +
    0.25 * (1 - normalize(latency_ms, min_latency, max_latency))
)
```

Default weights assume **quality is worth more than cost and latency combined**. Profiles can override weights.

### 4.4 Registry Interface

```json
// Request (Planner → Registry)
{
  "request_type": "capability_negotiation",
  "requirements": {
    "capability_type": "research",
    "domain": ["finance", "sec_filing"],
    "language": "en",
    "quality_min": 0.85,
    "cost_max": 0.5,
    "latency_max_ms": 5000,
    "required_features": ["citation", "source_attribution"]
  },
  "profile_preferences": {
    "preferred_models": ["claude-sonnet-4"],
    "cost_budget": { "max_per_task": 0.5 }
  }
}

// Response (Registry → Planner)
{
  "matched": true,
  "matches": [
    {
      "capability_id": "cap://nous-research/research-v2@2.3.0",
      "quality": 0.94,
      "cost_per_call": 0.02,
      "avg_latency_ms": 2500,
      "model": "claude-sonnet-4",
      "features_supported": ["citation", "source_attribution", "web_search"]
    }
  ],
  "negotiation_duration_ms": 45
}
```

---

## 5. Replan Protocol

### 5.1 When Replan Happens

From RFC-0001 §4.3, a ReplanRequest is emitted when:

```
IF replan_candidate(Task) == true AND execution.state == 'running':
    emit ReplanRequested
```

### 5.2 Replan Flow

```
Execution Engine                    Planner                    Rule Manager
      │                                │                          │
      │  Task:Failed                   │                          │
      │  retries_exhausted=true        │                          │
      │  replan_allowed=true           │                          │
      │                                │                          │
      │── ReplanRequest ──────────────►│                          │
      │  { execution_id,               │                          │
      │    failed_stage_id,            │                          │
      │    failed_task_id,             │                          │
      │    reason,                     │                          │
      │    remaining_stages,           │                          │
      │    completed_outputs }         │                          │
      │                                │                          │
      │                                │  [Planner re-enters       │
      │                                │   the pipeline at         │
      │                                │   Pass 3 (Rule Injection) │
      │                                │   or Pass 6 (Cap Bind),   │
      │                                │   depending on failure]   │
      │                                │                          │
      │                                │── (if rules changed) ──► │
      │                                │◄── updated rules ────────│
      │                                │                          │
      │                                │  [Planner produces        │
      │                                │   a Replacement Plan      │
      │                                │   for remaining stages]   │
      │                                │                          │
      │◄── ReplacementPlan ────────────│                          │
      │  { execution_id,               │                          │
      │    new_stages[],               │                          │
      │    inherited_context,          │                          │
      │    plan_type: "replacement" }  │                          │
      │                                │                          │
      │  [Execution Engine cancels     │                          │
      │   remaining old stages and     │                          │
      │   dispatches new stages]       │                          │
```

### 5.3 Replan Pass Re-entry Points

The Planner does not re-run the entire pipeline on replan. It re-enters at the appropriate pass:

| Failure Reason | Re-entry Pass | Why |
|---------------|---------------|-----|
| Capability not found (Capability Bind failure) | Pass 6 (Capability Bind) | Only binding needs redo |
| Capability execution error (non-retryable) | Pass 6 (Capability Bind) | Try a different Capability |
| Rule constraint violation | Pass 3 (Rule Injection) | Rules may have been updated |
| Stage condition misclassification | Pass 4 (Condition Simplification) | Re-evaluate with more context |
| Structural: Workflow needs modification | Full pipeline (Pass 1) | Fundamental change needed |

### 5.4 Replan Safety

- `replan_count` is tracked per Execution (RFC-0001 §8.4)
- If `replan_count >= max_replans` (default: 3), Planner returns `ReplanRefused`
- Execution Engine transitions Execution to `Failed`
- Replan loops are flagged for Loop analysis

---

## 6. Plan Caching

### 6.1 Cache Key

```
cache_key = sha256(concat(
    workflow_id + workflow_version,
    sorted(rule_ids + rule_versions),
    profile_id + profile_version,
    intent_hash,
    input_hash               // Only if static_fields only; dynamic inputs bypass cache
))
```

### 6.2 Cache Hit Conditions

A cached Plan is valid when:

1. All components of the cache key match exactly
2. The cached Plan was compiled within the cache TTL (default: 5 minutes)
3. None of the referenced Capability Manifests have been updated or deprecated since caching
4. None of the referenced Rules have been updated since caching

### 6.3 Cache Invalidation Triggers

| Event | Action |
|-------|--------|
| Workflow version published | Invalidate all Plans for that `workflow_id` |
| Rule version published | Invalidate all Plans referencing that `rule_id` |
| Profile version published | Invalidate all Plans referencing that `profile_id` |
| Capability Manifest deprecated | Invalidate all Plans with that `capability_id` binding |
| Cache TTL expired (5 min) | Invalidate and recompute |

### 6.4 No-Cache Bypass

Certain executions must bypass caching:

- Profile specifies `cache_policy: "never"`
- Intent specifies `freshness: "always"` (user explicitly requests fresh data)
- Execution is the first run after a Rule Governance change affecting the Workflow

### 6.5 Planner Caching and Statelessness

The Planner does **not** hold a cache in its own memory. Plan caching is the **Registry's responsibility** (Metadata Plane). The Planner:

1. Computes the `cache_key`
2. Sends a `PlanCacheLookup` request to the Registry
3. Either receives a cached Plan or a cache miss
4. On cache miss: runs the full pipeline and sends the result to the Registry for caching

This preserves the Planner's statelessness (Constitution Article 1).

---

## 7. Error Model

### 7.1 Compilation Errors

| Error Condition | Error Code | Pass | Recovery |
|----------------|------------|------|----------|
| Invalid Workflow YAML | `ParseError` | Pass 1 | Report to user; do not proceed |
| Non-existent capability type | `CapabilityTypeNotFound` | Pass 6 | Report with available types |
| No capability matches requirements | `NoCapabilityMatch` | Pass 6 | Report; suggest requirement relaxation |
| Cycle detected in DAG | `CyclicDependency` | Pass 2 | Report; abort compilation |
| Budget exceeded (hard cap) | `BudgetExceeded` | Pass 7 | Report; abort; suggest Profile change |
| Replan max exceeded | `ReplanRefused` | §5.4 | Report; Execution fails |

### 7.2 Warning Conditions

| Condition | Pass | Action |
|-----------|------|--------|
| Budget warning (approaching cap) | Pass 7 | Attach warning to Plan; proceed |
| No preferred model available | Pass 6 | Use best available; note in Plan |
| Capability quality below Profile recommendation | Pass 6 | Use best match; note in Plan |
| Cache lookup failed (non-critical) | §6.5 | Recompile; note degraded performance |

---

## 8. Planner API

The Planner exposes a minimal API consumed by the Execution Engine:

```json
// Input (from Execution Engine when an Execution Plan is needed)
{
  "workflow_ref": "wf://finance/stock-research@2.1.0",
  "intent": { /* Intent from Intent Engine */ },
  "input": { /* parsed Goal input */ },
  "profile_ref": "profile://finance/deep@1.0.0",
  "rules_override": null,  // Optional: specific Rule versions to apply
  "execution_id": "exec://finance/...",
  "cache_policy": "default"  // "default" | "never" | "force_recompile"
}

// Output
{
  "plan_id": "plan://exec_001",
  "compilation": {
    "status": "success",
    "passes_completed": 8,
    "total_duration_ms": 120,
    "cache_hit": false
  },
  "execution_plan": { /* RFC-0100 §10 format */ }
}
```

---

## 9. Compliance

Any implementation claiming Agent OS Planner compatibility **must**:

1. Implement the 8-pass compiler pipeline defined in §3 (all passes, in order)
2. Implement the Capability Negotiation protocol defined in §4
3. Implement the Replan protocol defined in §5
4. Support Plan caching via Registry as defined in §6 (Planner itself must not cache)
5. Produce Execution Plans conforming to RFC-0100 §10 format

---

## 10. Open Questions

1. **Incremental compilation** — on replan, should the Planner recompute only the affected subgraph, or the entire remaining graph?
2. **Parallel compilation** — multiple compilation requests for different executions should be safe (Planner is stateless). But should there be a concurrency limit?
3. **Condition DSL extension** — should future versions support runtime variables (not just compile-time) for adaptive Workflows?
4. **Cache scope** — should Plan caching cross execution sessions, or only within a session?

---

## 11. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.3 | Workflow entity |
| SPEC-0000 §3.7 | Capability Manifest entity |
| SPEC-0000 §3.8 | Capability Requirement entity |
| SPEC-0000 §3.16 | Execution Plan entity (Planner output format) |
| RFC-0001 §3 | Task State Machine (Replan trigger) |
| RFC-0001 §4.3 | Replan Decision |
| RFC-0001 §8.4 | Replan loops |
| RFC-0100 §6 | Capability Requirements schema |
| RFC-0100 §7 | Maximal → Minimal Graph compilation |
| RFC-0100 §10 | Execution Plan JSON format |
| ADR-0001 | Event Sourcing pattern |
| Constitution Article 1 | Kernel must be stateless |
| Constitution Article 9 | Planner optimizes at compile time only (v1) |
