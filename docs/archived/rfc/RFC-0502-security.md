# RFC-0502: Security

**Status:** Draft
**Type:** Infrastructure RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0002, RFC-0500 v1.0, RFC-0300 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Security subsystem** for Agent OS — how identities are established, how access is authorized, how Events are cryptographically signed and verified, how Capability access to sensitive resources is controlled, and how the system ensures data sovereignty and audit chain integrity. It fills the three Constitution-level gaps identified in the Architecture Review: security boundaries, data sovereignty, and audit chain integrity.

---

## 2. Motivation

The existing RFCs treat security as an implicit concern:

| Where | Gap | Source |
|-------|-----|--------|
| RFC-0500 §4 | "Event envelope has a signature field" — but who signs, who verifies, with which key? | Defined field, undefined process |
| RFC-0200 §4 | Capability accesses browser, terminal, API — but who authorizes which Capability to access which resource? | No authorization model |
| RFC-0300 §4 | Registry accepts object registrations — but who can register? Who can deprecate? | No access control |
| Constitution | Three blank Articles: security boundary, data sovereignty, audit integrity | Identified in Architecture Review Phase 5 |

Without RFC-0502:
- Any module can claim any identity (no authentication)
- Any Capability can access any resource (no authorization)
- Events can be forged (no signature verification)
- Registry objects can be modified by anyone (no access control)
- Tenant data is not isolated (no data sovereignty)

---

## 3. Security Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      SECURITY SUBSYSTEM                             │
│                                                                     │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────┐  │
│  │  Identity       │  │  Authorization  │  │  Audit               │  │
│  │  Manager        │  │  Manager        │  │  Logger              │  │
│  │                 │  │                 │  │                      │  │
│  │  · Module keys  │  │  · Policy store │  │  · Tamper-proof log  │  │
│  │  · User auth    │  │  · RBAC engine  │  │  · Hash chain        │  │
│  │  · Capability   │  │  · Resource ACLs│  │  · Periodic sealing  │  │
│  │    identity     │  │  · Scope check  │  │                      │  │
│  └────────────────┘  └────────────────┘  └──────────────────────┘  │
│                                                                     │
│  ┌────────────────┐  ┌────────────────┐                             │
│  │  Key Store      │  │  Crypto Engine  │                             │
│  │                 │  │                 │                             │
│  │  · Key gen/rot  │  │  · Sign/verify  │                             │
│  │  · HSM-backed   │  │  · Hash chain   │                             │
│  │  · Compromise   │  │  · Encrypt/dec  │                             │
│  │    recovery     │  │                 │                             │
│  └────────────────┘  └────────────────┘                             │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.1 Trust Model

Agent OS uses a **hierarchical trust model**:

```
Root of Trust (installation-time)
    │
    ├── Platform Key (identifies the Agent OS installation)
    │
    ├── Module Keys (one per module — Engine, Planner, Pool, etc.)
    │   │  Signed by Platform Key
    │   │
    │   ├── Execution Engine Key
    │   ├── Planner Key
    │   ├── Capability Pool Key
    │   ├── Registry Key
    │   ├── Event Backbone Key
    │   └── Loop Key
    │
    ├── User Keys (one per user/tenant)
    │   │  Signed by Platform Key or external IdP
    │   │
    │   └── Session Keys (derived per session)
    │
    └── Capability Instance Keys (one per loaded instance)
         Signed by Module Key (Capability Pool)
```

---

## 4. Identity & Authentication

### 4.1 Module Identity

Every module in Agent OS has a cryptographic identity:

```json
{
  "module_id": "module://execution-engine/ee-001",
  "public_key": "ed25519:abc123...",
  "signed_by": "platform-key:v1",
  "issued_at": "2026-01-01T00:00:00Z",
  "expires_at": "2027-01-01T00:00:00Z",
  "permissions": [
    "event:publish:*",
    "event:subscribe:Task:*",
    "event:subscribe:Execution:*",
    "capability:invoke:*"
  ]
}
```

