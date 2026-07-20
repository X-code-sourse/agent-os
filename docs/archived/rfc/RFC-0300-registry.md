# RFC-0300: Registry

**Status:** Draft
**Type:** Metadata RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0100 v1.0, RFC-0104 v1.0, RFC-0201 v1.0, RFC-0202 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Metadata Registry** — the Metadata Plane's central store for all definition objects: Workflows, Rules, Capability Manifests, and Profiles. The Registry is the **sole discovery entry point** (Constitution Article 11): no module hardcodes references to specific implementations. All matching (RFC-0202), scope resolution (RFC-0104), and compilation (RFC-0101) depend on the Registry.

---

## 2. Motivation

The existing RFCs define the *format* of objects that must be stored and queried:

| Object | Format RFC | How It's Discovered |
|--------|-----------|---------------------|
| Capability Manifest | RFC-0201 | Negotiation (RFC-0202) — by type, domain, quality, cost |
| Rule | RFC-0104 | Scope resolution — by workflow pattern, task type, domain |
| Workflow | RFC-0100 | Workflow Resolver — by name, version |
| Profile | SPEC-0000 §3.6 | Direct reference — by profile_id |

But none of these RFCs define *where* these objects live, *how* they're stored, *how* they're versioned, or *how* the Registry indexes them for efficient lookup and matching. Without a Registry specification:

- Every implementation builds its own ad-hoc storage
- Cross-object references (a Plan binds a Capability that references a Manifest) are unverifiable
- Migration between Registry backends (SQLite → PostgreSQL → distributed) has no standard
- The Constitution's "sole discovery entry point" is an abstract statement without a concrete implementation contract

---

## 3. Objects Managed by the Registry

The Registry manages exactly four object types (all Definition Objects from SPEC-0000 §2):

| Object | Identity Pattern | Versioned? | Content |
|--------|-----------------|------------|---------|
| Workflow | `wf://<ns>/<name>@<version>` | Yes | DAG of stages, requirements (RFC-0100) |
| Rule | `rule://<ns>/<name>@<version>` | Yes | Scope, constraints, governance (RFC-0104) |
| Capability Manifest | `cap://<provider>/<name>@<version>` | Yes | Type, domains, schemas, performance (RFC-0201) |
| Profile | `profile://<ns>/<name>@<version>` | Yes | Capability configs, model prefs, budget (SPEC-0000) |

### 3.1 Storage Schema (Logical)

All objects share a common storage envelope:

```json
{
  "object_id": "cap://nous-research/research-v2",
  "version": "2.3.0",
  "kind": "capability_manifest",
  "status": "active",

  "body": { /* object-specific content — the YAML/JSON from its defining RFC */ },

  "metadata": {
    "created_at": "2026-01-15T10:00:00Z",
    "updated_at": "2026-06-01T14:30:00Z",
    "author": "provider:nous-research",
    "checksum": "sha256:abc123..."
  },

  "indexable_fields": {
    "type": "research",
    "domains": ["finance", "technology"],
    "languages": ["en", "zh"],
    "quality_score": 0.94,
    "cost_per_call": 0.02,
    "avg_latency_ms": 2500,
    "features": ["citation", "web_search"],
    "models": ["claude-sonnet-4", "gpt-4o"],
    "workflow_patterns": null     // Only populated for Rules
  }
}
```

The `indexable_fields` are a **denormalized extraction** of search-relevant fields from the `body`. This enables efficient filtering without parsing the full body on every query.

---

## 4. Object Lifecycle

### 4.1 Lifecycle States

```
[Draft] ──► [Published] ──► [Deprecated] ──► [Removed]
               │
               └──► [Superseded] (newer version published)
```

| State | Definition | Visible in Discovery? | Accepts New References? |
|-------|------------|----------------------|------------------------|
| `draft` | Being authored; not yet discoverable | No | No |
| `published` | Fully active and discoverable | Yes | Yes |
| `deprecated` | Will be removed on `sunset_date` | Yes (with deprecation notice) | Existing references valid; no new references from Plans |
| `superseded` | Replaced by a newer version | Yes (redirect to successor) | No (redirect to newer version) |
| `removed` | Permanently deleted from active storage | No | No |

### 4.2 Registration Flow

```
Publisher                              Registry
   │                                      │
   │── Register(Object) ────────────────►│
   │    { object_id, version, kind, body }│
   │                                      │
   │                                      ├─ 1. Validate body against schema
   │                                      │    (schema depends on kind)
   │                                      │
   │                                      ├─ 2. Check version uniqueness
   │                                      │    (id@version must not exist)
   │                                      │
   │                                      ├─ 3. Extract indexable_fields
   │                                      │    (denormalize for fast querying)
   │                                      │
   │                                      ├─ 4. Store with status=published
   │                                      │
   │                                      ├─ 5. Mark previous version as superseded
   │                                      │    (if this is a MAJOR/MINOR update)
   │                                      │
   │                                      └─ 6. Publish Registry:ObjectRegistered
   │
   │◄── Registered ───────────────────────│
   │    { object_id, version, status }
```

### 4.3 Deprecation Flow

