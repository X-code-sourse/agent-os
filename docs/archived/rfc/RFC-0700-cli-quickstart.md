# RFC-0700: CLI & Quickstart Specification

**Status:** Draft
**Type:** Interface RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.1, RFC-0001 v1.0, RFC-0100 v1.0, RFC-0101 v1.0, RFC-0201 v1.0
**Author:** Architecture Team
**Date:** 2026-07-20

---

## 1. Summary

This RFC defines the **CLI interface** for Agent OS — the four commands that form the user-facing entry point. It specifies input/output formats, exit codes, error output structure, and the machine-readable JSON variants. Every reference implementation must implement these four commands before any higher-level interface (API, GUI).

---

## 2. Motivation

The entire Agent OS specification defines a precise internal architecture, but nowhere specifies how a user interacts with it on the first day. Without a CLI specification:

- Every implementation invents its own command structure and flag conventions
- There is no standard machine-readable output format for tooling to consume
- Error codes (SPEC-0000 §11) have no defined rendering surface
- The "first minute" experience is undefined

---

## 3. Command Overview

```
agentos run <workflow_id> [--query <text>] [--profile <ref>] [--output <path>] [--json] [--verbose]
agentos workflow validate <path> [--json]
agentos workflow plan <workflow_id> --query <text> [--json]
agentos capability scaffold <name> [--output <dir>]
```

### 3.1 Global Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--verbose` | bool | false | Print Event trace to stderr during execution |
| `--json` | bool | false | Output in JSON format (machine-readable) instead of human-readable |

### 3.2 Exit Codes

| Code | Meaning | When |
|------|---------|------|
| 0 | Success | Command completed successfully |
| 1 | Validation error | Input validation failed (bad YAML, missing fields) |
| 2 | Execution error | Runtime execution failed (Capability error, timeout) |
| 3 | Not found | Workflow, capability, or profile not found |
| 4 | Configuration error | Missing config file, bad environment |
| 5 | Internal error | Unexpected system error (bug) |

---

## 4. `agentos run`

### 4.1 Purpose

Execute a workflow from start to finish: load Workflow → compile Plan → execute Tasks → review → output report.

### 4.2 Usage

```bash
# Human-readable output (Markdown report to stdout)
agentos run stock_research --query "research Nvidia stock"

# Save report to file
agentos run stock_research --query "research Nvidia stock" --output report.md

# JSON output (machine-readable)
agentos run stock_research --query "research Nvidia stock" --json

# With execution trace on stderr
agentos run stock_research --query "research Nvidia stock" --verbose 2>trace.log
```

### 4.3 Input

| Argument | Required | Description |
|----------|----------|-------------|
| `<workflow_id>` | yes | Workflow identifier (file stem or registry ID) |
| `--query` | yes | User goal text |
| `--profile` | no | Profile reference (default: `profile://default/default`) |
| `--output` | no | File path to write report (default: stdout) |
| `--verbose` | no | Print Event trace to stderr |
| `--json` | no | Machine-readable JSON output |

### 4.4 Output (Human-Readable, default)

A Markdown document containing:

```markdown
# Agent OS Report — `<workflow_id>`

**Generated:** 2026-07-20T12:00:00Z
**Execution Status:** completed

## Task Results

| Task | Status | Output Preview |
|------|--------|---------------|
| search_news | ✅ completed | Found 15 articles... |
| llm_analysis | ✅ completed | ## Investment Highlights... |

## Quality Review

**Overall:** ✅ PASSED

| Check | Result | Detail |
|-------|--------|--------|
| execution_status | ✅ | Status: completed |
| non_empty_outputs | ✅ | 5/5 tasks produced output |

## Detailed Outputs

### search_news
[Full output of each task]
```

### 4.5 Output (JSON, `--json` flag)

```json
{
  "version": "1.0",
  "command": "run",
  "exit_code": 0,

  "execution": {
    "execution_id": "exec://default/a1b2c3d4",
    "workflow_ref": "wf://default/stock_research@1.0.0",
    "status": "completed",
    "started_at": "2026-07-20T12:00:00Z",
    "completed_at": "2026-07-20T12:00:15Z",
    "duration_ms": 15000,
    "total_cost_usd": 0.42
  },

  "tasks": [
    {
      "task_id": "task://exec_001/001",
      "stage_id": "search_news",
      "status": "completed",
      "duration_ms": 3200,
      "output_preview": "Found 15 articles about Nvidia...",
      "review_score": 0.95
    }
  ],

  "review": {
    "result": "pass",
    "score": 0.91,
    "checks": [
      { "check": "execution_status", "status": "pass" },
      { "check": "non_empty_outputs", "status": "pass" }
    ]
  },

  "errors": []
}
```