Module identities are:
- **Issued at installation time** (or when a new module is added)
- **Signed by the Platform Key** (root of trust)
- **Validated on every Event publish/subscribe** (§5)
- **Revocable** via key rotation (§9)

### 4.2 User Identity

User identity may be handled by an **external Identity Provider** (IdP) or local authentication:

```json
{
  "user_id": "user://haihao",
  "auth_method": "oauth2",          // oauth2 | saml | local | api_key
  "external_id": "sub:12345@idp.example.com",
  "roles": ["admin", "developer"],
  "session": {
    "session_id": "session://finance/abc123",
    "issued_at": "2026-07-19T09:00:00Z",
    "expires_at": "2026-07-19T21:00:00Z"
  }
}
```

**v1 support:** local authentication (API key or password) + pluggable external IdP interface.

### 4.3 Capability Identity

Each loaded Capability instance has its own identity:

```json
{
  "instance_id": "inst://pool/research-v2-003",
  "capability_id": "cap://nous-research/research-v2@2.3.0",
  "public_key": "ed25519:def456...",
  "signed_by": "module://capability-pool/pool-001",
  "resource_access": [
    { "resource": "browser", "mode": "read_write" },
    { "resource": "search", "mode": "read" },
    { "resource": "network", "mode": "outbound", "allowed_hosts": ["*.sec.gov", "*.reuters.com"] }
  ]
}
```

---

## 5. Event Signing & Verification

### 5.1 When to Sign

| Event Type | Must Sign? | Signer | Verifier |
|------------|-----------|--------|----------|
| Task lifecycle events | Yes | Execution Engine | Event Store, Consumers |
| Capability invocation events | Yes | Capability Pool | Engine |
| Registry lifecycle events | Yes | Registry | All subscribers |
| Rule lifecycle events | Yes | Rule Manager | All subscribers |
| Metric/observability events | No (too high volume) | — | — |
| Heartbeat events | No | — | — |

### 5.2 Signing Process

```
publish(event)
    │
    ├─ 1. Serialize event payload to canonical JSON
    │      (sorted keys, no whitespace — deterministic)
    │
    ├─ 2. Compute hash: sha256(canonical_payload + metadata.timestamp + metadata.sequence_id)
    │
    ├─ 3. Sign hash with module's private key:
    │      signature = ed25519_sign(hash, module_private_key)
    │
    ├─ 4. Attach signature to event:
    │      event.signature = {
    │          algorithm: "ed25519",
    │          value: base64(signature),
    │          key_id: module_public_key_fingerprint
    │      }
    │
    └─ 5. Publish signed event to Event Bus
```

### 5.3 Verification Process

```
receive(event)
    │
    ├─ 1. Extract: signature, key_id, timestamp, sequence_id
    │
    ├─ 2. Lookup public key by key_id from Key Store
    │      If key not found → reject (unknown signer)
    │
    ├─ 3. Recompute canonical hash from payload + timestamp + sequence_id
    │
    ├─ 4. Verify: ed25519_verify(hash, signature, public_key)
    │      If invalid → reject (tampered event)
    │
    └─ 5. Accept event → process normally
```

### 5.4 Signature Policy

```json
{
  "signature_policy": {
    "required_events": [
      "Task:*",
      "Execution:*",
      "Capability:*",
      "Registry:*",
      "Rule:*"
    ],
    "optional_events": ["Metric:*", "Heartbeat:*"],
    "algorithm": "ed25519",
    "hash_function": "sha256",
    "key_rotation_interval_days": 90,
    "tolerance": {
      "max_clock_skew_ms": 5000,
      "max_sequence_gap": 100
    }
  }
}
```

---

## 6. Authorization

### 6.1 Resource Access Model

