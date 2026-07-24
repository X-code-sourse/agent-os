# SPEC-0004: Security Model

> **Status:** v1.0 — Matches reference-runtime v0.4.3 Phase 0 implementation
> **Scope:** Security policy evaluation, tool-call guard, post-execution audit/scanning

---

## 1. Status

This spec describes the **Phase 0 (current)** implementation. The security model is deliberately minimal: a synchronous, SQLite-backed policy evaluator with optional event emission. It does NOT include event-driven pub/sub policy resolution, layered overrides, manifest signing, human-in-the-loop review, or audit mode. Those are documented in [Section 12 (Phase 2+ Roadmap)](#12-phase-2-roadmap) and do **not** exist in the current codebase.

---

## 2. Purpose

The Security Model answers one question for Phase 0:

> **Should this capability invocation be allowed, denied, or flagged for review?**

It operates at the **interoperability layer** — the same policy evaluation logic applies whether a capability runs via OpenAI, Anthropic, Ollama, or a future runtime. It does NOT perform model-level safety, transport security, API key management, or user authentication.

### 2.1 Scope Boundaries

**In scope (implemented):**
- Policy evaluation engine (`SecurityManager.evaluate()`) — synchronous, pure-function decision tree
- Policy storage (`PolicyStore`) — flat SQLite CRUD, versioned per policy
- Proxy tool-call guard (`ToolCallGuard`) — inspects LLM responses for dangerous tool calls
- Policy CLI commands (`security policy list/get/apply`, `security evaluate`, `security audit`)
- Post-execution scanning (`intent-os scan`) — traces in Event Store
- Audit reporting (`intent-os audit`) — execution records with cost/agent/model tracking
- `PolicyEvaluated` event emission (optional, via EventStore)

**Out of scope (Phase 2+, not implemented):**
- Event-driven pub/sub policy resolution
- Layered overrides (org -> user -> runtime)
- Manifest signing (ed25519 or other)
- `data_access_scope` with glob patterns
- Permission descriptors with scope/constraints
- Human-in-the-loop review flow (review events are defined but never emitted)
- Audit mode (log-only, no enforcement)
- Review expiration/timeout
- Policy specificity sorting
- Trust anchors / publisher allowlists
- `SecurityPolicy` YAML format with `kind`/`applies_to`

---

## 3. Design Principles

### P1: Declare, Don't Enforce (Current)

A capability declares its risk level and required permissions. The SecurityManager evaluates these declarations against stored policies. The capability manifest contains no enforcement logic.

### P2: Stateless Evaluation (Current)

`SecurityManager` holds no mutable evaluation state. Every `evaluate()` call is a pure function of `(policy_snapshot, capability_spec, context) -> decision`. This means:
- Any SecurityManager instance can evaluate any request
- Crash recovery requires no state restoration
- Evaluations are deterministic given the same inputs

### P3: Deny-by-Default (Current)

If no policy matches a capability name, the result is DENY. This is the security-conservative choice: capabilities must have explicit policy coverage to execute.

### P4: Policy Versioning (Current)

Every update to a policy increments its `version` field. Policies have `created_at` and `updated_at` timestamps. The PolicyStore retains all versions via upsert semantics.

### P5: Layered Overrides (Future — Phase 2+)

This principle is documented for design intent but is **not implemented**. The intended model is:

```
Capability Self-Declared Risk  ← most permissive
    ↓ override
Organizational Policy          ← can restrict
    ↓ override
User Consent                   ← can restrict
    ↓ override
Runtime Defaults               ← most restrictive (deny-by-default)
```

### P6: Audit-Before-Enforce (Future — Phase 2+)

The intended "audit mode" (log decisions without enforcing) does not exist. Currently, the only audit capability is post-execution via `intent-os audit` and `intent-os scan`.

---

## 4. Architecture

### 4.1 Synchronous Evaluation Flow (Current)

The SecurityManager performs **direct synchronous evaluation** — it does NOT use pub/sub or event-driven resolution. The caller provides the capability spec directly; the manager loads policies from a local SQLite database and returns a decision.

```
Caller (Planner, Proxy Guard, or CLI)
  │
  │  manager.evaluate(capability={name, risk, ...}, context={...})
  ▼
SecurityManager
  │
  │  1. policy_store.get_for_capability(name)   ──► PolicyStore (SQLite)
  │     ↓ matching policies
  │  2. Decision tree (see Section 4.2)
  │  3. Optionally emit PolicyEvaluated event     ──► EventStore
  │
  ▼
EvaluationResult(decision, rationale, policy_id, risk_level, capability_name)
```

Key differences from the aspirational event-driven design:
- **No `PolicyQueryRequest`/`PolicyQueryResponse` events.** The manager queries SQLite directly.
- **No Capability Manifest fetch.** The caller provides `SecuritySpec` (name, risk, permissions_required, review_required, allowed_contexts) — the manager never reaches into the Metadata Plane to load a manifest.
- **No pub/sub.** Policies are loaded via synchronous SQLite queries.

### 4.2 Decision Tree (Precise Order)

The `SecurityManager.evaluate()` decision tree runs in this exact order:

```
Phase A — Policy-driven checks (require at least one matching policy):

  A1. Explicit DENY rule in ANY matching policy
      → DENY (final, cannot be overridden by any subsequent check)

  A2. Explicit ALLOW rule in any matching policy
      → ALLOW (overrides review threshold)
      → Track _explicit_allowed flag to prevent A3 from upgrading to REVIEW

  A3. Review threshold exceeded
      → If policy.review_rules["require_review_for"] contains
        effective_risk.value → REQUIRE_REVIEW

      NOTE: Skipped if A2 found an explicit allow.
      NOTE: "require_review_for" is a list of risk level strings,
            e.g. ["high", "critical"]. There is no timeout or
            escalation — REQUIRE_REVIEW is an informational
            signal, not a blocking state with a review workflow.

  A4. Fallthrough — at least one policy matched with no deny/allow/review rule
      → ALLOW (attributed to first matching policy)

Phase B — Spec-level and default checks (run regardless of policy presence):

  B1. spec.review_required == True (and not already DENY)
      → REQUIRE_REVIEW

  B2. No policies matched at all
      → DENY (default deny)

  B3. Context restrictions (spec.allowed_contexts is non-empty, not already DENY)
      → If context keys don't match allowed_contexts glob patterns → DENY
```

### 4.3 Effective Risk Calculation

For each matching policy, `policy.effective_risk(capability_name, baseline)` checks if the capability name matches any key in `policy.risk_overrides` (glob-based). If it does, the override value replaces the baseline. Otherwise the capability's declared risk is used as-is.

---

## 5. Policy Model

### 5.1 Policy Data Structure

Policies are **flat** dataclass instances stored as rows in a single SQLite table. There is no `kind` discriminator, no `applies_to` sub-structure, no `metadata` block.

```python
@dataclass
class Policy:
    policy_id: str                    # Unique identifier (e.g. "pol-001")
    target_patterns: list[str]        # Glob patterns: ["file.*", "network.connect"]
    risk_overrides: dict[str, str]    # Pattern → risk level: {"file.delete": "critical"}
    permissions: list[str]            # Permissions granted: ["file:read", "network:outbound"]
    review_rules: dict[str, Any]      # Free-form dict with known keys:
                                      #   require_review_for: ["high", "critical"]
                                      #   deny: list[str] or dict with "capabilities" + "context"
                                      #   allow: list[str] or dict with "capabilities" + "context"
    version: int                      # Monotonically increasing, bumped on every upsert
    description: str                  # Human-readable
    enabled: bool                     # Disabled policies are skipped during evaluation
    created_at: str                   # ISO-8601
    updated_at: str                   # ISO-8601
```

### 5.2 What Policies Do NOT Have

These fields exist in the aspirational design but are **not present** in the current implementation:

- No `kind: SecurityPolicy` discriminator
- No structured `applies_to` (workflows, tags, publishers)
- No `review.timeout` or `review.escalation`
- No `audit` configuration block
- No structured permission descriptors (just a flat list of strings)
- No `min_approval_level`
- No `trust` section

### 5.3 Policy Matching

`policy.matches(capability_name)` uses `fnmatch.fnmatch` against each pattern in `target_patterns`. First match short-circuits. There is **no specificity sorting** — policies are returned in insertion order, and the decision tree processes them sequentially.

### 5.4 Policy Storage (SQLite Schema)

```sql
CREATE TABLE IF NOT EXISTS policies (
    policy_id       TEXT PRIMARY KEY,
    target_patterns TEXT NOT NULL DEFAULT '[]',   -- JSON array
    risk_overrides  TEXT NOT NULL DEFAULT '{}',   -- JSON object
    permissions     TEXT NOT NULL DEFAULT '[]',   -- JSON array
    review_rules    TEXT NOT NULL DEFAULT '{}',   -- JSON object
    version         INTEGER NOT NULL DEFAULT 1,
    description     TEXT NOT NULL DEFAULT '',
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
```

All structured fields are stored as JSON-encoded TEXT to avoid SQLite JSON1 extension dependency.

### 5.5 Example Policy (YAML)

This is the format accepted by `security policy apply`:

```yaml
policy_id: "pol-default"
target_patterns:
  - "tool.*"
  - "file.*"
risk_overrides:
  "file.delete": "critical"
permissions:
  - "file:read"
  - "network:outbound"
review_rules:
  require_review_for:
    - "high"
    - "critical"
  deny:
    capabilities:
      - "tool.bash"
      - "tool.exec"
  allow:
    - "tool.read_file"
    - "tool.list_directory"
version: 1
description: "Default enterprise policy"
enabled: true
```

---

## 6. SecuritySpec (Capability Manifest Integration)

### 6.1 Two SecuritySpec Definitions

The codebase contains **two** SecuritySpec definitions:

**A. `core.models.SecuritySpec` — used in CapabilityManifest parsing:**

```python
@dataclass
class SecuritySpec:
    risk: SecurityRisk = SecurityRisk.LOW       # low | medium | high | critical
    network: bool = False                        # Does capability make network calls?
    data_access: bool = False                    # Does it access user/organization data?
    require_approval: bool = False               # Does it require human approval?
```

This is the field attached to parsed `CapabilityManifest` objects. It is **not** directly consumed by `SecurityManager.evaluate()`.

**B. `core.security.SecuritySpec` — used by SecurityManager:**

```python
@dataclass
class SecuritySpec:
    name: str                                    # Canonical capability name
    risk: SecurityRisk = SecurityRisk.MEDIUM
    permissions_required: list[str] = []         # e.g. ["file:write"]
    review_required: bool = False                # Always require review
    allowed_contexts: list[str] = []             # Glob patterns for context keys
```

`SecurityManager.evaluate()` accepts this spec, or a dict with equivalent keys, or bare `capability_name` + `risk_level` kwargs.

### 6.2 Risk Levels

```python
class SecurityRisk(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

Supports ordered comparison: `CRITICAL >= HIGH >= MEDIUM >= LOW`.

| Level | Examples | Default Policy Behavior (with no matching policy) |
|---|---|---|
| `low` | Text formatting, read_file, list_directory | DENY (no policy = deny) |
| `medium` | API calls, HTTP requests | DENY (no policy = deny) |
| `high` | File write, shell execution, DB queries | DENY (no policy = deny) |
| `critical` | File deletion, process execution, deployment | DENY (no policy = deny) |

**Note:** There are no auto-allow defaults by risk level. Without a matching policy, **every** risk level results in DENY. The policy determines what is allowed.

---

## 7. PolicyStore

### 7.1 Overview

`PolicyStore` is a SQLite-backed CRUD store living in the Metadata Plane. It is **not** event-driven — callers interact with it synchronously.

### 7.2 API

| Method | Description |
|---|---|
| `PolicyStore(db_path)` | Initialize, auto-create `policies` table |
| `upsert(policy) -> Policy` | Insert or update. Bumps version, refreshes timestamps |
| `get(policy_id) -> Policy \| None` | Retrieve by ID |
| `get_for_capability(name, context) -> list[Policy]` | Return all enabled policies whose `target_patterns` match `name` |
| `delete(policy_id) -> bool` | Remove by ID, returns success |
| `list_all() -> list[Policy]` | All policies, enabled or not |
| `count() -> int` | Total policy count |
| `close()` | Close DB connection |

`get_for_capability` iterates all enabled rows, calls `policy.matches(name)` on each, and returns matching policies in insertion order. The `context` parameter is accepted but **not used** at the query level (it is reserved for future context-aware filtering).

### 7.3 Versioning

- `upsert` increments `version` by 1 if the policy already exists
- New policies start at `version: 1`
- Old versions are overwritten (not retained as history)
- `created_at` is preserved across updates; `updated_at` is always refreshed

---

## 8. SecurityManager

### 8.1 Overview

```python
class SecurityManager:
    def __init__(self, policy_store: PolicyStore, event_store: EventStore | None = None)
    def evaluate(self, capability, context) -> EvaluationResult
```

- **Stateless** — holds references to `PolicyStore` and optional `EventStore`, but no mutable evaluation state
- **Synchronous** — no async/await, no callbacks, no pub/sub
- **Event emission is optional** — if `event_store` is `None`, decisions are returned without persistence

### 8.2 evaluate() Signature

```python
def evaluate(
    self,
    capability: SecuritySpec | dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    *,
    capability_name: str | None = None,
    risk_level: str | None = None,
) -> EvaluationResult
```

Accepts a `SecuritySpec` object, a dict with `name`/`risk`/`permissions_required`/`review_required`/`allowed_contexts`, or bare string kwargs. The dict form is the most common for ad-hoc evaluation (e.g., from the proxy guard).

### 8.3 EvaluationResult

```python
@dataclass
class EvaluationResult:
    decision: SecurityDecision      # ALLOW | REQUIRE_REVIEW | DENY
    rationale: str                  # Human-readable explanation
    policy_id: str | None           # ID of the deciding policy, or None
    risk_level: str                 # Effective risk level (may be overridden)
    capability_name: str            # Name of the evaluated capability
```

### 8.4 SecurityDecision Enum

```python
class SecurityDecision(Enum):
    ALLOW = "allow"
    REQUIRE_REVIEW = "require_review"
    DENY = "deny"
```

`REQUIRE_REVIEW` is an informational signal. There is **no review workflow** — no `ReviewRequired`/`ReviewCompleted` event emission, no review token, no timeout, no escalation. The caller is responsible for interpreting `REQUIRE_REVIEW` however it chooses.

### 8.5 Context Matching

`_matches_rules()` supports two rule formats:

1. **List of glob patterns** — matched against capability name:
   ```python
   "deny": ["tool.bash", "tool.exec.*"]
   ```

2. **Dict with `capabilities` and optional `context` constraints**:
   ```python
   "deny": {
       "capabilities": ["tool.bash"],
       "context": {"user_role": ["guest", "intern"]}
   }
   ```
   Context matching uses simple key-value equality (or list membership).

`_context_allowed()` matches context **keys** (not values) against glob patterns from `spec.allowed_contexts`.

---

## 9. Proxy Tool Call Guard

### 9.1 Overview

`ToolCallGuard` is an **optional** proxy layer (enabled via `--guard` flag) that inspects LLM responses for tool/function calls and evaluates them against security policies.

### 9.2 Tool Risk Classification

`classify_tool_risk(tool_name)` maps tool names to risk levels using a hardcoded dictionary of **30+ patterns** across six categories:

| Category | Example Patterns | Default Risk |
|---|---|---|
| **filesystem** | `write_file`, `delete_file`, `edit_file`, `chmod`, `rename_file` | high/critical |
| **shell** | `bash`, `execute_command`, `run_shell`, `exec`, `subprocess` | high/critical |
| **data** | `database_query`, `sql`, `delete_database`, `drop_table`, `read_database` | high/critical |
| **network** | `api_call`, `http_request`, `fetch_url` | medium |
| **deployment** | `deploy`, `kubernetes`, `docker`, `terraform` | critical |
| **auth** | `add_ssh_key`, `create_user`, `delete_user`, `sudo` | high/critical |
| **low-risk** | `read_file`, `list_directory` | low |

Matching strategy: exact name match first, then substring fallback (if the pattern is found within the tool name or vice versa). Unknown tools default to `{"risk": "medium", "category": "unknown"}`.

### 9.3 Sensitive Data Scanning

`check_sensitive_data(text)` scans text against regex patterns for:
- API keys (OpenAI, Anthropic, AWS, GitHub)
- Bearer tokens, JWT tokens
- Password assignment in environment variables
- Private key blocks (PEM format)

Returns `[{type, match_preview}]` for any matches.

### 9.4 Response Parsing

- `parse_openai_tool_calls(response_body)` — extracts `tool_calls` from OpenAI chat completion responses
- `parse_anthropic_tool_calls(response_body)` — extracts `tool_use` blocks from Anthropic content arrays

### 9.5 Inspection Flow

```
LLM Response
  → parse tool/function calls
  → for each call:
       classify_tool_risk(name)
       manager.evaluate(capability_name=f"tool.{name}", risk_level=classified_risk)
       check_sensitive_data(arguments)
  → return [{tool, risk, category, decision, rationale, sensitive_data_found}]
```

### 9.6 What the Guard Does NOT Do

- Does NOT modify the forwarding path — it only adds inspection
- Does NOT block execution — it reports decisions but the caller decides what to do
- Does NOT use typed permission descriptors — tool risk is determined by pure name matching

---

## 10. Security Events

### 10.1 Implemented: PolicyEvaluated

Only **one** security event type is emitted in the current codebase:

```python
EventType.POLICY_EVALUATED = "PolicyEvaluated"
```

Emitted by `SecurityManager._emit_event()` after every evaluation (if `event_store` is provided). Payload:

```json
{
    "policy_id": "pol-001",
    "capability": "file.write",
    "decision": "allow",
    "rationale": "Capability 'file.write' is permitted by policy 'pol-001'.",
    "risk_level": "high"
}
```

Each evaluation gets a fresh UUID `trace_id` — the SecurityManager maintains no session state.

### 10.2 Defined but NOT Emitted (Phase 2+)

These event types exist in `EventType` enum but **no code emits them**:

| Event Type | Status |
|---|---|
| `PERMISSION_GRANTED` | Defined, not emitted |
| `PERMISSION_DENIED` | Defined, not emitted |
| `REVIEW_REQUIRED` | Defined (in enum as `ReviewRequired`), not emitted |
| `REVIEW_COMPLETED` | Defined (in enum as `ReviewCompleted`), not emitted |
| `REVIEW_EXPIRED` | Defined, not emitted |
| `POLICY_VIOLATION` | Defined, not emitted |

They are placeholders reserved for Phase 2+ review workflows, fine-grained permission tracking, and behavioral anomaly detection.

---

## 11. CLI Commands

### 11.1 Security Commands

```bash
# List all policies
intent-os security policy list

# Get a single policy
intent-os security policy get <name>

# Apply a policy from a YAML file
intent-os security policy apply <file.yaml>

# Dry-run: evaluate a capability manifest against stored policies
intent-os security evaluate <manifest.yaml>

# Export compliance report (policy coverage summary in JSON)
intent-os security audit
```

### 11.2 Scan Command

```bash
# Scan all recent traces for security issues
intent-os scan

# Scan a specific trace
intent-os scan --trace <trace-id>

# Generate a security report file (CSV)
intent-os scan --report

# Generate an HTML security report
intent-os scan --report --html

# Specify output path
intent-os scan --report --output report.csv
```

The scan command is **post-execution and read-only** — it reads from the Event Store, identifies dangerous tool call patterns, sensitive data exposure, permission errors, and agent call failures. It does not modify state or intercept execution.

Scan analysis includes:
- Sensitive data pattern scanning (API keys, tokens, passwords)
- Agent call failure detection
- Permission denial pattern detection in execution errors

### 11.3 Audit Command

```bash
# Summary of all execution records
intent-os audit

# Full audit report (CSV)
intent-os audit report

# Full audit report (HTML)
intent-os audit report --html

# Full audit report (JSON)
intent-os audit report --json

# Limit to N days
intent-os audit report --days 30
```

The audit command generates compliance-ready reports covering: trace IDs, capability names/versions, status (success/failure), runtimes, adapters, costs, token usage, agents, models, and security events detected.

---

## 12. Phase 2+ Roadmap

Everything in this section is **not implemented**. It documents the design direction for future phases.

### 12.1 Event-Driven Policy Resolution

Replace direct SQLite queries with pub/sub:
```
SecurityManager emits PolicyQueryRequest → Event Bus
Metadata Plane subscribers respond with PolicyQueryResponse
```

This would enable distributed deployment (any SecurityManager instance can evaluate any request without a local PolicyStore) and deterministic replays (replay events, get same decisions).

### 12.2 Layered Overrides

Implement the `org → user → runtime` restriction chain. Each layer can only restrict, never expand. Organizational policy stored in Metadata Plane, user preferences via User Plane, runtime defaults as final safety net.

### 12.3 Human-in-the-Loop Review

Implement actual review workflow using `REVIEW_REQUIRED`, `REVIEW_COMPLETED`, and `REVIEW_EXPIRED` events:
- Review request with token, expiration
- User Plane presents approval dialog
- Auto-DENY on timeout
- Configurable escalation path

### 12.4 Manifest Signing

Ed25519 signature support in Capability Manifests:
- Sign manifest fields with publisher private key
- Verify against trusted publisher registry
- Block unsigned manifests when policy requires signatures

### 12.5 Structured Permission Descriptors

Replace flat `permissions: list[str]` with typed descriptors:
```yaml
permissions:
  - id: filesystem_write
    type: filesystem
    scope: "output/*"
    risk: medium
    optional: true
    constraints:
      max_file_size: "10MB"
```

### 12.6 Data Access Scope

Add `data_access_scope` to manifest `spec.security`:
```yaml
data_access_scope:
  reads:
    - files: ["*.md", "*.txt"]
    - env: ["USER", "HOME"]
  writes:
    - files: ["output/*"]
```

### 12.7 Advanced Policy Features

- `applies_to` with workflow, tag, and publisher matching
- Review timeout and escalation configuration
- Audit mode (log-only, no enforcement)
- Policy specificity sorting (most specific match wins)
- Conflict detection for overlapping policy scopes
- Dry-run policy evaluation against historical events

### 12.8 Trust Anchors

Publisher verification via trusted registry:
- `trust.require_signed_manifest`
- `trust.allowed_publishers`
- Periodic re-validation (`max_manifest_age`)

### 12.9 Behavioral Anomaly Detection

Runtime behavior monitoring:
- `POLICY_VIOLATION` events when capability exceeds declared scope
- Anomaly detection in Phase 3+ (event pattern analysis)
- Automated policy suggestion from Event Store analytics

### 12.10 Audit Mode

`audit.level` configuration:
- `none` — no audit events
- `decisions_only` — log decisions without payload
- `all` — full audit with payload
- `include_payload` and `retention_days` settings

---

## 13. Validation Rules (Current Implementation)

1. **No-policy = deny**: A capability with no matching policy receives DENY.
2. **Explicit deny is final**: An explicit deny rule in any matching policy overrides all other rules.
3. **Explicit allow overrides review**: An explicit allow rule prevents review threshold from upgrading to REQUIRE_REVIEW.
4. **Context restrictions fail closed**: If `spec.allowed_contexts` is non-empty and context keys don't match, the result is DENY.
5. **Disabled policies are skipped**: Only `enabled=1` policies participate in evaluation.
6. **Risk override is glob-based**: `policy.risk_overrides` matches keys against capability name via `fnmatch`.

---

## 14. Files

| File | Role |
|---|---|
| `reference-runtime/core/security.py` | SecurityManager, PolicyStore, Policy, SecuritySpec, SecurityDecision, EvaluationResult |
| `reference-runtime/core/models.py` | EventType enum (all security events), CapabilityManifest SecuritySpec |
| `reference-runtime/proxy/guard.py` | ToolCallGuard, classify_tool_risk, check_sensitive_data, response parsers |
| `reference-runtime/commands/security.py` | CLI: policy list/get/apply, evaluate, audit |
| `reference-runtime/commands/scan.py` | CLI: post-execution security scanning |
| `reference-runtime/commands/audit.py` | CLI: compliance audit reports |
| `reference-runtime/cli.py` | CLI command registration and parser setup |

---

## 15. References

- SPEC-0001: Capability Manifest — `SecuritySpec` in manifest model
- SPEC-0003: Event Schema — `POLICY_EVALUATED`, reserved security events
- `fnmatch` — Python standard library glob matching used for policy targeting