### 4.6 Error Output (JSON)

```json
{
  "version": "1.0",
  "command": "run",
  "exit_code": 2,

  "execution": {
    "status": "failed",
    "error": {
      "code": "PLAN_ERR_004",
      "severity": "fatal",
      "message": "No capability matches requirements for stage 'financial_analysis'",
      "detail": "type=research, domain=[finance, sec_filing], quality_min=0.85",
      "suggested_action": "Lower quality_min, remove sec_filing domain, or register a matching capability",
      "source": { "module": "planner", "stage_id": "financial_analysis" }
    }
  },

  "tasks": [],
  "review": null,
  "errors": [
    {
      "code": "PLAN_ERR_004",
      "severity": "fatal",
      "message": "No capability matches requirements for stage 'financial_analysis'",
      "suggested_action": "Lower quality_min, remove sec_filing domain, or register a matching capability"
    }
  ]
}
```

### 4.7 Verbose Mode (`--verbose`)

When `--verbose` is set, each Event published during execution is printed to stderr as JSON Lines:

```
# stderr (interleaved with stdout report)
{"event_type":"Task:Created","payload":{"task_id":"task://001","stage_id":"search_news"}}
{"event_type":"Task:Queued","payload":{"task_id":"task://001"}}
{"event_type":"Task:Running","payload":{"task_id":"task://001","capability_id":"cap://..."}}
{"event_type":"Task:Completed","payload":{"task_id":"task://001","duration_ms":3200}}
```

---

## 5. `agentos workflow validate`

### 5.1 Purpose

Validate a Workflow YAML file against the Workflow specification (RFC-0100) without executing it. Reports structural errors, missing fields, cyclic dependencies, and condition expression syntax errors.

### 5.2 Usage

```bash
# Human-readable
agentos workflow validate stock_research.yaml

# JSON output
agentos workflow validate stock_research.yaml --json
```

### 5.3 Output (Human-Readable)

```
✅ workflows/stock_research.yaml — valid
  5 stages, 7 dependencies, no cycles

❌ workflows/broken.yaml — 2 errors
  ERROR WF_ERR_001: Stage 'analysis' has a cyclic dependency
    → Break the cycle in depends_on
  ERROR WF_ERR_004: Stage 'risk' has no capability_type in requirements
    → Add capability_type field
```

### 5.4 Output (JSON)

```json
{
  "version": "1.0",
  "command": "workflow validate",
  "exit_code": 0,

  "file": "workflows/stock_research.yaml",
  "valid": true,
  "summary": {
    "stages": 5,
    "dependencies": 7,
    "has_cycles": false
  },
  "errors": []
}
```

On validation failure:

```json
{
  "version": "1.0",
  "command": "workflow validate",
  "exit_code": 1,

  "file": "workflows/broken.yaml",
  "valid": false,
  "errors": [
    {
      "code": "WF_ERR_001",
      "severity": "fatal",
      "message": "Workflow 'broken' has a cyclic dependency at stage 'analysis'",
      "suggested_action": "Break the cycle in depends_on"
    },
    {
      "code": "WF_ERR_004",
      "severity": "error",
      "message": "Stage 'risk' has no capability_type in requirements",
      "suggested_action": "Add capability_type field"
    }
  ]
}
```

---

## 6. `agentos workflow plan`

### 6.1 Purpose

Show the compiled Execution Plan for a Workflow without executing it. Useful for debugging: see which stages are pruned, which Capabilities are bound, and the estimated cost.

### 6.2 Usage

```bash
# Human-readable
agentos workflow plan stock_research --query "research Nvidia stock"

# JSON output
agentos workflow plan stock_research --query "research Nvidia stock" --json
```

### 6.3 Output (Human-Readable)

```
📋 Plan for stock_research (@1.0.0)
  Profile: profile://default/default
  Rules: 2 applied (sec-filing@1.2.0, risk-check@3.0.1)

  Stages (4 active, 3 pruned):
    → company_identification    [research]             $0.02  ~2.5s
    → news_analysis             [research]             $0.02  ~2.5s
    → financial_analysis        [research]             $0.02  ~2.5s
    → summary_report            [writing]              $0.01  ~1.0s

  Pruned:
    ✄ valuation_analysis   (condition: depth=quick)
    ✄ risk_assessment      (condition: depth=quick)
    ✄ peer_comparison      (condition: depth=quick)

  Estimated total: $0.07  |  ~8.5s
```