```
Publisher                              Registry
   │                                      │
   │── Deprecate(Object) ───────────────►│
   │    { object_id, sunset_date, reason }│
   │                                      │
   │                                      ├─ 1. Set status=deprecated
   │                                      ├─ 2. Set sunset_date
   │                                      ├─ 3. Publish Registry:ObjectDeprecated
   │                                      │
   │                                      └─ 4. Notify Capability Pool (if Manifest)
   │                                              Pool drains instances
```

---

## 5. Versioning

### 5.1 Version Storage

Every object version is stored independently. The Registry maintains a **version chain**:

```
cap://nous-research/research-v2
├── @2.1.0  (published)  ── superseded by → @2.2.0
├── @2.2.0  (published)  ── superseded by → @2.3.0
├── @2.3.0  (published)  ← latest
└── @3.0.0  (draft)      ← not yet published
```

### 5.2 Version Resolution

| Strategy | Behavior | Used By |
|----------|----------|---------|
| `pinned` | Return exactly `id@version` | Execution Plans (deterministic replay) |
| `latest` | Return `id@latest( status=published )` | Workflow Resolver (always use newest) |
| `range` | Return `id@max( version within [range] )` | Rule resolution with compatibility range |

### 5.3 Latest Version Cache

The Registry maintains a `latest_version` pointer per object_id that is updated atomically when a new version is published. This enables O(1) latest-version lookup without scanning the version chain.

---

## 6. Indexing for Negotiation

### 6.1 Index Structure

The Registry maintains **secondary indexes** on `indexable_fields` to support fast Capability Negotiation (RFC-0202):

```
Index: capability_type
  Key: type (string) → Value: set of { object_id, version }

Index: domain
  Key: domain (string) → Value: set of { object_id, version }

Index: domain_coverage
  Key: domain (string) → Value: set of { object_id, domain_overlap_count }
  (For multi-domain queries — finds Capabilities supporting ALL required domains)

Index: features
  Key: feature (string) → Value: set of { object_id, version }

Index: performance_range
  Key: (quality_score_bucket, cost_bucket, latency_bucket)
  → Value: set of { object_id, version }
  (Bucketed for range queries: quality >= 0.85)
```

### 6.2 Negotiation Query Optimization

The Registry optimizes RFC-0202 negotiations using these indexes:

```python
def negotiate(request):
    # Step 1: Type filter — direct index lookup
    candidates = index.capability_type.get(request.requirements.capability_type)

    # Step 2: Domain filter — only candidates supporting ALL required domains
    for domain in request.requirements.domain:
        candidates = candidates ∩ index.domain.get(domain)

    # Step 3: Feature filter — only candidates supporting ALL required features
    for feature in request.requirements.required_features:
        candidates = candidates ∩ index.features.get(feature)

    # Step 4: Performance filter — scan remaining candidates
    candidates = [c for c in candidates
                  if c.quality_score >= request.requirements.quality_min
                  and c.cost_per_call <= request.requirements.cost_max]

    # Step 5: Rank and return
    return rank(candidates, request.profile_preferences)
```

### 6.3 Index Maintenance

| Event | Index Action |
|-------|-------------|
| Object registered | Insert into all applicable indexes |
| Object deprecated | Remove from indexes (keep in storage for existing references) |
| Object removed | Remove from indexes and storage |
| Object version superseded | Update indexes to point to new latest version |

---

## 7. Discovery API

### 7.1 Query Interface

```json
// List objects by kind, with optional filters
GET /registry/v1/objects?kind=capability_manifest&status=published&type=research&domain=finance
→ {
    "objects": [
      { "object_id": "cap://nous-research/research-v2@2.3.0", "kind": "capability_manifest", ... }
    ],
    "total": 3,
    "page": 1
  }


// Get a specific object version
GET /registry/v1/objects/cap://nous-research/research-v2@2.3.0
→ { "object_id": "...", "version": "2.3.0", "kind": "capability_manifest", "body": {...} }


// Resolve version (pinned, latest, or range)
GET /registry/v1/resolve?object_id=cap://nous-research/research-v2&strategy=latest
→ { "object_id": "cap://nous-research/research-v2", "resolved_version": "2.3.0", "body": {...} }


// Negotiate (RFC-0202 endpoint)
POST /registry/v1/negotiate
  Body: { requirements, profile_preferences, context }
  Response: { matched, matches, failure?, negotiation_metadata }


// Scope resolution (RFC-0104 endpoint — match Rules to a Workflow)
POST /registry/v1/resolve-rules
  Body: { workflow_ref, stage_type, domains }
  Response: { rules: [{ rule_id, version, constraints }] }
```

### 7.2 Event Subscription Interface

Clients can subscribe to Registry events:

```json
// Subscribe to changes
POST /registry/v1/subscribe
  Body: { kinds: ["capability_manifest", "rule"], events: ["registered", "deprecated"] }
→ { subscription_id: "sub://registry_001/..." }


// Events delivered via Event Bus
{
  "event_type": "Registry:ObjectRegistered",
  "payload": {
    "object_id": "cap://nous-research/research-v2",
    "version": "2.4.0",
    "kind": "capability_manifest",
    "status": "published"
  }
}
```

