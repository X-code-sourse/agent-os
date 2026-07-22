# SPEC-0004: Security Model

> **Status:** Design Draft v0.1 — Phase 2 (Placeholder in Phase 0/1)
> **Scope:** Defines permission, authentication, authorization, and audit model for Intent OS
> **Editor:** Security Architect — Intent OS Project

---

## 1. Purpose

The Security Model defines **how AI capability execution is secured** — how permissions are declared, enforced, audited, and governed. It answers one question:

> **Who can do what, under what conditions, and how is it recorded?**

Intent OS's security model is unique because it operates at the **interoperability layer**, not within a single runtime. It must work across OpenAI, Anthropic, Ollama, and future runtimes — each with their own security models and trust boundaries.

### 1.1 Design Constraints from the Constitution

This spec is designed within the following inviolable constraints:

| Constraint | Implication for Security |
|---|---|
| **R1: Control Plane Owns No State** | Security Manager (Control Plane) evaluates policies but never stores them. Policies are stored in Metadata Plane, evaluation results flow to Data Plane via Event Bus. |
| **R2: No Direct Inter-Processor Communication** | All security checks must route through the Scheduler. Processors cannot bypass security by invoking each other directly. |
| **R3: Event Bus is Single Source of Truth** | Every security decision — allow, deny, escalate, require approval — is recorded as an Event. No audit trail exists outside Events. |
| **R4: Capabilities are Stateless** | A capability carries its security *declaration* (risk level, required permissions) but never maintains security *state*. |

### 1.2 Scope Boundaries

**In scope:**
- Permission declaration format (in Capability Manifest)
- Policy evaluation flow (enforcement architecture)
- Human approval gates (Review workflow)
- Audit trail via Event Schema
- Organizational policy overrides
- Capability-level privilege separation

**Out of scope (not part of this spec):**
- ❌ Model-level security (ML model safety, alignment, jailbreak prevention)
- ❌ Transport security (TLS, mTLS — delegated to deployment infrastructure)
- ❌ API key management (adapter-specific, not interoperability concern)
- ❌ User authentication (delegated to the consuming application)
- ❌ MCP server authentication (handled by MCP protocol)
- ❌ Confidential computing / TEE integration (Phase 3+)

---

## 2. Design Principles

### P1: Declare, Don't Enforce

A Capability Manifest **declares** its security requirements (risk level, required permissions, network access). The runtime **enforces** them. The Manifest cannot contain enforcement logic. This keeps Manifests portable — the same Manifest running on a strict enterprise runtime and a permissive development runtime behaves within different policy bounds.

### P2: Layered Overrides

Security is evaluated in layers, with each layer able to restrict but never expand:

```
Capability Self-Declared Risk  ← most permissive
    ↓ override
Organizational Policy          ← can restrict
    ↓ override
User Consent                   ← can restrict
    ↓ override
Runtime Defaults               ← most restrictive (deny-by-default)
```

A capability that self-declares `risk: low` cannot be expanded to `risk: high` by any layer. But a `risk: high` capability can be blocked by organizational policy.

### P3: Audit-Before-Enforce (Phase 2+)

In Phase 2, the system should support "audit mode": log all policy decisions without enforcing them. This allows organizations to discover what their AI capabilities are actually doing before writing restrictive policies. This is the security equivalent of "observe before control."

### P4: Capability Least Privilege

Each capability should declare the minimum permissions it needs. The runtime should have defaults for common patterns:
- Read-only text processing → no special permissions
- Web search → `network: true`
- File system write → `require_approval: true`

---

## 3. Architecture

### 3.1 Security Components in the Five-Plane Architecture

