# RFC-0600: Loop Learning

**Status:** Draft
**Type:** Evolution RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0001 v1.0, RFC-0002, RFC-0104 v1.0, RFC-0201 v1.0, RFC-0501 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Loop Learning subsystem** — the offline batch-processing pipeline that analyzes execution data, detects patterns, and generates suggestions for system improvement. The Loop operates under Constitution Article 10: **it has suggestion rights only**. All suggestions pass through Human Governance before taking effect.

The Loop consists of four sub-engines coordinated by a Loop Manager:

- **Learning Engine** — detects patterns in execution data
- **Optimization Engine** — generates proposals for cost, latency, or quality improvements
- **Evaluation Engine** — analyzes A/B experiment results
- **Analytics Engine** — produces aggregate metrics and trend reports

---

## 2. Motivation

Six existing RFCs contain references to Loop functionality that was left undefined:

- RFC-0001 §8.4: "replan loops are flagged for Loop analysis"
- RFC-0201 §4.5: "Loop-verified values take precedence" (over self-declared Manifest performance)
- RFC-0104 §6.3: "conflicts flagged to Loop"
- RFC-0104 §8.3: "experiment data feeds Loop analysis"
- RFC-0501 §3: "Loop consumes Observability data"
- Constitution Article 10: "Loop has suggestion rights only"

Without RFC-0600, none of these references can be implemented. The Loop is cargo-culted as "the thing that learns" without having a defined architecture.

---

## 3. Architecture: Offline Batch Pipeline

The Loop runs as an **offline batch process** (v1). It does not react to Events in real time. Instead, it runs on a schedule (default: nightly) against accumulated data.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        LOOP MANAGER                                 │
│                                                                     │
│  Scheduler (cron: daily)                                            │
│       │                                                             │
│       ▼                                                             │
│  DataCollector                                                      │
│       │                                                             │
│       ├── from Event Store: execution data (last 24h)              │
│       ├── from Observability: traces, costs, metrics (RFC-0501)    │
│       ├── from Registry: Manifest perf, Rule state (RFC-0300)      │
│       └── from Experiment Store: A/B results (RFC-0104)            │
│       │                                                             │
│       ▼                                                             │
│  ┌───────────┬────────────┬──────────────┬──────────────┐          │
│  │ Learning  │Optimization│  Evaluation   │  Analytics   │          │
│  │  Engine   │   Engine   │    Engine     │   Engine     │          │
│  └───────────┴────────────┴──────────────┴──────────────┘          │
│       │           │             │              │                    │
│       ▼           ▼             ▼              ▼                    │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │                  Suggestion Queue                         │      │
│  │  (outputs: PatternReport, OptimizationProposal,           │      │
│  │   ExperimentResult, AnalyticsReport)                      │      │
│  └──────────────────────────────────────────────────────────┘      │
│       │                                                             │
│       ▼                                                             │
│  Human Governance Review                                            │
│       │                                                             │
│       ├── Approve → Rule Manager / Registry applies                 │
│       ├── Experiment → Rule Manager sets experiment state          │
│       └── Reject → Close with ADR note                             │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.1 Why Offline (v1)

| Aspect | Online (v2) | Offline (v1, this RFC) |
|--------|-------------|------------------------|
| Response time | Real-time (seconds) | Batch (hours) |
| Data volume | Single execution | Thousands of executions |
| Decision risk | High (auto-pilot could degrade) | Low (reviewed before applying) |
| Complexity | High (streaming, state mgmt) | Low (batch, deterministic) |
| Observability dependency | Minimal | Full (all data available) |

---

## 4. Loop Manager

### 4.1 Responsibilities

The Loop Manager is the coordinator. It does not perform analysis itself.

```
LoopManager
├── schedule(run_interval, data_sources)  — when to run, what data to collect
├── collect()  — pull data from Event Store, Observability, Registry
├── dispatch() — send collected data to each sub-engine
├── gather()   — collect outputs from sub-engines
├── deduplicate() — merge duplicate suggestions
├── prioritize() — rank suggestions by estimated impact
└── publish() — write suggestions to the Suggestion Queue
```

### 4.2 Schedule

Default schedule: **daily at 02:00** (configurable via Profile or system config).

```json
{
  "loop_schedule": {
    "cron": "0 2 * * *",
    "timezone": "UTC",
    "data_window_hours": 24,
    "enabled_engines": ["learning", "optimization", "evaluation", "analytics"]
  }
}
```

### 4.3 Data Collection Scope

Each run collects:

| Data Source | Contents | Volume (per day) |
|-------------|----------|------------------|
| Event Store | All Execution lifecycle events (Task:Completed, Task:Failed, Execution:Completed, etc.) | 10K–100K events |
| Observability | Execution Traces (§4), Cost Records (§5), Metrics (§7) | 1K–10K traces |
| Registry | All active Manifests, Rules, Workflows (for reference) | < 1K |
| Experiment Store | Completed experiment results (RFC-0104 §8.3) | < 10 |

---

## 5. Learning Engine

### 5.1 Purpose

The Learning Engine detects **patterns** in execution data. It does not suggest changes — it identifies what *exists*.

### 5.2 Pattern Types

| Pattern Type | Description | Example |
|-------------|-------------|---------|
| `cost_anomaly` | Execution cost significantly deviates from historical norm | "Workflow X cost $2.50 avg last week, $5.00 avg today" |
| `quality_drop` | Review scores declining for a specific Workflow or Capability | "Research-v2 quality dropped from 0.92 to 0.85 over 3 days" |
| `latency_regression` | Execution latency increasing | "Planner compile time increased from 2s to 8s" |
| `failure_cluster` | Non-random failure pattern | "60% of failures occur in the same Workflow stage" |
| `replan_loop` | Recurring replan cycles for the same failure mode | "3 replans in 24h for capability binding failure" |
| `capability_drift` | Manifest-declared performance diverging from actual | "Manifest claims 0.94 quality; actual avg is 0.88" |
| `rule_conflict` | Two Rules consistently producing conflicting evaluations | "SEC-filing and Risk-check Rules conflict on 40% of Executions" |
| `workflow_stall` | Workflow stages that are never executed (always pruned) | "valuation_analysis never runs — condition too narrow" |

### 5.3 Pattern Report Output

```json
{
  "report_id": "pattern://learning/2026-07-19/capability-001",
  "engine": "learning",
  "generated_at": "2026-07-19T02:15:00Z",
  "data_window": { "from": "2026-07-18T02:00:00Z", "to": "2026-07-19T02:00:00Z" },

  "patterns": [
    {
      "type": "capability_drift",
      "confidence": 0.87,
      "severity": "warning",
      "summary": "cap://nous-research/research-v2@2.3.0 quality drift detected",
      "detail": "Manifest declares quality_score=0.94. Actual quality over 150 invocations: avg=0.88, p50=0.91, p10=0.72.",
      "evidence": {
        "executions_analyzed": 150,
        "declared_quality": 0.94,
        "actual_avg_quality": 0.88,
        "actual_p10_quality": 0.72,
        "trend": "declining (last 7 days: 0.92→0.90→0.88)"
      },
      "suggestion": {
        "type": "manifest_performance_update",
        "target": "cap://nous-research/research-v2",
        "proposed_change": { "quality_score": 0.88 },
        "estimated_impact": "Negotiation ranking will adjust; lower-ranked Capabilities may be selected more often"
      }
    }
  ],

  "metrics": {
    "executions_analyzed": 450,
    "patterns_found": 3,
    "execution_time_ms": 45000
  }
}
```

---

## 6. Optimization Engine

### 6.1 Purpose

The Optimization Engine consumes patterns from the Learning Engine and generates **actionable proposals** for system improvement.

### 6.2 Proposal Types

| Proposal Type | Description | Example |
|---------------|-------------|---------|
| `model_switch` | Replace a model with a cheaper or better alternative | "Research-v2 using claude-sonnet-4; gpt-4o gives same quality at 60% cost" |
| `capability_rebind` | Switch to a different Capability for a Workflow stage | "For finance/stock-research stage news_analysis, research-lite achieves same quality at 25% cost" |
| `rule_relaxation` | Loosen an overly strict Rule constraint | "SEC-filing Rule requires 4 quarters; 2 quarters is sufficient for 95% of Executions" |
| `rule_tightening` | Tighten an insufficient Rule constraint | "No Rule requires source diversity; 30% of Executions cite only one source type" |
| `workflow_restructure` | Reorder stages, add/remove conditional paths | "peer_comparison stage is always pruned (condition never met); suggest removing or widening condition" |
| `cache_enable` | Enable Plan caching for a frequently compiled Workflow | "wf://finance/stock-research compiled 80 times today with identical Rules and Profile" |

### 6.3 Optimization Proposal Output