---

## 8. Cross-Object Reference Integrity

### 8.1 References Between Objects

Objects in the Registry may reference each other. The Registry **validates** references at registration time:

| Object | References | Validation Rule |
|--------|-----------|----------------|
| Workflow | Rules (in `stages` via constraint IDs) | Referenced rule_ids must exist in Registry |
| Execution Plan | Workflow + Rules + Capability + Profile | All must exist at their pinned versions |
| Profile | Capability Manifests (in `capability_configs`) | Referenced capability_ids must exist |
| Rule | Workflows (in `scope.workflows` via glob) | At least one workflow must match the glob |

### 8.2 Reference Validation on Registration

```json
// Register a Workflow that references rules
POST /registry/v1/objects
  Body: {
    "object_id": "wf://finance/stock-research",
    "version": "2.1.0",
    "kind": "workflow",
    "body": {
      "stages": [
        { "constraint_ids": ["rule://finance/sec-filing"] }
      ]
    }
  }
→ {
    "registered": true,
    "warnings": [
      { "type": "reference_not_found",
        "object_id": "rule://finance/sec-filing",
        "note": "Rule exists but only in draft state; not yet approved" }
    ]
  }
```

### 8.3 Cascading Deprecation Warning

When an object is deprecated, the Registry identifies all objects that reference it:

```
Deprecate: cap://nous-research/research-v2@2.3.0
    ↓
    References from:
    - Profile: profile://finance/deep@1.0.0 (capability_configs references this)
    - Execution Plans: 47 active plans bind to this version
    ↓
    Registry publishes: Registry:DependentsWarning
    { object_id, dependents: [{ profile://finance/deep }, ...] }
```

---

## 9. Registry Implementation Requirements

### 9.1 Backend-Agnostic Contract

The Registry API is backend-agnostic. Implementations may use:

| Backend | Suitable For | Considerations |
|---------|-------------|----------------|
| SQLite | Development, single-user | No concurrent writes |
| PostgreSQL | Production, multi-user | Indexes for negotiation queries |
| etcd / Consul | Distributed, HA | Value size limits (typically 1–4 MB) |
| S3 + Index | Large objects, archival | Higher latency for index queries |

The Registry must implement the full API surface from §7 regardless of backend.

### 9.2 Minimum Performance Requirements

| Operation | P99 Latency | Throughput |
|-----------|-------------|------------|
| Object registration | 500ms | 100/s |
| Object lookup by ID | 50ms | 1000/s |
| Version resolution | 50ms | 1000/s |
| Negotiation (RFC-0202) | 200ms | 100/s |
| Scope resolution (RFC-0104) | 200ms | 100/s |

### 9.3 Caching Layer

The Registry may implement an optional caching layer:

```
Client → Cache (LRU, TTL=60s) → Registry Backend
```

Cache invalidation:
- On `Registry:ObjectRegistered` event → invalidate affected negotiation cache entries
- On `Registry:ObjectDeprecated` event → invalidate affected entries
- Cache TTL: 60s maximum (stale metadata leads to incorrect negotiation results)

---

## 10. Compliance

Any implementation claiming Agent OS Registry compatibility **must**:

1. Support storage and versioning of all four object types (§3)
2. Implement the full object lifecycle (§4): register, deprecate, remove, supersede
3. Implement version resolution with `pinned`, `latest`, and `range` strategies (§5)
4. Maintain negotiation indexes as defined in §6 (type, domain, feature, performance)
5. Implement the full Discovery API from §7
6. Implement the Negotiation endpoint (RFC-0202) and Scope Resolution endpoint (RFC-0104)
7. Validate cross-object references at registration time (§8)
8. Support event publishing for lifecycle changes (§7.2)
9. Meet the minimum performance requirements from §9.2

---

## 11. Open Questions

1. **Multi-tenant isolation** — should the Registry support namespaced visibility (e.g., `private` vs `public` Manifests within the same Registry)?
2. **Soft deletion** — should `removed` objects be hard-deleted or soft-deleted with a retention period?
3. **Registry federation** — should a Registry be able to query another Registry and merge results in a negotiation response?
4. **Schema evolution** — if a future RFC extends the object schema (adds a field), how does the Registry handle mixed-version objects?

---

## 12. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §2 | Object Classification (Definition Objects live here) |
| SPEC-0000 §3.3 | Workflow entity |
| SPEC-0000 §3.5 | Rule entity |
| SPEC-0000 §3.6 | Profile entity |
| SPEC-0000 §3.7 | Capability Manifest entity |
| SPEC-0000 §5 | Identity Convention |
| RFC-0100 | Workflow Specification (format of stored Workflows) |
| RFC-0104 | Rule Resolution (scope matching queries the Registry) |
| RFC-0201 | Capability Manifest (format of stored Manifests) |
| RFC-0202 | Capability Negotiation (Registry implements the negotiation endpoint) |
| RFC-0101 §4 | Planner's negotiation protocol (calls Registry) |
| RFC-0101 §3, Pass 3 | Rule Injection (calls Registry for scope resolution) |
| Constitution Article 11 | Metadata Registry is the only discovery entry point |