```
┌──────────────────────────────────┐
│ User Plane                       │
│  - User consent dialogs          │
│  - Human approval workflows      │
└──────────────┬───────────────────┘
               │ Event Bus
┌──────────────▼───────────────────┐
│ Control Plane                    │
│  Planner / Execution Engine      │
│  ┌──────────────────────────┐    │
│  │   Security Manager       │    │  ← Policy evaluation engine
│  │   - Policy Evaluator     │    │     OWNS NO STATE (R1)
│  │   - Consent Delegator    │    │
│  └──────────────────────────┘    │
└──────────────┬───────────────────┘
               │ Event Bus
┌──────────────▼───────────────────┐
│ Metadata Plane                   │
│  ┌──────────────────────────┐    │
│  │   Policy Store           │    │  ← Policies live here, not in Control Plane
│  │   - Org policies         │    │
│  │   - User preferences     │    │
│  │   - Trust anchors        │    │
│  └──────────────────────────┘    │
└──────────────┬───────────────────┘
┌──────────────▼───────────────────┐
│ Data Plane                       │
│  ┌──────────────────────────┐    │
│  │   Audit Log (Event Store)│    │  ← All decisions recorded
│  │   - PolicyEvaluated      │    │
│  │   - ReviewRequired       │    │
│  │   - ReviewCompleted      │    │
│  └──────────────────────────┘    │
└──────────────┬───────────────────┘
┌──────────────▼───────────────────┐
│ Runtime Plane                    │
│  - Enforcement hooks per adapter │
│  - Capability risk constraints   │
└──────────────────────────────────┘
```

### 3.2 Policy Evaluation Flow

```
                        ┌──────────────┐
                        │   Planner    │
                        │ (identifies  │
                        │  capability) │
                        └──────┬───────┘
                               │ requests execution
                               ▼
                  ┌──────────────────────┐
                  │   Security Manager   │
                  │                      │
                  │ 1. Load capability   │──→ Metadata Plane (fetch Manifest)
                  │    manifest security │
                  │ 2. Load org policies │──→ Metadata Plane (Policy Store)
                  │ 3. Evaluate          │
                  │    a) Is capability  │
                  │       explicitly     │
                  │       blocked?       │
                  │    b) Is risk level  │
                  │       within policy  │
                  │       bounds?        │
                  │    c) Does workflow  │
                  │       context match  │
                  │       policy scope?  │
                  │ 4. Determine action  │
                  │    - ALLOW           │──→ proceed to executor
                  │    - DENY            │──→ block + record
                  │    - REQUIRE_REVIEW  │──→ escalate to User Plane
                  │                      │
                  │ 5. Record decision   │──→ Event Bus → Data Plane
                  └──────────────────────┘
```

### 3.3 Key Architectural Rule: Evaluation Without State

The Security Manager evaluates policy but never stores it. The full flow is stateless:

```
Security Manager receives "evaluate(capability, context)" request
  → emits PolicyQueryRequest Event (Event Bus → Metadata Plane)
  → Metadata Plane responds with PolicyQueryResponse Event containing capability security declaration + applicable policies
  → evaluates declaratively (pure function of inputs: capability.security + policies + context)
  → emits PolicyEvaluated Event with: decision, rationale, policy_id
  → returns decision to caller
  → does NOT cache, does NOT store, does NOT maintain session state

Security Manager never queries the Event Bus directly. The Event Bus is a message-passing medium, not a queryable store. All information flows through the publish/subscribe pattern: Security Manager publishes a request event, Metadata Plane subscribers respond with a response event. This preserves R1 (Control Plane owns no state — responses are transient messages, not stored state) and R3 (Event Bus is single source of truth — the request/response pair is recorded as Events).
```

This enables:
- **Deterministic replays**: replay the same events and get the same policy decisions
- **Distributed deployment**: any Security Manager instance can evaluate any request
- **Zero state recovery**: crash recovery requires no security state restoration

---

## 4. Capability Manifest Security Declaration

### 4.1 Existing Fields

The Capability Manifest (SPEC-0001) already defines a `security` section:

```yaml
spec:
  security:
    risk: low                         # low | medium | high | critical
    network: true                     # Does this capability make network calls?
    data_access: false                # Does this access user/organization data?
    require_approval: false           # Does this require human approval?
```

**Phase 2 additions:**

```yaml
spec:
  security:
    risk: medium
    network: true
    data_access: true
    require_approval: false

    # ── New in Phase 2 ──

    # Declares what user data the capability accesses
    data_access_scope:                # Optional. Describes data access patterns
      reads:
        - files: ["*.md", "*.txt"]   # Glob patterns for files read
        - env: ["USER", "HOME"]       # Environment variables read
        - api_endpoints: []           # API endpoints called (network: true implied)
      writes:
        - files: ["output/*"]         # Glob patterns for files written
        - api_endpoints: []           # API endpoints modified

    # Declares required permissions beyond defaults
    permissions:                      # Optional. Extended permission requests
      - id: filesystem_write
        scope: "output/*"
        description: "Write generated reports to output directory"
        optional: true                # Capability can degrade if permission denied
      - id: email_send
        description: "Send notification email"
        optional: false               # Capability cannot function without this

    # Declares trust requirements
    trust:                            # Optional. Trust and verification requirements
      require_signed_manifest: false  # Require manifest to be digitally signed
      allowed_publishers: []          # Empty = any publisher allowed
      min_approval_level: "user"      # none | user | admin | compliance
```

### 4.3 Versioning Strategy

The Phase 2 additions above extend `spec.security` with optional fields. Per SPEC-0001 Section 6:

| Change | Version Bump |
|---|---|
| Add optional field to `spec.security` | **MINOR** — backward-compatible |
| Add required field to `spec.security` | **MAJOR** — breaks existing manifests |
| Remove a field from `spec.security` | **MAJOR** — breaks consumers |
| Change default value of an existing field | **MINOR** — documented in release notes |

Since all Phase 2 additions (`data_access_scope`, `permissions`, `trust`) are **optional**, a manifest versioned `1.0.0` with only basic `security.risk` remains valid. Manifests using Phase 2 security features should bump to `1.1.0` (MINOR). No `2.0.0` is required unless a future version makes any security field required.

**Parsing rule:** Parsers must treat unknown keys inside `spec.security` as unrecognized but not invalid. A manifest with Phase 2 security fields executed on a Phase 1 runtime should still work — the runtime simply ignores the advanced security declarations and applies its default policy.

### 4.2 Permission Descriptors

Permissions are a formal description of what a capability needs from the outside world.

```yaml
permissions:
  - id: filesystem_write
    type: filesystem                  # filesystem | network | process | secrets | email | ...
    scope: "output/*"
    description: "Write report files to output directory"
    risk: medium                      # Override the default risk for this permission
    optional: true                    # If denied, capability can degrade gracefully
    constraints:
      max_file_size: "10MB"
      allowed_extensions: [".md", ".pdf", ".html"]
```

**Permission types:**

| Type | Description | Default Risk |
|---|---|---|
| `filesystem_read` | Read files from the local filesystem | medium |
| `filesystem_write` | Write files to the local filesystem | high |
| `network_outbound` | Make outbound network requests | medium |
| `network_inbound` | Listen for inbound connections | high |
| `process_exec` | Execute subprocesses | critical |
| `secret_read` | Read secrets or credentials | critical |
| `email_send` | Send email | high |
| `api_modify` | Modify external API resources | high |
| `user_data_read` | Read user's personal data | medium |
| `user_data_write` | Write user's personal data | high |
| `payment_exec` | Execute financial transactions | critical |

### 4.3 Risk Level Semantics

| Level | Examples | Default Policy |
|---|---|---|
| **low** | Text summarization, translation, formatting | Auto-allow |
| **medium** | Web search, file read, data analysis | Auto-allow, logged |
| **high** | File write, email send, API modification | Require user confirmation on first use |
| **critical** | Payment execution, system administration, process execution | Require explicit approval per invocation |