### 6.4 Output (JSON)

```json
{
  "version": "1.0",
  "command": "workflow plan",
  "exit_code": 0,

  "workflow_ref": "wf://default/stock_research@1.0.0",
  "profile_ref": "profile://default/default",

  "stages": [
    {
      "stage_id": "company_identification",
      "type": "task_node",
      "active": true,
      "capability_binding": {
        "capability_id": "cap://example/research-v1",
        "model": "claude-sonnet-4",
        "estimated_cost": 0.02,
        "estimated_latency_ms": 2500
      }
    }
  ],

  "pruned_stages": [
    { "stage_id": "valuation_analysis", "reason": "condition: depth=quick" }
  ],

  "estimates": {
    "total_cost_usd": 0.07,
    "total_latency_ms": 8500,
    "parallel_regions": 1
  }
}
```

---

## 7. `agentos capability scaffold`

### 7.1 Purpose

Generate a minimal, runnable Capability project scaffold. The output is a directory with a Manifest YAML and a Python file implementing the Capability interface (RFC-0200). The scaffold is immediately registerable and invocable.

### 7.2 Usage

```bash
agentos capability scaffold my-research --output ./capabilities/
```

### 7.3 Output

Creates the following files:

```
./capabilities/my-research/
├── manifest.yaml
└── capability.py
```

`manifest.yaml` (auto-generated, ~30 lines):

```yaml
manifest_id: cap://local/my-research
version: 1.0.0
name: "My Research"
description: "Auto-generated capability scaffold"

type: research
supported_domains: [general]
supported_languages: [en]

interfaces:
  execute:
    input_schema:
      type: object
      required: [query]
      properties:
        query: { type: string }

    output_schema:
      type: object
      properties:
        result: { type: string }

features:
  supported: []

performance:
  quality_score: 0.80
  avg_latency_ms: 1000
  cost_per_call: 0.01

errors:
  supported: [timeout, invalid_input, internal_error, cancelled]

lifecycle:
  status: active
```

`capability.py` (auto-generated, ~60 lines):

```python
"""My Research — auto-generated capability scaffold."""

from agentos.capability import Capability, ExecutionResult


class MyResearch(Capability):
    """Minimal capability implementation."""

    async def execute(self, input, context, config) -> ExecutionResult:
        query = input.get("query", "")
        # TODO: Replace with actual research logic
        result = f"Research result for: {query}"
        return ExecutionResult(
            status="success",
            output={"result": result},
            metrics={
                "tokens_used": 0,
                "api_calls": 0,
                "latency_ms": 0,
                "cost_usd": 0.0,
            },
        )

    async def cancel(self, invocation_id) -> dict:
        return {"status": "cancelled", "work_saved": {}}
```

---

## 8. Compliance

Any implementation claiming Agent OS CLI compatibility **must**:

1. Implement all four commands: `run`, `workflow validate`, `workflow plan`, `capability scaffold`
2. Use the exit codes defined in §3.2 (0–5)
3. Support human-readable output as the default and `--json` for machine-readable
4. Render errors using SPEC-0000 §11 error codes, not natural language strings (§4.6)
5. Support `--verbose` mode with JSON Lines Event trace on stderr (§4.7)
6. The `run` command must produce either a Markdown report or JSON matching §4.4/§4.5
7. The `workflow validate` command must accept a file path (not just a registry ID)
8. The `capability scaffold` command must produce exactly the two files defined in §7.3
9. Every error output must include `suggested_action` (§4.6)

---

## 9. Open Questions

1. **Plan caching** — should `agentos workflow plan` cache compiled plans, or always recompile?
2. **Output streaming** — should `agentos run` support `--watch` mode that streams task completions as they happen?
3. **Scaffold language** — should `capability scaffold` support languages other than Python (e.g., `--lang rust`)?
4. **Interactive mode** — should there be an `agentos shell` command for interactive goal entry?

---

## 10. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §11 | Error Code Directory (all CLI error output references these) |
| RFC-0100 §9 | Workflow Validation Rules (validated by `workflow validate`) |
| RFC-0101 §8 | Planner API (invoked by `workflow plan` and `run`) |
| RFC-0100 §10 | Execution Plan format (output by `workflow plan --json`) |
| RFC-0200 §4 | Capability Contract (implemented by scaffold output) |
| RFC-0201 §3 | Manifest Schema (included in scaffold output) |
