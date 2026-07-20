# RFC-0202: Capability Negotiation

**Status:** Draft
**Type:** Runtime RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0101 v1.0, RFC-0200 v1.0, RFC-0201 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Capability Negotiation Protocol** — the formal interface between the Planner (compile time) and the Registry for matching Capability Requirements (RFC-0100 §6) against Capability Manifests (RFC-0201). It specifies the request/response schema, matching algorithm, ranking and tie-breaking, failure modes, caching, and the negotiation boundary between compile time and runtime.

---

## 2. Motivation

RFC-0101 §4 defines the Planner's side of negotiation: it sends Requirements, receives ranked matches, applies Profile preferences, selects a winner. But that RFC is from the Planner's perspective. It does not define the **Registry's formal interface** — the API endpoint, the exact matching semantics, the response format, or the caching contract.

Without RFC-0202:

- Every Registry implementation invents its own query language
- The matching algorithm is scattered across implementations
- There is no standard response format that the Planner can depend on
- Partial matches and negotiation failures have no formal handling
- Third-party Registry implementations cannot participate in the ecosystem

---

## 3. Protocol Overview

```
Planner (compile time)              Registry                     Capability Pool
      │                                │                              │
      │── Negotiate(Request) ────────►│                              │
      │                                │                              │
      │                                ├─ 1. Cache lookup            │
      │                                │    (key = hash of Request)  │
      │                                │                              │
      │                                ├─ 2. If cache miss:          │
      │                                │    a. Filter Manifests      │
      │                                │    b. Rank survivors        │
      │                                │    c. Apply preferences     │
      │                                │                              │
      │◄── Negotiate(Response) ────────│                              │
      │    { matched: true/false,      │                              │
      │      matches: [...],           │                              │
      │      negotiation_id }          │                              │
      │                                │                              │
      │  [Planner selects best match,  │                              │
      │   applies Profile overrides]   │                              │
      │                                │                              │
      │── ConfirmBinding(Request) ────►│                              │
      │    { stage_id, capability_id } │                              │
      │                                │── Reserve(cap, quota) ────►│
      │                                │                              │
```

### 3.1 Protocol Roles

| Role | Module | Responsibility |
|------|--------|----------------|
| **Requester** | Planner (RFC-0101 §4) | Sends Requirements, receives matches, applies Profile preferences, selects winner |
| **Resolver** | Registry (this RFC) | Filters Manifests by matching rules, ranks survivors, returns structured response |
| **Reservation Keeper** | Registry (this RFC) | Optionally tracks binding confirmations for quota management |

### 3.2 Compile-Time vs Runtime Negotiation

| Phase | Trigger | Who Initiates | Cacheable? |
|-------|---------|---------------|------------|
| Compile time | Planner Pass 6 (Capability Bind) | Planner | Yes — Plan caching covers this |
| Runtime (fallback) | Pool cannot load bound Capability | Execution Engine | No — runtime conditions may change |
| Runtime (replan) | Replan requires new Capability | Engine → Planner | No — failure context matters |

---

## 4. Negotiation Request

### 4.1 Request Schema

```json
{
  "request_type": "capability_negotiation",
  "negotiation_id": "neg://planner_001/003",

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
    "preferred_models": ["claude-sonnet-4", "gpt-4o"],
    "cost_budget": { "max_per_task": 0.5 },
    "quality_weight": 0.50,
    "cost_weight": 0.25,
    "latency_weight": 0.25
  },

  "context": {
    "workflow_ref": "wf://finance/stock-research@2.1.0",
    "stage_id": "financial_analysis",
    "execution_id": "exec://finance/abc123",
    "requested_at": "2026-07-19T10:00:02.000Z"
  }
}
```

### 4.2 Request Field Definitions

| Field | Required | Source | Description |
|-------|----------|--------|-------------|
| `requirements.capability_type` | Yes | Workflow stage | The broad capability type (research, python, browser...) |
| `requirements.domain` | Yes | Workflow stage | Required domain expertise. ALL must be supported by the Manifest |
| `requirements.language` | Yes | Workflow stage | Primary language. BCP 47 code |
| `requirements.quality_min` | No | Workflow or Profile | Minimum acceptable quality score. Default: 0.0 |
| `requirements.cost_max` | No | Workflow or Profile | Maximum cost per invocation. Default: unbounded |
| `requirements.latency_max_ms` | No | Workflow or Profile | Maximum latency. Default: unbounded |
| `requirements.required_features` | No | Workflow stage | ALL must be present in Manifest `features.supported` |
| `profile_preferences.preferred_models` | No | Profile | Ordered list; Registry ranks matches using these models first |
| `profile_preferences.cost_budget` | No | Profile | Per-task budget; Registry filters matches exceeding this |
| `profile_preferences.quality_weight` | No | Profile | Override for ranking algorithm weight (default: 0.50) |
| `profile_preferences.cost_weight` | No | Profile | Override for ranking algorithm weight (default: 0.25) |
| `profile_preferences.latency_weight` | No | Profile | Override for ranking algorithm weight (default: 0.25) |