---

## 5. Policy Model

### 5.1 Policy Structure

```yaml
kind: SecurityPolicy
metadata:
  name: enterprise_default
  version: 1.0.0
  publisher: org.example
  description: "Default security policy for Example Corp"

spec:
  # Which capabilities/scopes this policy applies to
  applies_to:
    capabilities:
      - "*"                           # All capabilities
      - "financial_*"                 # Or specific patterns
    workflows:
      - "production_*"
    tags:
      - "imported"
    publishers:
      - "org.intent-os"               # Trusted publishers
  
  # Risk-level overrides
  risk_overrides:
    - target: "financial_*"
      max_allowed: "high"             # Block any financial capability with risk > high
      default_action: "require_review"
  
  # Permission grants and denials
  permissions:
    allow:
      - "filesystem_read"
      - "network_outbound"
    deny:
      - "process_exec"
      - "email_send"
      - id: "payment_exec"
        unless_context:               # Conditional: allow only in specific workflows
          workflow_tags: ["approved_payment"]
  
  # Human review configuration
  review:
    require_for:
      risk: ["critical"]
      permissions: ["email_send", "payment_exec"]
      tags: ["untrusted"]
    timeout: 3600s                    # Review request expires after 1 hour
    escalation:
      first: "user"
      after: 300s                     # If user doesn't respond in 5 min
      escalate_to: "admin"
  
  # Audit configuration
  audit:
    level: "all"                      # none | decisions_only | all
    include_payload: false            # Include execution payload in audit events?
    retention_days: 90
```

### 5.2 Policy Storage

Policies are stored in the **Metadata Plane** (Policy Store), not in the Control Plane. The Policy Store is a versioned, append-only store supporting:

- CRUD operations for policy management
- Policy versioning (every change creates a new version)
- Conflict detection (overlapping policy scopes)
- Dry-run evaluation ("what would the decision be for capability X?")

### 5.3 Policy Evaluation Order

```
For a given capability execution request:

1. Load all policies where applies_to matches the capability/workflow/tag/publisher
2. Sort by specificity (most specific match wins)
   - Explicit capability name > glob pattern > wildcard
   - Explicit workflow name > workflow glob > wildcard
   - Publisher-specific > general
3. For each policy dimension (risk, permissions, review), find the most specific applicable rule
4. Apply the most restrictive interpretation across matched policies
5. Record the evaluation result as a PolicyEvaluated Event
6. Return: ALLOW | DENY | REQUIRE_REVIEW
```

---

## 6. Human-in-the-Loop Review

### 6.1 Review Flow

Some capabilities or workflows require human approval. The review flow crosses multiple planes:

```
1. Security Manager determines: REQUIRE_REVIEW
2. → Emits ReviewRequired Event (Event Bus → Data Plane)
3. → User Plane presents review request to user/approver
4.   User reviews: capability, input, risk level, requested permissions
5.   User responds: approve | deny | approve_with_restrictions
6. → Emits ReviewCompleted Event (User Plane → Event Bus)
7. → Security Manager reads ReviewCompleted from Event Bus
8. → Returns final decision
```

### 6.2 Review Event Types (SPEC-0003 Addition)

```yaml
# SPEC-0003 addition: Review events

ReviewRequired:
  payload:
    task_id: string
    capability: string               # name@version
    risk_level: string
    requested_permissions: Permission[]
    input_preview: string             # Truncated input for reviewer context
    reason: string                    # Why review was triggered
    review_token: string              # Token for correlating review request → response
    expires_at: ISO8601               # Review request expiration

ReviewCompleted:
  payload:
    task_id: string
    review_token: string              # Correlates to ReviewRequired
    approved: boolean
    reviewer: string                  # Reviewer identifier
    restrictions: Permission[] | null # Approved-with-restrictions
    feedback: string | null           # Optional reviewer notes
```

