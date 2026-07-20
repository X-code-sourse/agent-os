# RFC-0100: Workflow Specification

**Status:** Draft
**Type:** Control Plane RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0001 v1.0, RFC-0002
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Workflow Specification** — the syntax, semantics, and compilation model for Workflows in Agent OS. A Workflow is a declarative Graph describing Task dependencies and execution order. It is the primary mechanism for domain experts to encode professional SOPs.

---

## 2. Motivation

A Workflow is not code. It is not a prompt. It is a **declarative Graph** authored by domain experts who know the right sequence of operations but should not need to know about models, capabilities, or infrastructure.

Without a formal specification, Workflows become ad-hoc YAML files with inconsistent schemas, making them impossible to validate, version, or share across the ecosystem.

---

## 3. Workflow Structure

### 3.1 Top-Level Schema

```yaml
# Every Workflow is a single YAML document with the following top-level fields:
workflow_id: string        # wf://<namespace>/<name>
version: semver            # MAJOR.MINOR.PATCH
description: string        # Human-readable description

stages: Stage[]             # Ordered list of stage definitions (the DAG)

# Optional
metadata:
  author: string
  tags: string[]
  category: string
  icon: string
  documentation_url: string

output_schema: JSONSchema  # Expected output format
defaults:                  # Default values applied to all stages
  max_retries: int
  retry_policy: RetryPolicy
  quality_threshold: float
```

### 3.2 Stage Definition

```yaml
stages:
  - id: string                    # Unique within this Workflow. Used in depends_on.
    type: stage_type              # See §3.3
    description: string

    # Dependency
    depends_on: string[]          # Stage IDs this stage depends on (empty = root)

    # Condition (see §5)
    condition: string             # Expression evaluated by Planner at compile time

    # Capability Requirement (see §6)
    requirements:
      capability_type: string
      domain: string[]
      language: string
      quality_min: float          # Optional
      cost_max: float             # Optional
      latency_max_ms: int         # Optional
      required_features: string[] # Optional

    # Stage-specific configuration
    config:
      input_template: JSON        # Template for the input sent to the Capability
      output_mapping: JSON        # How to map outputs to downstream stage inputs

    # Retry (overrides workflow defaults if set)
    max_retries: int              # Optional
    retry_policy: RetryPolicy     # Optional
    replan_allowed: boolean       # Default: false
```

### 3.3 Stage Types

| Stage Type | Description | Incoming Edges | Outgoing Edges |
|------------|-------------|----------------|----------------|
| `task_node` | A single executable Task. The most common type. | 1+ | 1+ |
| `parallel_gate` | Fan-out: all outgoing stages run in parallel. | 1 | N |
| `join_gate` | Fan-in: waits for all incoming stages to complete before proceeding. | N | 1 |
| `exclusive_gate` | Decision point: exactly one outgoing path is taken based on condition. | 1 | N |
| `inline_subworkflow` | References another Workflow as a sub-stage. The referenced Workflow is inlined at compile time. | 1 | 1 |

---

## 4. Dependency Semantics

### 4.1 DAG Definition

A Workflow defines a **Directed Acyclic Graph (DAG)** where:

- **Nodes** are stages
- **Edges** are defined by the `depends_on` field
- The graph MUST be acyclic (validated at registration time)
- The graph MAY have multiple roots (stages with empty `depends_on`)
- The graph MAY have multiple sinks (stages no other stage depends on)

### 4.2 Topological Order

The Planner MUST produce a topological ordering of the stages. Stages with no dependency edges between them MAY execute in any order (including parallel if the Execution Engine supports it).

### 4.3 Dependency Resolution

```
Stage A (root)
    │ depends_on: []
    │
    ├──► Stage B     depends_on: [A]
    │
    └──► Stage C     depends_on: [A]
              │
              ▼
         Stage D     depends_on: [B, C]
              │
              ▼
         Stage E     depends_on: [D]
```

In this graph:
- B and C execute after A completes (possibly in parallel)
- D executes only after BOTH B and C complete
- E executes after D completes

### 4.4 Data Flow Between Stages

Each stage's output is available to downstream stages via a **context object**. The context accumulates as the DAG executes:

```
Stage A output:
  { "company": "NVIDIA", "ticker": "NVDA" }

Stage B (depends_on: [A]) receives context:
  { "A": { "company": "NVIDIA", "ticker": "NVDA" },
    "current": StageB.input }

Stage D (depends_on: [B, C]) receives context:
  { "A": { ... },
    "B": { "news": [...] },
    "C": { "financials": {...} },
    "current": StageD.input }
```

---

## 5. Condition Expression DSL

### 5.1 Purpose

Conditions allow the Planner to **prune stages at compile time**, producing a Minimal Viable Graph from the Maximal Graph. Conditions are evaluated against the `Intent` (after Domain Detection) and the current `input`.

### 5.2 Expression Language

Conditions use a restricted expression language with no side effects:

```
expression     ::= conjunction ( "||" conjunction )* | "always" | "never"
conjunction    ::= comparison ( "&&" comparison )*
comparison     ::= path_expr operator value | "(" expression ")"
path_expr      ::= identifier ( "." identifier )*
operator       ::= "==" | "!=" | "in" | "not in" | ">" | "<" | ">=" | "<="
               | "contains" | "starts_with"
value          ::= string | number | boolean | "[" value ("," value)* "]"
identifier     ::= [a-zA-Z_][a-zA-Z0-9_]*
```

**Keywords:**
- `"always"` — always evaluate to true; no expression parse needed (optimization hint)
- `"never"` — always evaluate to false; stage is permanently pruned (for deprecation or debugging)

### 5.3 Available Context Variables

| Variable | Source | Example Values |
|----------|--------|----------------|
| `user_intent.domain` | Intent | `"finance"`, `"education"`, `"coding"` |
| `user_intent.task_type` | Intent | `"stock_research"`, `"homework_help"`, `"code_review"` |
| `user_intent.depth` | Intent | `"quick"`, `"financial"`, `"valuation"`, `"deep"` |
| `input.has_company` | Goal | `true`, `false` |
| `input.has_ticker` | Goal | `true`, `false` |
| `input.topic` | Goal | string (detected topic) |

### 5.4 Condition Examples

```yaml
# Always execute (no condition filter)
condition: "always"

# Execute only for deep research
condition: "user_intent.depth in ['financial', 'valuation', 'deep']"

# Execute only if input contains a company reference
condition: "input.has_company == true"

# Skip for quick queries
condition: "user_intent.depth != 'quick'"

# Execute only for finance domain
condition: "user_intent.domain == 'finance'"

# Complex: execute for finance stock research at financial depth or deeper
condition: "user_intent.domain == 'finance' && user_intent.depth in ['financial', 'valuation', 'deep']"
```

### 5.5 Compile-Time Evaluation Guarantee

Conditions are evaluated **exactly once** at compile time by the Planner. The resulting stage set is frozen in the Execution Plan. This guarantees:

- Deterministic execution paths
- Stable DAG structure within a single Execution
- No runtime condition re-evaluation (v1; may change with dynamic DAG in v2)

---

## 6. Capability Requirements

### 6.1 Purpose

A Capability Requirement declares **what** a stage needs without specifying **which** Capability implementation should fulfill it. The Metadata Registry resolves Requirements to Manifests via Capability Negotiation.

### 6.2 Requirement Schema

```yaml
requirements:
  capability_type: string       # Required. The type of capability needed.
                                # Examples: "research", "python", "browser", "writing", "search"

  domain: string[]              # Required. Domain expertise needed.
                                # Examples: ["finance", "sec_filing"], ["python", "data_science"]

  language: string              # Required. Primary language for the task.
                                # Examples: "en", "zh", "ja", "mixed"

  quality_min: float            # Optional (default: 0.7). Minimum acceptable quality score.
  cost_max: float               # Optional. Maximum cost per invocation in USD.
  latency_max_ms: int           # Optional. Maximum acceptable latency in milliseconds.

  required_features: string[]   # Optional. Specific features the Capability must support.
                                # Examples: ["citation", "source_attribution", "web_search", "file_upload"]
```

### 6.3 Matching Rules

A Capability Manifest matches a Requirement when:

1. `manifest.type == requirement.capability_type`
2. `requirement.domain` is a SUBSET of `manifest.supported_domains` (every required domain must be supported)
3. `requirement.language` is in `manifest.supported_languages`
4. `manifest.quality_score >= requirement.quality_min` (if specified)
5. `manifest.cost_per_call <= requirement.cost_max` (if specified)
6. `manifest.avg_latency_ms <= requirement.latency_max_ms` (if specified)
7. All entries in `required_features` are present in the Manifest