---

## 5. Negotiation Response

### 5.1 Response Schema (Success)

```json
{
  "negotiation_id": "neg://planner_001/003",
  "matched": true,
  "response_type": "capability_negotiation",

  "matches": [
    {
      "rank": 1,
      "score": 0.912,
      "capability": {
        "manifest_id": "cap://nous-research/research-v2",
        "version": "2.3.0",
        "name": "Nous Research v2",
        "provider": "Nous Research"
      },
      "performance": {
        "quality_score": 0.94,
        "avg_latency_ms": 2500,
        "p95_latency_ms": 5000,
        "cost_per_call": 0.02,
        "cost_per_token": 0.000003
      },
      "model": "claude-sonnet-4",
      "match_details": {
        "type_matched": true,
        "domains_matched": ["finance", "sec_filing"],
        "language_matched": "en",
        "quality_met": true,
        "cost_met": true,
        "latency_met": true,
        "features_matched": ["citation", "source_attribution"]
      }
    },
    {
      "rank": 2,
      "score": 0.781,
      "capability": {
        "manifest_id": "cap://community-research/research-lite",
        "version": "1.1.0",
        "name": "Research Lite",
        "provider": "Community Research"
      },
      "performance": {
        "quality_score": 0.80,
        "avg_latency_ms": 800,
        "cost_per_call": 0.005
      },
      "model": "gpt-4o-mini",
      "match_details": {
        "type_matched": true,
        "domains_matched": ["finance"],
        "language_matched": "en",
        "quality_met": false,
        "quality_note": "Manifest quality 0.80 < requirement 0.85",
        "cost_met": true,
        "latency_met": true,
        "features_matched": ["citation"]
      }
    }
  ],

  "negotiation_metadata": {
    "candidates_considered": 8,
    "candidates_filtered": 6,
    "candidates_returned": 2,
    "negotiation_duration_ms": 45,
    "cache_hit": false
  }
}
```

### 5.2 Response Schema (No Match)

```json
{
  "negotiation_id": "neg://planner_001/003",
  "matched": false,
  "response_type": "capability_negotiation",

  "failure": {
    "reason": "no_capability_matches_requirements",
    "detail": "No capability satisfies: type=research, domain=[finance, sec_filing], quality_min=0.85",
    "blocking_constraints": [
      {
        "constraint": "domain",
        "required": ["finance", "sec_filing"],
        "available_options": ["finance", "technology", "general"]
      },
      {
        "constraint": "quality_min",
        "required": 0.85,
        "max_available": 0.80
      }
    ],
    "suggestions": [
      "Lower quality_min to 0.80 (max available: 0.80)",
      "Remove sec_filing domain requirement (no capability supports it)",
      "Check if research capability is registered and active"
    ]
  },

  "negotiation_metadata": {
    "candidates_considered": 5,
    "candidates_filtered": 5,
    "candidates_returned": 0,
    "negotiation_duration_ms": 12,
    "cache_hit": false
  }
}
```

---

## 6. Matching Algorithm

### 6.1 Filtering Stage (Hard Constraints)

Every Requirement field corresponds to a Manifest field. The Registry filters by checking each constraint:

| Requirement Field | Manifest Field | Match Rule |
|-------------------|----------------|------------|
| `capability_type` | `type` | Exact string match (case-sensitive) |
| `domain` | `supported_domains` | Requirement domains are a **subset** of Manifest domains (∀d ∈ requirement.domains: d ∈ manifest.supported_domains) |
| `language` | `supported_languages` | Exact match on BCP 47 code |
| `quality_min` | `performance.quality_score` | `manifest.quality_score >= requirement.quality_min` |
| `cost_max` | `performance.cost_per_call` | `manifest.cost_per_call <= requirement.cost_max` |
| `latency_max_ms` | `performance.avg_latency_ms` | `manifest.avg_latency_ms <= requirement.latency_max_ms` |
| `required_features` | `features.supported` | Requirement features are a **subset** of Manifest features (∀f ∈ requirement.required_features: f ∈ manifest.features.supported) |

**Filtering is strict:** any constraint that is not met excludes the Manifest from the candidate pool.

### 6.2 Ranking Stage (Soft Scoring)