### 6.3 Auto-Deny on Timeout

If a review request expires without response, the Security Manager must default to **DENY**. This is a safety requirement — no execution proceeds on a timed-out review. The timeout duration is configurable in the policy.

---

## 7. Audit Trail

### 7.1 Security Event Types

The following Events are added to SPEC-0003's taxonomy:

| Event Type | When Emitted | Key Payload |
|---|---|---|
| `PolicyEvaluated` | Every time a policy is checked | policy_id, capability, decision, rationale |
| `PermissionGranted` | A specific permission is approved | permission_id, scope, granter |
| `PermissionDenied` | A specific permission is denied | permission_id, reason, policy_ref |
| `ReviewRequired` | Execution is blocked pending review | task_id, capability, risk_level, review_token |
| `ReviewCompleted` | Human review responded | review_token, approved, restrictions |
| `ReviewExpired` | Review timed out without response | review_token |
| `PolicyViolation` | Runtime detected behavior outside declared scope | capability, violation_type, evidence |

### 7.2 Audit Record Correlation

All security events for a single execution share a `trace_id`, enabling:

```
Trace ID: t-20260722-abc123

Events:
  WorkflowStarted        → trace_id: t-20260722-abc123
  PolicyEvaluated        → trace_id: t-20260722-abc123  ← security decision
  TaskStarted            → trace_id: t-20260722-abc123
  PermissionGranted      → trace_id: t-20260722-abc123  ← permission decision
  CapabilityInvoked      → trace_id: t-20260722-abc123
  TaskCompleted          → trace_id: t-20260722-abc123

→ Complete audit trail for this execution
→ Reproducible: replay events and verify policy decisions match
```

---

## 8. Threat Model

### 8.1 Actors

| Actor | Description | Trust Level |
|---|---|---|
| **Capability Publisher** | Writes and publishes Capability Manifests | Low — Manifests may misdeclare risk |
| **Runtime Operator** | Operates the Intent OS runtime (adapter config) | High — controls which adapters run |
| **End User** | Submits goals and approves execution | Medium — may be tricked into approving malicious workflows |
| **Policy Author** | Writes organizational security policies | High — should be trusted role |
| **Model Provider** | Provides the underlying LLM (OpenAI, Anthropic, etc.) | Depends on provider |

### 8.2 Threats and Mitigations

| # | Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| T1 | **Capability misdeclares risk** (declares `low` but performs `critical` actions) | Medium | High | Trust verification (signed manifests), runtime behavior monitoring (PolicyViolation events), capability review |
| T2 | **Malicious capability exfiltrates data** via network call | Medium | Very High | Declared `data_access` + `network` must match; runtime can strip/rewrite network calls |
| T3 | **Orchestration poisoning** — attacker controls what capabilities compose together | Medium | High | Policy scoping by publisher; signed workflows; trusted publisher allowlists |
| T4 | **Privilege escalation via workflow** — low-risk capability combined with high-risk one | Medium | Medium | Workflow-level risk aggregation: total workflow risk ≥ max(task risk) |
| T5 | **Policy bypass via adapter** — adapter fails to enforce a constraint | Low | Very High | Adapter compatibility certification; intent-os compare validates security behavior |
| T6 | **Review fatigue** — user auto-approves without reading | High | Medium | Progressive delay (auto-deny doubles timeout each skip); require different approvers for critical |
| T7 | **Manifest injection** — attacker modifies manifest between validation and execution | Low | High | Digest verification (SPEC-0001); runtime verifies digest before execution |
| T8 | **Audit flood** — attacker generates many events to hide malicious one | Medium | Low | Event Store is immutable append-only; anomaly detection in Phase 3+ |
| T9 | **MCP injection** — malicious or compromised MCP server registers harmful capabilities | Medium | High | Import-time security defaults (network: true, risk: medium); admin must review and override; MCP Server origin is recorded as publisher |
| T10 | **MCP blind spot** — security-relevant actions happen inside the MCP server outside Intent OS's audit scope | Medium | Medium | Intent OS cannot audit what it cannot see; policy should require MCP capabilities to declare all side effects explicitly; Phase 3+ may support MCP server attestation |
| T11 | **Stale MCP import** — MCP server capability evolves after import, changing its actual behavior without updating the Intent OS Manifest | Medium | High | Periodic re-import recommended; digest verification catches content changes; policy can set max_manifest_age to force re-validation |