```json
{
  "proposal_id": "optimization://2026-07-19/model-003",
  "engine": "optimization",
  "generated_at": "2026-07-19T02:30:00Z",

  "proposals": [
    {
      "type": "model_switch",
      "priority": "high",
      "summary": "Switch research-v2 from claude-sonnet-4 to gpt-4o for news_analysis stages",
      "analysis": {
        "current_model": "claude-sonnet-4",
        "proposed_model": "gpt-4o",
        "stages_affected": ["news_analysis"],
        "workflows_affected": ["wf://finance/stock-research"],
        "estimated_savings": {
          "cost_per_invocation": { "current": 0.02, "proposed": 0.008, "savings_usd": 0.012 },
          "monthly_projected": { "current": 60.00, "proposed": 24.00, "savings_usd": 36.00 }
        },
        "quality_impact": {
          "current_avg": 0.91,
          "proposed_expected": 0.89,
          "degradation_risk": "low"
        },
        "evidence": {
          "executions_analyzed": 85,
          "confidence": 0.82
        }
      },
      "implementation": {
        "action": "update_profile",
        "target": "profile://finance/deep",
        "change": "Set capability_configs.research.preferred_models[1] = gpt-4o for stages matching news_analysis"
      }
    }
  ]
}
```

### 6.4 Optimization Constraints

The Optimization Engine must respect these **hard constraints** when generating proposals:

1. **Constitution Article 10**: Never generate a proposal that modifies a Rule, Workflow, or Configuration directly
2. **Quality floor**: A proposal must not reduce expected quality below `profile.quality_threshold`
3. **Minimum evidence**: A proposal requires at least 30 data points (executions) before being generated
4. **Non-regression validation**: A proposal that reduces cost must not increase expected failure rate by more than 5%

---

## 7. Evaluation Engine

### 7.1 Purpose

The Evaluation Engine analyzes the results of **A/B experiments** (RFC-0104 §8) and produces recommendations.

### 7.2 Experiment Analysis

```json
{
  "analysis_id": "evaluation://2026-07-19/experiment-001",
  "engine": "evaluation",
  "generated_at": "2026-07-19T02:45:00Z",

  "experiment": {
    "rule_id": "rule://finance/sec-filing",
    "version": "1.3.0-experiment.1",
    "traffic_share": 0.10,
    "duration_hours": 48,
    "completed_at": "2026-07-19T00:00:00Z"
  },

  "results": {
    "treatment": {
      "executions": 150,
      "avg_quality": 0.91,
      "avg_cost": 0.45,
      "failure_rate": 0.02
    },
    "control": {
      "executions": 1350,
      "avg_quality": 0.88,
      "avg_cost": 0.50,
      "failure_rate": 0.03
    },
    "improvement": {
      "quality": { "delta": "+0.03", "significant": true, "confidence": 0.95 },
      "cost": { "delta": "-10%", "significant": true, "confidence": 0.92 },
      "failure_rate": { "delta": "-1%", "significant": false, "confidence": 0.60 }
    }
  },

  "recommendation": "promote_to_approved",
  "rationale": "Treatment group shows statistically significant quality improvement (+0.03) and cost reduction (-10%) with no increase in failure rate."
}
```

### 7.3 Recommendation Actions

| Recommendation | Action |
|---------------|--------|
| `promote_to_approved` | Rule Manager moves Rule from `experiment` to `approved` |
| `promote_with_modifications` | Rule is approved after minor adjustments suggested by Evaluation Engine |
| `extend_experiment` | Not enough data; extend experiment with same or higher traffic share |
| `revert_to_control` | Experiment not beneficial; remove experiment Rule, keep control |
| `inconclusive` | Data insufficient or contradictory; human decision required |

---

## 8. Analytics Engine

### 8.1 Purpose

The Analytics Engine produces **aggregate metrics and trends** from Observability data. Unlike the Learning Engine (which detects anomalies), the Analytics Engine tracks steady-state trends.

### 8.2 Periodic Report