Surviving candidates are ranked using a weighted scoring formula:

```
score(capability) = (
    quality_weight * normalize(quality_score, 0, 1) +
    cost_weight * (1 - normalize(cost_per_call, min_cost_in_pool, max_cost_in_pool)) +
    latency_weight * (1 - normalize(latency_ms, min_latency_in_pool, max_latency_in_pool))
)
```

**Where:**
- `quality_weight` = `profile_preferences.quality_weight` (default: 0.50)
- `cost_weight` = `profile_preferences.cost_weight` (default: 0.25)
- `latency_weight` = `profile_preferences.latency_weight` (default: 0.25)
- Weights must sum to 1.0 (± 0.01)
- `normalize(x, min, max)` = `(x - min) / (max - min)`; if min == max, normalize to 0.5

### 6.3 Tie-Breaking

When two candidates have the same score (within 0.001):

1. **Higher quality_score** wins
2. If still tied: **lower cost_per_call** wins
3. If still tied: **lower avg_latency_ms** wins
4. If still tied: **alphabetical by manifest_id** (deterministic)

### 6.4 Model Preference Filtering

Before ranking, if `profile_preferences.preferred_models` is provided:

1. For each Manifest, check if any of its `required_environment.models` overlap with the preferred models list
2. **If overlap exists:** the Manifest survives (the overlapping model is noted in the response)
3. **If no overlap:** the Manifest is not removed (it survives as a lower-ranked fallback), BUT it receives a `model_preference_note` in its match_details

```
After filtering hard constraints:
    Manifest A: models=[claude-sonnet-4, gpt-4o]  → overlap with preferred → survives at full rank
    Manifest B: models=[gemini-pro]                 → no overlap → survives at penalized rank
```

Model preference is a **soft** constraint — it influences ranking but does not exclude.

---

## 7. Binding Confirmation

After the Planner selects a match, it **confirms the binding** with the Registry:

```json
// ConfirmBinding Request (Planner → Registry)
{
  "request_type": "binding_confirmation",
  "negotiation_id": "neg://planner_001/003",
  "stage_id": "financial_analysis",
  "selected": {
    "manifest_id": "cap://nous-research/research-v2",
    "version": "2.3.0",
    "model": "claude-sonnet-4"
  },
  "execution_id": "exec://finance/abc123",
  "estimated_invocations": 1
}

// ConfirmBinding Response (Registry → Planner)
{
  "confirmed": true,
  "manifest_id": "cap://nous-research/research-v2@2.3.0",
  "reservation": {
    "reservation_id": "res://registry_001/005",
    "expires_at": "2026-07-19T10:05:00Z"
  }
}
```

The binding confirmation serves two purposes:
1. **Quota reservation** — the Registry may reserve capacity on the Capability Pool
2. **Audit trail** — the Registry records which Plan binds to which Capability

If the Registry cannot confirm (e.g., the Manifest was deprecated between negotiation and confirmation):

```json
{
  "confirmed": false,
  "reason": "manifest_deprecated",
  "alternatives": [
    "cap://nous-research/research-v2@2.4.0",
    "cap://community-research/research-lite@1.2.0"
  ]
}
```

---

## 8. Caching

### 8.1 Cache Key

```
cache_key = sha256(concat(
    requirements.capability_type,
    sorted(requirements.domain),
    requirements.language,
    str(requirements.quality_min) if set,
    str(requirements.cost_max) if set,
    str(requirements.latency_max_ms) if set,
    sorted(requirements.required_features) if set,
    sorted(profile_preferences.preferred_models) if set,
    str(profile_preferences.cost_budget.max_per_task) if set,
    str(profile_preferences.quality_weight),
    str(profile_preferences.cost_weight),
    str(profile_preferences.latency_weight)
))
```

### 8.2 Cache Invalidation

| Event | Action |
|-------|--------|
| Manifest registered | Invalidate all cache entries that could match the new Manifest |
| Manifest version published | Invalidate cache entries referencing that manifest_id |
| Manifest deprecated | Invalidate cache entries referencing that manifest_id |
| Manifest performance updated (Loop-verified) | Invalidate cache entries referencing that manifest_id |
| Cache TTL expired (default: 5 minutes) | Recompute |

### 8.3 Bypass Conditions

Negotiation caching is bypassed when:

- `context.execution_id` is a replan (replan must get fresh results)
- Profile specifies `negotiation_cache: "never"`
- The Registry has detected a recent change to Manifests in the candidate pool

---

## 9. Negotiation Failure Modes

### 9.1 No Match

**Symptom:** `matched: false`, `failure.reason = "no_capability_matches_requirements"`