### 8.3 Risk Aggregation

For composed workflows (SPEC-0002), the overall risk is the maximum of all task risks:

```
workflow risk = max(task_1.risk, task_2.risk, ..., task_n.risk)
```

This is a conservative model. Future versions may support context-aware aggregation:
- If tasks execute sequentially on unrelated data, the aggregate risk may be lower than the max
- If tasks share data flow (output of high-risk task feeds another), the aggregate risk compounds

---

## 9. Manifest Signing (Phase 2+)

### 9.1 Trust Chain

```
Capability Publisher
  ↓ signs manifest with private key
Signed Manifest (YAML + detached signature)
  ↓ runtime verifies against trusted publisher registry
Verified Manifest
  ↓ policy evaluation
Execution Decision
```

### 9.2 Signature Format

```yaml
metadata:
  name: financial_analyze
  version: 1.0.0
  publisher: org.example
  digest: sha256:e3b0c44298fc...
  signature:                      # Optional — present only when signed
    algorithm: ed25519
    key_id: "pub-2026-01"
    value: "MC0CFQ..."           # Base64-encoded signature
    signed_fields:               # Which fields were included in the signature
      - "metadata.name"
      - "metadata.version"
      - "metadata.publisher"
      - "spec.input"
      - "spec.output"
      - "spec.security"
      - "spec.permissions"
    timestamp: "2026-07-22T10:00:00Z"
```

### 9.3 Verification

- The runtime verifies the signature against the publisher's public key (stored in Metadata Plane)
- If `trust.require_signed_manifest` is true and the manifest is unsigned, execution is blocked
- If the manifest content differs from signed_fields, execution is blocked
- Verification result is recorded as a `PolicyEvaluated` event

### 9.4 Signature Algorithm Choice

> **Note:** This spec defines the *format* of a signed manifest (where the signature goes, what fields are covered) but does NOT mandate which signing algorithm to use. The choice of algorithm (Ed25519, ECDSA, RSA-PSS, etc.) is **implementation-defined** and outside the scope of this spec. Implementations may select algorithms based on their deployment environment's key management infrastructure. This preserves the constitutional principle: **Intent OS does not standardize intelligence — it standardizes interaction.** The format of interaction (where the signature field lives) is standardized; the cryptographic *method* is left to the implementer.

---

## 10. Policy API (Phase 2+)

### 10.1 CLI Interface

```bash
# List active policies
intent-os policy list

# Apply a policy from file
intent-os policy apply enterprise_policy.yaml

# Evaluate a capability against current policies (dry run)
intent-os policy evaluate examples/text_summarize.yaml

# View policy evaluation history
intent-os policy history

# Export audit trail for compliance
intent-os policy audit --since 2026-07-01 --format json
```

### 10.2 Audit Export Format

```yaml
compliance_report:
  period:
    start: "2026-07-01T00:00:00Z"
    end: "2026-07-22T23:59:59Z"
  
  summary:
    total_executions: 1247
    total_policy_evaluations: 1247
    approvals_granted: 1240
    approvals_denied: 5
    reviews_required: 2
    reviews_approved: 2
    reviews_denied: 0
    reviews_expired: 0
    policy_violations: 0
  
  policy_coverage:
    - policy: "enterprise_default"
      evaluations: 1247
      allows: 1240
      denies: 5
      requires_review: 2
  
  high_risk_executions:
    - trace_id: "t-abc123"
      capability: "payment_exec@1.0.0"
      decision: "allow"
      rationale: "workflow context matches approved_payment"
      reviewer: "user@example.com"
      timestamp: "2026-07-15T14:30:00Z"
  
  compliance_status: "PASS"   # PASS | FAIL | NEEDS_REVIEW
```