### 6.4 Multiple Matches

If multiple Manifests match a Requirement, the Registry returns all matches ranked by:
1. Quality score (descending)
2. Cost (ascending, tiebreaker)
3. Latency (ascending, final tiebreaker)

The Execution Engine selects the final Capability based on Profile preferences.

---

## 7. Maximal Graph vs Minimal Viable Graph

### 7.1 Maximal Graph

The **Maximal Graph** is the Workflow as authored by the domain expert — all stages with all conditions declared. It represents the full procedural knowledge of the domain.

Example (Finance research, maximal):

```
company_identification
    │
    ├──► news_analysis
    │         │
    │         ├──► peer_comparison ──┐
    │         │                      │
    ├──► financial_analysis           ├──► summary_report
    │         │                      │
    │         ├──► valuation_analysis┘
    │         │
    │         └──► risk_assessment
```

### 7.2 Minimal Viable Graph

The **Minimal Viable Graph** is the result of Planner compilation — the Maximal Graph with stages pruned according to their conditions.

Example (User asks "NVIDIA stock price" — quick query):

```
company_identification → news_analysis → summary_report
```

Example (User asks "Should I buy NVIDIA?" — full deep analysis):

```
company_identification
    │
    ├──► news_analysis ─────────┐
    │                            │
    ├──► financial_analysis ─────├──► peer_comparison ──┐
    │         │                  │                       │
    │         ├──► valuation_analysis────────────────────├──► summary_report
    │         │                                          │
    │         └──► risk_assessment ──────────────────────┘
```

### 7.3 Pruning Rules

The Planner prunes stages as follows:

1. Evaluate each stage's `condition` expression against the Intent + input
2. If `condition == "always"` or `condition` evaluates to true: **keep**
3. If `condition` evaluates to false: **remove**
4. After removal, check all downstream stages:
   - If a downstream stage's `depends_on` becomes empty AND its condition does not independently evaluate to true: **remove** (no input to process)
   - If a downstream stage has remaining dependencies: **keep** (will receive partial context)
5. If a `parallel_gate` or `join_gate` has zero remaining children, it is replaced with a pass-through

### 7.4 Planner Output: Execution Plan

The Planner compiles the Minimal Viable Graph into an **Execution Plan**:

```json
{
  "plan_id": "plan://exec_001",
  "workflow": { "id": "wf://finance/stock-research", "version": "2.1.0" },
  "compiled_at": "2026-07-19T10:00:02Z",
  "stages": [
    {
      "stage_id": "company_identification",
      "type": "task_node",
      "depends_on": [],
      "requirements": { "capability_type": "research", "domain": ["general"], "language": "en" },
      "config": { "input_template": { "query": "{goal.text}" } },
      "max_retries": 2,
      "replan_allowed": false
    },
    {
      "stage_id": "news_analysis",
      "type": "task_node",
      "depends_on": ["company_identification"],
      "requirements": { "capability_type": "research", "domain": ["finance", "news"], "language": "en" },
      "max_retries": 2,
      "replan_allowed": false
    }
  ],
  "pruned_stages": [
    "financial_analysis",
    "valuation_analysis",
    "risk_assessment",
    "peer_comparison"
  ],
  "pruning_reasons": {
    "financial_analysis": "condition 'user_intent.depth in [\"financial\",\"valuation\",\"deep\"]' evaluated false (depth=quick)",
    "valuation_analysis": "condition evaluated false",
    "risk_assessment": "condition evaluated false",
    "peer_comparison": "condition evaluated false"
  }
}
```

---

## 8. Workflow Versioning

### 8.1 Semantic Versioning

Workflow versions follow SemVer 2.0.0:

| Increment | When | Example |
|-----------|------|---------|
| MAJOR | Breaking change to stage structure, dependencies, or output schema | `1.0.0` → `2.0.0` |
| MINOR | Adding new stages, relaxing conditions, adding optional output fields | `1.0.0` → `1.1.0` |
| PATCH | Fixing description, metadata, default values (no behavioral change) | `1.0.0` → `1.0.1` |