```
Resource          Actions                       Authorizer
──────────────    ──────────────────────────    ─────────────────
Event Bus         publish, subscribe            Identity Manager
Event Store       read, replay, snapshot        Identity Manager
Registry          register, read, update,       Registry (ACL)
                  deprecate, remove
Capability Pool   invoke, cancel, status        Security Manager
Capability Instance  execute, cancel            Security Manager
Sensitive Tools   browser, terminal, email,     Security Manager
                  ssh, git, payment
Execution Engine  execute, cancel               Security Manager
Planner           compile, replan               Security Manager
Loop              read_observability            Identity Manager
```

### 6.2 Authorization Check Flow

```
Request: { principal, action, resource, context }

    1. Identity Manager resolves principal → roles
    2. Authorization Manager looks up policy:
         policy = get_policy(role, action, resource_type)
       If no policy → DENY (default-deny)
    3. Policy evaluation:
         IF principal.role in policy.allowed_roles
            AND resource matches policy.resource_pattern
            AND context satisfies policy.conditions
         THEN ALLOW
         ELSE DENY
    4. Audit Logger records the decision (ALLOW or DENY)
```

### 6.3 Default Policies

```json
{
  "policies": [
    {
      "id": "policy://builtin/admin-full-access",
      "roles": ["admin"],
      "actions": ["*"],
      "resources": ["*"],
      "effect": "ALLOW"
    },
    {
      "id": "policy://builtin/engine-operate",
      "roles": ["engine"],
      "actions": ["invoke", "cancel"],
      "resources": ["capability_pool:/*"],
      "conditions": {
        "execution_active": true,
        "budget_available": true
      },
      "effect": "ALLOW"
    },
    {
      "id": "policy://builtin/planner-compile",
      "roles": ["planner"],
      "actions": ["read"],
      "resources": ["registry:/*"],
      "effect": "ALLOW"
    },
    {
      "id": "policy://builtin/capability-execute",
      "roles": ["capability"],
      "actions": ["execute"],
      "resources": ["tool:browser", "tool:search"],
      "conditions": {
        "allowed_hosts_match": true
      },
      "effect": "ALLOW"
    }
  ]
}
```

### 6.4 Sensitive Resource Access

Some resources require **explicit user consent** before a Capability can access them:

| Resource | Consent Required? | Consent Scope |
|----------|------------------|---------------|
| Browser (read) | No | — |
| Browser (write — form submit, login) | Yes | Per-session |
| Terminal | Yes | Per-invocation |
| Email (read) | Yes | Per-session |
| Email (send) | Yes | Per-invocation |
| SSH | Yes | Per-invocation |
| Payment API | Yes | Per-invocation |
| File system (read) | No | — |
| File system (write) | Yes | Per-session |

Consent is obtained through the Security Manager:

```json
{
  "consent_request": {
    "id": "consent://sec-mgr/001",
    "capability_id": "cap://nous-research/research-v2",
    "requested_access": [
      { "resource": "browser", "mode": "write", "justification": "Submit form for SEC filing" }
    ],
    "session_id": "session://finance/abc123",
    "expires_at": "2026-07-19T10:05:00Z"
  }
}
```

---

## 7. Data Sovereignty

### 7.1 Tenant Isolation

Agent OS supports multi-tenant deployments. Data belonging to different tenants must be isolated:

| Data Category | Isolation Granularity | Mechanism |
|---------------|----------------------|-----------|
| Execution Records | Per-tenant | Partitioned by tenant_id in Event Store |
| Knowledge | Per-tenant | Separate Knowledge Store namespace |
| Memory | Per-session (within tenant) | Key prefix: `tenant_id/session_id` |
| Registry objects | Per-tenant or global | `ns` field in identity; cross-namespace visibility controlled by policy |
| Event Store | Per-tenant or shared | Configurable at deployment time |

### 7.2 Data Deletion

When a tenant requests data deletion:

```json
{
  "deletion_request": {
    "request_id": "deletion://sec-mgr/001",
    "tenant_id": "tenant://acme-corp",
    "scope": "all",                             // all | executions_only | registry_only
    "requested_at": "2026-07-19T10:00:00Z",
    "confirm_by": "2026-07-20T10:00:00Z",
    "status": "pending"                         // pending | in_progress | completed | failed
  }
}
```

