# RFC-0104: Rule Resolution

**Status:** Draft
**Type:** Control Plane RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0001 v1.0, RFC-0002, RFC-0100 v1.0, RFC-0101 v1.0, RFC-0200 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Rule Resolution** subsystem — how Rules (SPEC-0000 §3.5) are matched to Workflows and Tasks, how their constraints are evaluated, how multiple Rules compose without overwriting each other, how versions are locked in Execution Plans, and how Rule conflicts are resolved. Rule Resolution operates at two points: **compile time** (Planner Pass 3: Rule Injection) and **runtime** (Reviewer constraint evaluation).

---

## 2. Motivation

Rules exist in three places in the existing RFCs, but none defines how Rules actually work:

- **RFC-0101 Pass 3** says "Rule Manager provides applicable rules" — but doesn't define how
- **RFC-0001 §7** says "Local Reviewer evaluates constraints" — but doesn't define how constraint expressions are evaluated
- **RFC-0200 §6** says "rules may constrain Capability behavior" — but doesn't define how

Without a formal Rule Resolution specification:

- Every Rule Manager implementation invents its own scope matching
- Constraint expressions have no evaluation semantics
- Rule composition is undefined — two Rules may silently conflict or double-apply
- Execution Plan version locking is ad-hoc
- The Git-like governance model (propose → review → experiment → merge) cannot be implemented

---

## 3. Rule Structure (From SPEC-0000)

### 3.1 Rule Schema (Reference)

```yaml
rule_id: rule://<namespace>/<name>
version: semver
description: string

scope:                       # What this Rule applies to (see §4)
  workflows: string[]        # Glob patterns matching workflow_ids
  task_types: string[]       # Filter by task type
  domains: string[]          # Filter by domain

constraints:                 # What this Rule enforces (see §5)
  - id: string
    description: string
    field: string            # JSON path to the constrained value
    condition: string        # Constraint expression
    severity: required | warning
    on_violation: string     # retry | skip | fail | note

governance:                  # Governance metadata (see §8)
  status: draft | review | experiment | approved | superseded
  approved_by: string
  approved_at: ISO 8601
  experiment:                # Present only when status == experiment
    traffic_share: float     # 0.0–1.0: fraction of executions this applies to
    metric: string           # Success metric to compare
    duration: string         # Experiment duration
```

### 3.2 Rule Identity

Rules are identified by `rule_id@version` (SPEC-0000 §5). The version is **mandatory** in every Rule reference — no Rule reference is valid without a pinned version. This ensures deterministic Execution Plans.

---

## 4. Scope Matching

### 4.1 Matching Algorithm

Scope matching determines whether a Rule applies to a given Workflow and Task. It operates at **compile time** (Planner Pass 3) and the result is frozen in the Execution Plan.

```
def resolve_rules(workflow_ref, stage, intent):
    matching_rules = []

    for rule in rule_registry.all_active():
        # Step 1: Workflow scope filter
        if not any(glob_match(workflow_ref, pattern)
                   for pattern in rule.scope.workflows):
            continue  # Rule does not apply to this Workflow

        # Step 2: Task type filter (if specified)
        if rule.scope.task_types:
            if stage.requirements.capability_type not in rule.scope.task_types:
                continue  # Rule does not apply to this Task type

        # Step 3: Domain filter (if specified)
        if rule.scope.domains:
            if not any(domain in rule.scope.domains
                       for domain in stage.requirements.domain):
                continue  # Rule does not apply to this domain

        # Step 4: Governance status filter
        if rule.governance.status not in ["approved", "experiment"]:
            continue  # Only active rules are injected at compile time

        # Step 5: Experiment sampling (see §8.2)
        if rule.governance.status == "experiment":
            if not sample_experiment(rule):
                continue  # This execution falls in the control group

        matching_rules.append(rule)

    return matching_rules
```

### 4.2 Glob Matching

Workflow scope patterns support glob matching:

| Pattern | Matches | Does Not Match |
|---------|---------|----------------|
| `wf://finance/*` | `wf://finance/stock-research` | `wf://education/` |
| `wf://*/stock-*` | `wf://finance/stock-research` | `wf://finance/etf-analysis` |
| `wf://finance/**` | `wf://finance/deep/credit-risk` | `wf://technology/` |
| `*` | All workflows | — |

### 4.3 Scope Precedence

A more specific scope wins over a less specific one:

```
Rule A: scope.workflows = ["wf://finance/*"]        (general)
Rule B: scope.workflows = ["wf://finance/stock-*"]   (specific)

Both match wf://finance/stock-research.
→ Rule B has higher specificity (longer glob match)
→ More specific Rule's constraints are applied FIRST
→ General Rule's constraints are applied SECOND (as fallback)
```

**Specificity rule:** the pattern with the most non-wildcard characters wins.

---

## 5. Constraint Evaluation

### 5.1 Constraint Expression Language

Each constraint in a Rule uses a restricted expression language evaluated against the Task's output (or input, depending on the constraint). The expression language is identical to the Workflow condition DSL (RFC-0100 §5.2) with one addition: the `count` aggregate function.

```
expression      ::= conjunction ( "||" conjunction )* | "always" | "never"
conjunction     ::= comparison ( "&&" comparison )*
comparison      ::= path_expr operator value | "(" expression ")"
                  | aggregate "(" path_expr ")" operator int_value
path_expr       ::= identifier ( "." identifier )*
operator        ::= "==" | "!=" | "in" | "not in" | ">" | "<" | ">=" | "<="
                  | "contains" | "starts_with"
value           ::= string | number | boolean | "[" value ("," value)* "]"
aggregate       ::= "count" | "unique" | "sum"
identifier      ::= [a-zA-Z_][a-zA-Z0-9_]*
int_value       ::= [0-9]+
```

**Aggregate functions (constraint-specific):**

| Function | Applies To | Example |
|----------|-----------|---------|
| `count(path)` | Array fields | `count(output.sources) >= 5` — at least 5 sources |
| `unique(path)` | Array of objects | `unique(output.sources.type) >= 3` — at least 3 unique source types |
| `sum(path)` | Array of numbers | `sum(output.metrics.confidence_scores) / count(output.metrics) >= 0.8` |

### 5.2 Evaluation Context

Constraints are evaluated against a **context object** that varies by evaluation point:

| Evaluation Point | Context Available | Example |
|-----------------|-------------------|---------|
| Compile time (RFC-0101 Pass 3) | Intent, Workflow metadata, stage requirements | `stage.requirements.domain contains "sec_filing"` |
| Runtime — Local Reviewer | Task input, Task output, Capability metrics | `count(output.sources) >= 5` |
| Runtime — Global Reviewer | All Task outputs, Execution metadata | `unique(all_outputs.sources.type) >= 3` |

### 5.3 Evaluation Result

```json
{
  "constraint_id": "sec-filing/v1.2.0#primary_source",
  "rule_id": "rule://finance/sec-filing@1.2.0",
  "evaluated_at": "compile_time",
  "result": "pass",
  "severity": "required",
  "expression": "count(output.sources[type='sec']) >= 1",
  "evaluated_on": {
    "task_type": "research",
    "domain": ["finance", "sec_filing"]
  }
}
```

### 5.4 Severity Handling

| Severity | Pass | Fail |
|----------|------|------|
| `required` | No action | Task fails review → retry or fail (RFC-0001 §4.1) |
| `warning` | No action | Task passes with `CompletedWithWarning`; warning recorded in output |
| `info` | No action | Pass/fail is logged but does not affect Task outcome |

---

## 6. Rule Composition

### 6.1 Composition Principle: Combination, Not Fusion

From the Agent OS architecture: **Rules compose by combination, not by modification.** Each Rule contributes its own constraints without modifying or overriding other Rules.

```
Applied Rules:
  Rule A: { constraint_1: "count(sources) >= 5", constraint_2: "sources contains 'sec'" }
  Rule B: { constraint_3: "count(sources) >= 3", constraint_4: "confidence >= 0.8" }

Final Constraint Set (union):
  { constraint_1: required, constraint_2: required, constraint_3: warning, constraint_4: required }
```

**No Rule modifies another Rule's constraint.** All rules are applied independently.

### 6.2 De-duplication

If two Rules define the same `constraint_id`:

```
Rule A v1: { constraint_id: "source_count", condition: "count(sources) >= 5", severity: "required" }
Rule B v2: { constraint_id: "source_count", condition: "count(sources) >= 3", severity: "warning" }

Resolution: The higher-versioned Rule wins for that constraint_id.
→ Rule B (v2 > v1) applies: source_count >= 3, severity: warning
```

De-duplication uses `constraint_id` as the key, not the Rule ID. This allows a newer Rule to intentionally supersede an older Rule's specific constraint without affecting other constraints.