### 8.2 Backward Compatibility

A Workflow version N+1 is backward-compatible with N if:

- Every stage ID present in N is also present in N+1 (same ID, same type, same dependencies)
- No stage has had its `condition` narrowed (a stage that was `always` can become conditioned; but a conditioned stage cannot become stricter)
- No output field has been removed
- No requirement has been made stricter (cost_max can only increase, quality_min can only decrease)

### 8.3 Registry Storage

Workflows are stored in the Metadata Registry under the `wf://<namespace>/<name>` key, with each version addressable as `wf://<namespace>/<name>@<version>`.

---

## 9. Workflow Validation

Every Workflow MUST pass validation before being registered:

| Check | Rule | Phase |
|-------|------|-------|
| Acyclicity | The dependency graph must contain no cycles | Registration |
| Stage ID uniqueness | All stage IDs in a Workflow must be unique | Registration |
| Dependency existence | Every entry in `depends_on` must reference an existing stage ID | Registration |
| Root existence | At least one stage must have empty `depends_on` (or be referenced transitively from a root) | Registration |
| Condition syntax | All condition expressions must parse according to §5.2 | Registration |
| Requirement completeness | All required fields of `requirements` (§6.2) must be present | Registration |
| Output schema validity | `output_schema` must be valid JSON Schema (if provided) | Registration |
| Version increment | New version must follow SemVer rules relative to previous (if any) | Registration |

---

## 10. Execution Plan Serialization (JSON)

The canonical serialization format for an Execution Plan (Planner output → Execution Engine input):

```json
{
  "plan_id": "plan://exec_001",
  "workflow_ref": "wf://finance/stock-research@2.1.0",
  "execution_id": "exec://finance/a1b2c3d4-...",
  "compiled_at": "2026-07-19T10:00:02.000Z",

  "profile_ref": "profile://finance/deep@1.0.0",

  "rules_applied": [
    { "id": "rule://finance/sec-filing@1.2.0", "scope": "global" }
  ],

  "stages": [
    {
      "stage_id": "company_identification",
      "type": "task_node",
      "depends_on": [],
      "requirements": { "capability_type": "research", "domain": ["general"], "language": "en" },
      "input": { "query": "research Nvidia stock for investment recommendation" },
      "config": {},
      "max_retries": 2,
      "replan_allowed": false
    }
  ],

  "pruning_log": {
    "pruned": ["financial_analysis", "valuation_analysis", "risk_assessment", "peer_comparison"],
    "reasons": {
      "financial_analysis": "depth=quick, condition requires depth in [financial,valuation,deep]"
    }
  }
}
```

---

## 11. Compliance

Any implementation claiming Agent OS Workflow compatibility **must**:

1. Parse and validate Workflow YAML according to the schema in §3
2. Implement the stage type system defined in §3.3 (all 5 types)
3. Implement the dependency resolution semantics defined in §4
4. Implement the condition expression DSL defined in §5
5. Implement Capability Requirement matching as defined in §6
6. Implement the Maximal → Minimal Graph compilation algorithm defined in §7
7. Produce Execution Plans in the format defined in §10
8. Enforce the validation rules defined in §9 at registration time
9. Support semver-based Workflow versioning as defined in §8

---

## 12. Open Questions

1. **Inline subworkflows** — how deep can subworkflow nesting go? What happens when a subworkflow is versioned independently?
2. **Dynamic conditions** — should v2 support runtime re-evaluation of conditions (enabling truly adaptive workflows)?
3. **Error recovery in parallel gates** — if one branch of a parallel_gate fails, should the other branches be cancelled?
4. **Execution Plan caching** — identical inputs with identical Profiles could reuse cached plans. Cache invalidation rules needed.

---

## 13. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.3 | Workflow entity definition |
| SPEC-0000 §3.4 | Task entity definition |
| SPEC-0000 §4 | Relationship Graph |
| SPEC-0000 §5 | Identity Convention |
| RFC-0001 §3 | Task State Machine |
| RFC-0001 §8.1 | DAG with Skipped Tasks semantics |
| RFC-0002 | Architectural Constitution (Article 5: Workflow describes flow only) |
| Constitution Article 5 | Workflow Describes Flow Only |
| Constitution Article 8 | Workflow Depends on Capability Requirements, Not Implementations |