Deletion process:
1. Mark tenant data as `deletion_pending` (soft-delete)
2. Within retention period, data is retained for audit but inaccessible
3. After retention period (default: 30 days post-deletion request), data is purged
4. Execution Records are anonymized (tenant_id removed) rather than deleted (for system audit integrity)
5. Deletion is logged as an audit event

### 7.3 Data Portability

Tenants may export their data:

```json
GET /security/v1/export?tenant_id=tenant://acme-corp&format=json
→ {
    "execution_records": [...],
    "profiles": [...],
    "knowledge": [...],
    "exported_at": "2026-07-19T10:00:00Z",
    "format": "json"
  }
```

---

## 8. Audit Chain Integrity

### 8.1 Hash Chain

The Audit Logger maintains a **tamper-evident hash chain** of all audit-significant events (from RFC-0501 §8.1):

```
genesis_hash = sha256("Agent OS Audit Log v1 — 2026-01-01")

event_1 = { ... }
hash_1   = sha256(genesis_hash + canonical(event_1))

event_2 = { ... }
hash_2   = sha256(hash_1 + canonical(event_2))

...
```

Each audit event includes:
```json
{
  "audit_id": "audit://log-001/1547",
  "event_type": "Rule:Approved",
  "payload": { ... },
  "chain": {
    "previous_hash": "sha256:abc123...",
    "this_hash": "sha256:def456...",
    "position": 1547
  },
  "signed_at": "2026-07-19T10:00:00Z",
  "signature": { "algorithm": "ed25519", "value": "base64..." }
}
```

### 8.2 Chain Verification

```python
def verify_chain(audit_log):
    """Check that the hash chain is intact."""
    previous = "genesis_hash"
    for entry in audit_log:
        computed = sha256(previous + canonical(entry.payload))
        if computed != entry.chain.this_hash:
            return False, f"Break at position {entry.chain.position}"
        previous = computed
    return True, "Chain intact"
```

### 8.3 Periodic Sealing

The hash chain is periodically **sealed** — the latest hash is published to an external, immutable store (e.g., a public blockchain, a trusted timestamp service, or a separate secure store):

```
Every 24 hours:
    latest_hash = audit_log.last().chain.this_hash
    seal(latest_hash, external_anchor)

On audit verification:
    # Verify the chain is intact (hash chain check)
    # Verify the latest sealed hash matches the chain's last hash
    # If both pass: the audit log has not been tampered with
```

---

## 9. Key Management

### 9.1 Key Types

| Key Type | Algorithm | Lifetime | Purpose |
|----------|-----------|----------|---------|
| Platform Key | ed25519 | 5 years | Root of trust; signs module keys |
| Module Key | ed25519 | 1 year | Module identity; signs Events |
| User Key | ed25519 | Depends on IdP | User authentication |
| Session Key | ed25519 | Session duration | Per-session operations |
| Capability Instance Key | ed25519 | Instance lifetime | Capability identity |
| Audit Seal Key | ed25519 | 5 years | Audit chain sealing |

### 9.2 Key Rotation

```json
{
  "key_rotation": {
    "policy": "auto",                     // auto | manual
    "schedule": {
      "platform_key": { "interval_days": 1825, "overlap_days": 30 },
      "module_key":   { "interval_days": 365,  "overlap_days": 7 },
      "session_key":  { "interval_days": 1,    "overlap_days": 0 }
    },
    "compromise_recovery": {
      "revoke_immediately": true,
      "reissue_all_signed_keys": true,
      "audit_event": "Security:KeyCompromised"
    }
  }
}
```

### 9.3 Key Store

Keys are stored in a **hardware-backed or encrypted key store**:

| Backend | v1 Support | Production Readiness |
|---------|-----------|---------------------|
| OS keychain (Windows Credential Manager, macOS Keychain) | Yes | Development only |
| Encrypted file (AES-256-GCM, key derived from passphrase) | Yes | Low-security |
| HSM (YubiHSM, Azure Key Vault, AWS KMS) | No (v2) | Production |

**v1 default:** Encrypted file. The encryption key is derived from a user-provided master passphrase.

---

## 10. Security Manager API

```json
// Authenticate a module
POST /security/v1/authenticate
  Body: { module_id, signed_challenge }
→ { token: "jwt...", expires_at: "..." }


// Authorize an action
POST /security/v1/authorize
  Body: { principal, action, resource, context }
→ { authorized: true/false, policy_id: "..." }


// Sign data
POST /security/v1/sign
  Body: { data, key_id }
→ { signature: "base64...", algorithm: "ed25519" }


// Verify signature
POST /security/v1/verify
  Body: { data, signature, key_id }
→ { valid: true/false, signer: "module://...", verified_at: "..." }


// Request consent for sensitive resource access
POST /security/v1/consent
  Body: { capability_id, requested_access, session_id }
→ { consent_id: "...", status: "pending" | "granted" | "denied" }


// Export tenant data (data portability)
GET /security/v1/export?tenant_id=...&format=json
→ { ... }


// Get audit chain status
GET /security/v1/audit/status
→ { chain_length: 1547, last_sealed_at: "...", chain_integrity: true }
```

---

## 11. Compliance

Any implementation claiming Agent OS Security compatibility **must**:

1. Implement module identity with cryptographic keys as defined in §4.1
2. Support user authentication via local or external IdP (§4.2)
3. Sign all required Event types with ed25519 (§5.1, §5.2)
4. Verify Event signatures on receipt (§5.3)
5. Implement the authorization model with default-deny (§6.2)
6. Require user consent for sensitive resource access (§6.4)
7. Support tenant data isolation and deletion (§7.1, §7.2)
8. Maintain a tamper-evident hash chain of audit events (§8.1)
9. Seal the audit chain periodically (§8.3)
10. Support key rotation as defined in §9.2

---

## 12. Open Questions

1. **External IdP integration** — should v1 support OAuth2/OIDC directly, or is a plugin interface sufficient?
2. **Audit seal target** — what external store should the periodic seal target in v1? (A public blockchain is expensive; a separate encrypted log may suffice.)
3. **Capability sandboxing** — should the OS enforce resource access at the OS level (seccomp, containerization) or at the application level only?
4. **Emergency access** — should there a break-glass mechanism for administrators to bypass authorization in emergencies?

---

## 13. Constitutional Amendments

This RFC fills three gaps in the Architectural Constitution:

### Proposed Article 13: Security Boundary

> The Security Manager is the sole authority for authentication, authorization, and cryptographic operations. All Event signatures must be verified before acceptance. All resource access must be authorized before execution, with default-deny for any action not explicitly permitted.

### Proposed Article 14: Data Sovereignty

> Tenant data must be isolated at the storage layer. No module may access data belonging to a different tenant unless explicitly authorized by policy. Data deletion requests must be honored within the configured retention period. Execution Records may be anonymized but not deleted (audit integrity).

### Proposed Article 15: Audit Integrity

> All audit-significant state changes must be recorded in a tamper-evident hash chain. The chain must be sealed periodically to an external anchor. Any break in the chain must be treated as a security incident.

---

## 14. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.9 | Event envelope (signature field defined here) |
| RFC-0500 §4 | Event envelope (signature field — this RFC fills in the process) |
| RFC-0300 §4 | Registry registration (this RFC defines who can register) |
| RFC-0200 §4 | Capability invocation (this RFC defines authorization for resource access) |
| RFC-0200 §4.7 | Error codes (`authentication_failed` defined here) |
| RFC-0501 §8 | Audit Trail (hash chain feeds audit events) |
| Constitution (current) | Missing Articles 13, 14, 15 — now proposed above |
| Architecture Review Phase 5 | Identified Security/Data/Audit as Constitutional gaps |