**Cause:** Every Manifest failed at least one hard constraint from §6.1.

**Planner action:**
1. Read `failure.blocking_constraints` to identify which constraints are blocking
2. If `quality_min` or `cost_max` are blocking: relax constraint and re-negotiate
3. If `domain` or `capability_type` are blocking: compilation fails with clear error to Workflow author
4. If `required_features` are blocking: compilation fails; Workflow author must remove feature requirement or add a Capability that supports it

### 9.2 Partial Match

**Symptom:** `matched: true` but some `match_details.*_met` fields are `false`

**Example:** A Manifest matches on type, domain, language, cost, and latency, but its `quality_score` (0.82) is below `quality_min` (0.85).

**Planner action:**
1. Check `profile_preferences` — if the Profile does not require the constraint, the Planner may still select the partial match
2. If the constraint is mandatory: exclude this candidate, use the next-ranked one
3. If no candidates pass all mandatory constraints: treat as No Match (§9.1)

### 9.3 Binding Deprecated

**Symptom:** Binding confirmation fails with `"manifest_deprecated"`

**Planner action:** Re-run negotiation (the new version of the Manifest will be in the candidate pool). The cache will be bypassed for this request.

### 9.4 Negotiation Timeout

**Symptom:** Registry does not respond within `negotiation_timeout` (default: 5s)

**Planner action:** Fall back to local cache (compile-time cached negotiation result). If no local cache available, compilation fails.

---

## 10. Registry Query Interface

### 10.1 API Surface

```
// Negotiate: match Requirements against Manifests
POST /registry/v1/negotiate
  Body: NegotiateRequest (§4.1)
  Response: NegotiateResponse (§5.1 / §5.2)

// ConfirmBinding: reserve a selected match
POST /registry/v1/confirm-binding
  Body: ConfirmBindingRequest (§7)
  Response: ConfirmBindingResponse (§7)

// InvalidateCache: force cache invalidation
POST /registry/v1/invalidate-cache
  Body: { cache_key: "sha256:..." } | { manifest_id: "cap://..." }
  Response: { invalidated: true, entries_affected: N }
```

### 10.2 Negotiation as an Event

The Registry publishes negotiation events for Observability and Loop:

```json
{
  "event_type": "Registry:NegotiationCompleted",
  "payload": {
    "negotiation_id": "neg://planner_001/003",
    "matched": true,
    "candidates_considered": 8,
    "candidates_returned": 2,
    "selected_manifest_id": "cap://nous-research/research-v2@2.3.0",
    "negotiation_duration_ms": 45,
    "cache_hit": false
  },
  "context": {
    "execution_id": "exec://finance/abc123",
    "stage_id": "financial_analysis"
  }
}
```

---

## 11. Compliance

Any implementation claiming Agent OS Capability Negotiation compatibility **must**:

1. Implement the Negotiate endpoint with request/response schema from §4 and §5
2. Implement the filtering algorithm from §6.1 (hard constraints — all must pass)
3. Implement the ranking algorithm from §6.2 (weighted scoring)
4. Implement the ConfirmBinding endpoint from §7
5. Implement negotiation caching as defined in §8
6. Handle all 4 failure modes from §9
7. Publish `Registry:NegotiationCompleted` events for each negotiation
8. Support both compile-time and runtime (fallback/replan) negotiation contexts

---

## 12. Open Questions

1. **Bulk negotiation** — should a single NegotiateRequest support multiple Requirements for different stages in the same Plan, returning a batch of bindings?
2. **Live performance data** — should negotiation consider real-time Pool metrics (current queue depth, recent error rate) in addition to Manifest-declared performance?
3. **Human-in-the-loop negotiation** — should there be an option for a human to manually select or override a negotiation result?
4. **Cross-Registry federation** — should negotiation support querying multiple Registries (public + private) and merging results?

---

## 13. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.7 | Capability Manifest entity |
| SPEC-0000 §3.8 | Capability Requirement entity |
| RFC-0100 §6 | Capability Requirements (what Workflow stages declare) |
| RFC-0101 §4 | Capability Negotiation (Planner-side protocol definition) |
| RFC-0101 §4.3 | Match Ranking Algorithm (scoring formula originated here) |
| RFC-0200 §4 | Capability Interface (the interface being negotiated for) |
| RFC-0201 §4.5 | Performance fields in Manifest (used in ranking) |
| RFC-0201 §4.2 | Type, domain, language declarations (used in filtering) |
| RFC-0201 §4.4 | Feature declarations (used in filtering) |
| RFC-0201 §6 | Registration (Manifests must be registered before negotiation) |
| Constitution Article 11 | Metadata Registry is the only discovery entry point |