### 6.3 Conflict Detection

Conflicts are detected when two Rules with the same `constraint_id` have conditions that cannot both be satisfied:

```python
def detect_conflict(constraint_a, constraint_b):
    """Returns True if the two constraints are logically contradictory."""
    if constraint_a.condition == "count(sources) >= 5" and \
       constraint_b.condition == "count(sources) <= 2":
        return True, "Cannot require at least 5 sources and at most 2 sources"
    return False, None
```

Detected conflicts are:
1. **Logged** in the Execution Plan metadata
2. **Flagged** to Loop (Learning Engine) for governance attention
3. **Resolved** at runtime by the stricter constraint winning (higher `count`, lower `latency`, etc.)

---

## 7. Rule Version Locking

### 7.1 Locking in Execution Plans

Every Execution Plan records exactly which Rule versions were applied (RFC-0100 §10):

```json
{
  "rules_applied": [
    { "id": "rule://finance/sec-filing", "version": "1.2.0", "scope": "global" },
    { "id": "rule://finance/risk-check", "version": "3.0.1", "scope": "stage:risk_assessment" }
  ]
}
```

This ensures **deterministic replay**: replaying the same Execution Record applies the same Rule versions, producing the same constraint evaluations.

### 7.2 Version Pinning at Compile Time

At compile time (RFC-0101 Pass 3), the Planner asks the Rule Manager for applicable Rules. The Rule Manager returns the **exact versions** that will be used:

```
Planner → Rule Manager: resolve(workflow_ref, stage, intent)
Rule Manager → Planner: [
    { rule_id: "rule://finance/sec-filing@1.2.0", constraints: [...] },
    { rule_id: "rule://finance/risk-check@3.0.1", constraints: [...] }
]
```

The Planner pins these versions in the Execution Plan. If a Rule version is updated after plan compilation, the running Execution is unaffected.

### 7.3 Version Resolution Strategy

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| `pinned` (default) | Use exactly the version specified in the Plan | Production executions |
| `latest` | Resolve to latest approved version at runtime | Development, testing |
| `range` | Use any version within `>=1.0.0, <2.0.0` | Gradually adopting non-breaking changes |

---

## 8. Governance Integration

### 8.1 Rule States

```
[Draft] ──► [Review] ──► [Approved] ──► [Superseded]
                │
                └──► [Experiment] ──► [Approved] (if successful)
                                       [Draft] (if failed)
```

| State | Meaning | Injected at Compile Time? | Evaluated at Runtime? |
|-------|---------|---------------------------|----------------------|
| `draft` | Being authored; not yet reviewed | No | No |
| `review` | Under human review | No | No |
| `experiment` | A/B testing with traffic share | Yes (sampled) | Yes |
| `approved` | Fully active | Yes | Yes |
| `superseded` | Replaced by a newer version | No (unless pinned) | No (unless pinned) |

### 8.2 Experiment Sampling

When a Rule is in `experiment` state:

```python
def sample_experiment(rule, execution_id):
    """Deterministically assign this execution to treatment or control."""
    hash_input = f"{rule.rule_id}@{rule.version}:{execution_id}"
    bucket = hash(hash_input) % 100  # 0–99
    treatment_threshold = int(rule.governance.experiment.traffic_share * 100)
    return bucket < treatment_threshold
```

- **Treatment group:** The Rule's constraints are injected and evaluated
- **Control group:** The Rule is skipped entirely (no constraints)
- Assignment is **deterministic** (based on `execution_id` hash) — replay produces the same assignment
- The experiment metric (e.g., output quality, execution cost, user satisfaction) is tracked by the Evaluation Engine

### 8.3 Rule Lifecycle Events

```json
// Published when a Rule transitions state
{
  "event_type": "Rule:StatusChanged",
  "payload": {
    "rule_id": "rule://finance/sec-filing",
    "from_version": "1.1.0",
    "to_version": "1.2.0",
    "from_status": "approved",
    "to_status": "approved",
    "change": "Added minimum quarters as warning constraint"
  }
}

// Published when an experiment concludes
{
  "event_type": "Rule:ExperimentCompleted",
  "payload": {
    "rule_id": "rule://finance/sec-filing",
    "version": "1.3.0-experiment.1",
    "traffic_share": 0.10,
    "treatment_group": {
      "executions": 150,
      "avg_quality": 0.91,
      "avg_cost": 0.45
    },
    "control_group": {
      "executions": 1350,
      "avg_quality": 0.88,
      "avg_cost": 0.50
    },
    "improvement": {
      "quality": "+0.03",
      "cost": "-10%"
    },
    "recommendation": "promote_to_approved"
  }
}
```