```json
{
  "report_id": "analytics://2026-07-19/daily",
  "engine": "analytics",
  "period": { "from": "2026-07-18T00:00:00Z", "to": "2026-07-19T00:00:00Z" },

  "summary": {
    "executions": { "total": 450, "success": 437, "failed": 10, "cancelled": 3 },
    "success_rate": 0.971,
    "total_cost_usd": 182.50,
    "avg_cost_per_execution": 0.41,
    "avg_duration_ms": 12500,
    "p95_duration_ms": 45000
  },

  "by_workflow": [
    { "workflow": "wf://finance/stock-research", "executions": 200, "success_rate": 0.98, "avg_cost": 0.52, "avg_duration_ms": 18500 },
    { "workflow": "wf://finance/etf-analysis", "executions": 80, "success_rate": 0.99, "avg_cost": 0.28, "avg_duration_ms": 8200 }
  ],

  "by_capability": [
    { "capability": "cap://nous-research/research-v2", "invocations": 350, "avg_cost": 0.35, "avg_latency_ms": 2800, "error_rate": 0.015 },
    { "capability": "cap://community-research/research-lite", "invocations": 100, "avg_cost": 0.08, "avg_latency_ms": 900, "error_rate": 0.005 }
  ],

  "by_model": [
    { "model": "claude-sonnet-4", "invocations": 300, "total_cost": 90.00, "avg_cost": 0.30 },
    { "model": "gpt-4o", "invocations": 150, "total_cost": 30.00, "avg_cost": 0.20 }
  ],

  "trends": {
    "cost_trend": "stable",       // stable | increasing | decreasing
    "quality_trend": "stable",     // stable | improving | declining
    "latency_trend": "stable",     // stable | increasing | decreasing
    "execution_volume_trend": "growing"  // stable | growing | shrinking
  }
}
```

---

## 9. Suggestion Queue

### 9.1 Output Format

All sub-engine outputs are converted to a uniform **Suggestion** format and placed in the Suggestion Queue:

```json
{
  "suggestion_id": "suggestion://2026-07-19/opt-003",
  "source": { "engine": "optimization", "report_id": "optimization://2026-07-19/model-003" },
  "generated_at": "2026-07-19T02:30:00Z",

  "type": "model_switch",
  "priority": "high",            // critical | high | medium | low
  "status": "pending_review",    // pending_review | in_review | approved | experiment | rejected

  "target": {
    "kind": "profile",
    "object_id": "profile://finance/deep"
  },

  "summary": "Switch research-v2 from claude-sonnet-4 to gpt-4o for news_analysis",
  "detail": "...",               // Full analysis from the generating engine
  "evidence_ref": "observability://costs?capability=...",

  "estimated_impact": {
    "cost_savings_usd_monthly": 36.00,
    "quality_change": -0.02,
    "risk": "low"
  }
}
```

### 9.2 Governance Interface

The Suggestion Queue is consumed by the **Human Governance** process:

```
pending_review
    │
    ├── human approves → status=approved → action executed
    │
    ├── human approves with experiment → status=experiment
    │                                      └→ Rule Manager sets experiment state
    │
    └── human rejects → status=rejected → ADR-XXXX recorded
```

---

## 10. Compliance

Any implementation claiming Agent OS Loop Learning compatibility **must**:

1. Run as an offline batch process (v1) — no real-time feedback loop (§3)
2. Implement all four sub-engines (Learning, Optimization, Evaluation, Analytics)
3. The Learning Engine must detect at minimum: cost anomaly, quality drop, capability drift, failure cluster, and replan loop patterns (§5)
4. The Optimization Engine must respect the 4 hard constraints in §6.4
5. The Evaluation Engine must implement all 5 recommendation actions from §7.3
6. All outputs must be placed in the Suggestion Queue as uniform Suggestion objects (§9)
7. The Loop must never modify Rules, Workflows, Manifests, or Configurations directly — all changes go through Human Governance (Constitution Article 10)

---

## 11. Open Questions

1. **Feedback loop** — should Loop-verified Manifest performance updates (RFC-0201 §4.5) update the Registry automatically, or always require human approval?
2. **Suggestion prioritization** — when the queue has 50+ suggestions, what algorithm determines review order? (Impact × confidence × urgency?)
3. **False positive filtering** — how does the Learning Engine distinguish real patterns from noise without human review for every pattern?
4. **Online feedback (v2)** — when the system graduates to online learning, what's the migration path from batch to streaming?

---

## 12. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.14 | Experience entity (Loop output) |
| RFC-0001 §8.4 | Replan loops (flagged for Loop analysis) |
| RFC-0104 §6.3 | Rule conflicts (flagged for Loop) |
| RFC-0104 §8.2 | Experiment sampling (data source for evaluation) |
| RFC-0104 §8.3 | Experiment lifecycle events (consumed by Evaluation Engine) |
| RFC-0201 §4.5 | Loop-verified Manifest performance (Learning Engine output) |
| RFC-0501 §3 | Observability data flow (Loop as consumer) |
| RFC-0501 §4 | Execution Traces (Learning Engine input) |
| RFC-0501 §5 | Cost Records (Optimization Engine input) |
| RFC-0501 §7 | Metrics (Analytics Engine input) |
| Constitution Article 10 | Loop has suggestion rights only |