---

## 11. MCP Security Integration

### 11.1 Complementary Security Domains

```
MCP Security Domain:
  - Tool authentication (which client can call which tool)
  - Transport security (SSE or Streamable HTTP)
  - Tool-level authorization

Intent OS Security Domain:
  - Capability permission model (what a capability needs)
  - Workflow-level policy (composition safety)
  - Cross-runtime audit trail
  - Human review workflow
```

### 11.2 Integration Points

When Intent OS consumes an MCP server as a Capability Provider (via `import mcp-server`), the conversion process maps:

```
MCP tool definition
  → name and description become capability metadata
  → inputSchema becomes capability input schema
  → (The MCP tool has no security declaration — this is added during import)

Import-time security:
  → Imported MCP tools default to risk: medium
  → Publisher is set to the MCP server origin
  → network: true is set (all MCP calls are network calls)
  → The importing admin can override these defaults
```

---

## 12. Phase Transition Plan

### Phase 2 — Foundation (Current)

- ✅ `SecuritySpec` data model in Capability Manifest (SPEC-0001)
- ✅ `SecurityRisk` enum (low/medium/high/critical)
- ✅ Risk inheritance defaults (if omitted: `risk: low`)
- ⬜ Security Model design document (this file — complete)
- ⬜ `PolicyEvaluated` Event type in SPEC-0003
- ⬜ `ReviewRequired` / `ReviewCompleted` Event types in SPEC-0003

### Phase 2 — Implementation

- Security Manager component in Control Plane (stateless, policy evaluation only)
- Policy Store in Metadata Plane (versioned policies)
- Human review flow (User Plane integration)
- `intent-os policy` CLI subcommands

### Phase 3 — Advanced

- Manifest signing and signature verification
- Behavioral anomaly detection (PolicyViolation events)
- Automated policy suggestion (via Event Store analytics)
- Cross-registry trust federation

### Phase 4 — Ubiquitous

- Real-time policy adaptation (Evolution Loop integrates security feedback)
- Federated trust across independent Intent OS instances
- Compliance automation (auto-generated SOC2/ISO27001 evidence)

---

## 13. Validation Rules

1. **Risk consistency**: A capability's `security.risk` must be consistent with its declared `security.permissions`. E.g., a capability with `payment_exec` permission cannot declare `risk: low`.
2. **Scope coverage**: All `data_access_scope` paths and API endpoints must be covered by at least one declared permission.
3. **Publisher verification**: If `trust.allowed_publishers` is non-empty, the capability's `metadata.publisher` must appear in the list.
4. **Workflow risk aggregation**: A workflow's effective risk level is `max(task_1.risk, ..., task_n.risk)`. This value is used for policy evaluation, not individual task risks.
5. **Review timeout**: A `ReviewRequired` event without a corresponding `ReviewCompleted` before expiration auto-denies.
6. **Signature verification**: If a policy requires signed manifests, any unsigned capability's execution attempt produces a `PolicyEvaluated` event with `decision: deny`.

---

## 14. References

- SPEC-0001: Capability Manifest — `spec.security` section
- SPEC-0002: Workflow Graph — workflow-level risk aggregation
- SPEC-0003: Event Schema — `PolicyEvaluated`, `ReviewRequired`, `ReviewCompleted` events
- POSIX permissions model — for least-privilege inspiration
- Kubernetes RBAC — for policy evaluation ordering and aggregation patterns
- OAuth 2.0 scopes — for permission descriptor design
- MCP Security Specification — for complementary security domain boundaries