---

## 9. Rule Injection in the Compiler Pipeline

Rule Resolution operates at two points in the Planner pipeline (RFC-0101 §3):

### 9.1 Pass 3: Rule Injection (Compile Time)

```
Input:  DAG (maximal graph) + Intent
        Rule Manager provides rules matching scope

Process:
    For each stage in DAG:
        matching_rules = resolve_rules(workflow_ref, stage, intent)
        For each rule in matching_rules:
            For each constraint in rule.constraints:
                Evaluate constraint at compile time if possible
                    (constraints on Intent, Workflow metadata)
                Attach unevaluated constraints to stage metadata
                    (constraints on Task input/output — evaluated at runtime)

Output: DAG with per-stage constraint annotations
        Plan records: rules_applied = [{ id, version }]
```

### 9.2 Pass 3.5: Constraint Simplification (Compile Time)

After Rule Injection, the Planner may simplify constraints:

```
Rule: "if stage.domain contains 'sec_filing', require output.sources contains 'sec'"

If stage.domain == ['finance', 'sec_filing']:
    → The condition is always true at compile time
    → Simplify to unconditional constraint:
      "require output.sources contains 'sec'"
```

This reduces the work the Local Reviewer needs to do at runtime.

### 9.3 Runtime Evaluation (Local Reviewer)

At runtime (RFC-0001 §7.1), the Local Reviewer evaluates the remaining (non-compile-time-reducible) constraints against the Task's actual output:

```
Task produces output
    │
Local Reviewer receives:
    ├─ Task input + output
    ├─ Stage constraints (from Plan's rules_applied)
    └─ Capability metrics (from RFC-0200 invocation)
    │
    For each constraint:
        Evaluate condition expression against output
        Result: pass / warning / fail
    │
    Return: { result, score, constraint_results[] }
```

---

## 10. Compliance

Any implementation claiming Agent OS Rule Resolution compatibility **must**:

1. Implement scope matching as defined in §4 (glob patterns, specificity rules)
2. Implement constraint evaluation as defined in §5 (expression language, severity handling)
3. Implement Rule composition as defined in §6 (combination, de-duplication, conflict detection)
4. Implement Rule version locking as defined in §7 (pinning in Execution Plans)
5. Implement governance states as defined in §8 (draft → review → experiment → approved → superseded)
6. Implement experiment sampling as defined in §8.2
7. Publish Rule lifecycle events as defined in §8.3
8. Support both compile-time injection (RFC-0101 Pass 3) and runtime evaluation (Local Reviewer)

---

## 11. Open Questions

1. **Rule hot-reload** — when an approved Rule is updated, should in-flight Executions be re-evaluated or should they finish with the old version? (Current answer: they finish with the pinned version from the Plan)
2. **Cross-Workflow Rules** — should Rules be able to span multiple Workflows (e.g., a global compliance Rule constraining all finance Workflows)?
3. **Rule priority override** — should a Profile be able to explicitly override or disable a specific Rule?
4. **Constraint expression extension** — should constraint expressions support cross-stage references (e.g., "output of stage A must be consistent with output of stage B")?

---

## 12. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.5 | Rule entity definition |
| SPEC-0000 §3.6 | Profile entity (may override Rules) |
| RFC-0001 §4.1 | Execution Result Semantics (severity → result mapping) |
| RFC-0001 §7.1 | Local Reviewer (runtime constraint evaluation) |
| RFC-0001 §7.2 | Global Reviewer (cross-stage constraint evaluation) |
| RFC-0100 §5.2 | Condition Expression DSL (shared language with constraints) |
| RFC-0101 §3, Pass 3 | Rule Injection (compile-time scope matching) |
| RFC-0101 §3, Pass 3.5 | Constraint Simplification |
| RFC-0200 §6 | Contract Validation (Rule constraints on Capability output) |
| RFC-0201 §4.2 | Domain declarations (used in scope matching) |
| ADR-0001 | Event Sourcing (Rule lifecycle events) |
| Constitution Article 6 | Rule describes constraint only |
| Constitution Article 10 | Loop has suggestion rights only |
