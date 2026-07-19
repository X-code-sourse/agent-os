# RFC-0201: Capability Manifest

**Status:** Draft
**Type:** Runtime RFC
**Supersedes:** Nothing
**Depends on:** SPEC-0000 v1.0, RFC-0200 v1.0
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Summary

This RFC defines the **Capability Manifest** — the self-declaration document that every Capability publishes to announce its identity, capabilities, interface schemas, performance characteristics, and operational requirements. The Manifest is the unit of discovery in the Metadata Registry (§11): Workflows declare Requirements; the Registry matches them against Manifests; the Engine invokes the resulting binding.

---

## 2. Motivation

Without a standardized Manifest:

- Capabilities have no way to declare "I support finance research in English and Chinese with citation support"
- The Registry has no structured data to match Requirements against (RFC-0101 §4)
- The Planner cannot estimate cost or latency at compile time
- Third-party Capability authors cannot participate in the ecosystem — there is no contract to implement

A Manifest turns a Capability from an unnamed implementation into a **discoverable, matchable, verifiable service**.

---

## 3. Manifest Structure

### 3.1 Top-Level Schema

```yaml
manifest_id: cap://<provider>/<name>
version: semver                          # MAJOR.MINOR.PATCH
name: string                             # Human-readable name
description: string                      # What this Capability does

provider:
  name: string                           # Organization or individual
  homepage: string (URL)                 # Optional
  support_contact: string                # Optional

type: string                             # Capability type (research, python, browser, writing, ...)
supported_domains: string[]              # Domain expertise (finance, technology, science, ...)
supported_languages: string[]            # Language codes (en, zh, ja, ...)

interfaces:
  execute:                               # Main execution interface
    input_schema: JSON Schema            # Required: schema for execute() input
    output_schema: JSON Schema           # Required: schema for execute() output

  streaming:                             # Optional: streaming support
    supported: boolean                   # Default: false
    chunk_schema: JSON Schema            # Schema for each stream chunk
    max_chunks: int                      # Maximum chunks per invocation

  cancel:                                # Optional: cancellation support
    supported: boolean                   # Default: true (recommended)
    max_cancel_time_ms: int              # Max time to acknowledge cancel

features:
  supported: string[]                    # Feature flags (citation, file_upload, web_search, ...)
  required_environment:                  # What the Capability needs at runtime
    models: string[]                     # Model IDs it can use
    tools: string[]                      # Tool dependencies (browser, python, ...)
    memory_types: string[]               # Memory access needed (knowledge, cache, ...)

performance:
  quality_score: float                   # [0.0, 1.0] — self-declared or Loop-verified
  avg_latency_ms: int                    # Average execution latency
  p95_latency_ms: int                    # P95 execution latency (optional)
  cost_per_call: float                   # USD per typical invocation
  cost_per_token: float                  # USD per token (for model-based capabilities)
  throughput:                            # Concurrency capacity
    max_concurrent: int                  # Maximum concurrent invocations
    queue_depth: int                     # Maximum queue depth before rejecting

errors:                                 # Error codes this Capability may produce
  supported: string[]                    # From RFC-0200 §4.7 list

lifecycle:
  status: "active" | "deprecated" | "removed"
  deprecation_notice: string             # If deprecated: reason and migration path
  sunset_date: string (ISO 8601)         # If deprecated: when it will be removed

metadata:                                # Optional metadata
  tags: string[]
  documentation_url: string
  icon_url: string
  version_history:
    - version: semver
      date: ISO 8601
      change: string
```

---

## 4. Field Definitions

### 4.1 Identity

```yaml
manifest_id: cap://nous-research/research-v2
version: 2.3.0
name: "Nous Research v2"
description: >
  Full-spectrum research capability covering finance, technology,
  and general topics. Supports SEC filing retrieval, news aggregation,
  and citation-grounded analysis.
```

The `manifest_id` follows SPEC-0000 §5 identity convention:

```
cap://<provider>/<name>
```

- `<provider>` is a DNS-validated namespace (e.g., `nous-research`, `community-user`)
- `<name>` is the capability name, unique within the provider's namespace
- Version follows SemVer 2.0

### 4.2 Type and Domain

```yaml
type: research
supported_domains:
  - finance
  - technology
  - science
  - general
supported_languages:
  - en
  - zh
  - ja
```

**Type** is the broad category. The Registry matches this against `requirement.capability_type`.

**Domain** is the area of expertise. A Requirement may specify `domain: ["finance", "sec_filing"]` — the Registry checks that the Manifest supports all required domains as a subset.

**Language** follows BCP 47 codes. A Capability that supports only `en` will not match a Requirement for `zh`.

### 4.3 Interface Schemas

```yaml
interfaces:
  execute:
    input_schema:
      type: object
      required: [query]
      properties:
        query:
          type: string
          description: "The research query"
          maxLength: 5000
        depth:
          type: string
          enum: [quick, normal, deep]
          default: normal
        sources:
          type: array
          items:
            type: string
            enum: [sec, reuters, bloomberg, arxiv, general]
          description: "Preferred source types"

    output_schema:
      type: object
      properties:
        company:
          type: object
          description: "Identified company information"
        sources:
          type: array
          items:
            type: object
            properties:
              url: { type: string }
              type: { type: string }
              title: { type: string }
              accessed_at: { type: string, format: date-time }
        summary:
          type: string

  streaming:
    supported: true
    chunk_schema:
      type: object
      properties:
        content: { type: string }
        source_hint: { type: string }
```

The input and output schemas serve dual purposes:

1. **Validation** — the Pool validates every invocation's input/output against these schemas (RFC-0200 §6)
2. **Negotiation** — the Planner uses the output schema to determine whether a Capability's output is compatible with downstream stages

### 4.4 Features

```yaml
features:
  supported:
    - citation
    - source_attribution
    - web_search
    - file_upload
  required_environment:
    models:
      - claude-sonnet-4
      - gpt-4o
      - gemini-2.0-flash
    tools:
      - browser
      - search
    memory_types:
      - knowledge
      - cache
```

**Feature flags** enable Capability Negotiation to filter on specific capabilities. If a Workflow stage requires `citation`, only Manifests with `citation` in their `features.supported` list will match.

**Required environment** tells the Pool what infrastructure this Capability needs at runtime. The Pool uses this to:
- Verify that the required models are loaded
- Ensure the required tools are accessible
- Allocate the right memory stores

### 4.5 Performance

```yaml
performance:
  quality_score: 0.94
  avg_latency_ms: 2500
  p95_latency_ms: 5000
  cost_per_call: 0.02
  cost_per_token: 0.000003
  throughput:
    max_concurrent: 10
    queue_depth: 50
```

Performance values may be **self-declared** (initial registration) or **Loop-verified** (after sufficient execution data). When both exist, the Loop-verified values take precedence in negotiation.

The Registry's ranking algorithm (RFC-0101 §4.3) uses:
- `quality_score` — primary sort (50% weight)
- `cost_per_call` — secondary sort (25% weight)
- `avg_latency_ms` — tertiary sort (25% weight)

### 4.6 Error Support Declaration

```yaml
errors:
  supported:
    - timeout
    - rate_limit_exceeded
    - temporary
    - model_unavailable
    - invalid_input
    - internal_error
    - cancelled
```

A Manifest must declare which error codes (from RFC-0200 §4.7) it may emit. If a Capability emits an undeclared error code, the Pool treats it as `internal_error` and logs a Manifest compliance warning.

### 4.7 Lifecycle

```yaml
lifecycle:
  status: active
```

| Status | Meaning | Accepted Invocations |
|--------|---------|---------------------|
| `active` | Fully operational | New invocations accepted |
| `deprecated` | Will be removed on `sunset_date` | Existing invocations complete; new ones accepted with warning in Plan metadata |
| `removed` | No longer in the Registry | None |

---

## 5. Versioning

### 5.1 SemVer for Manifests

| Increment | When | Example |
|-----------|------|---------|
| MAJOR | Breaking change to input/output schema, type change, feature removal | `2.3.0` → `3.0.0` |
| MINOR | Adding features, domains, languages; performance improvements | `2.3.0` → `2.4.0` |
| PATCH | Bug fixes, latency improvements, documentation updates | `2.3.0` → `2.3.1` |

### 5.2 Backward Compatibility

A Manifest version N+1 is backward-compatible with N if:

1. All fields in `input_schema` from N remain in N+1 (with same or relaxed constraints)
2. All fields in `output_schema` from N remain in N+1 (with same or stricter constraints)
3. `type` has not changed
4. No feature has been removed from `features.supported`
5. `quality_score` has not decreased by more than 0.1 (Loop-verified changes exempt)
6. `cost_per_call` has not increased (or increased by less than 20% with justification)

---

## 6. Registration

### 6.1 Registration Flow

```
Capability Author                  Registry                    Capability Pool
      │                               │                             │
      │── Register(Manifest) ────────►│                             │
      │                               │                             │
      │                               ├─ 1. Validate Manifest       │
      │                               │    §3 schema conformance    │
      │                               │    §6.2 checks              │
      │                               │                             │
      │                               ├─ 2. Store Manifest          │
      │                               │    Version it               │
      │                               │                             │
      │                               ├─ 3. Notify Pool             │
      │                               │    "New capability available"│
      │                               │         │                   │
      │                               │         ├─ Load instance    │
      │                               │         ├─ Health check     │
      │                               │         └─ Set status=Ready │
      │                               │                             │
      │◄── Registered ────────────────│                             │
      │    { manifest_id, version,    │                             │
      │      status: active }         │                             │
```

### 6.2 Registration Validation

The Registry validates the Manifest before accepting it:

| Check | Rule |
|-------|------|
| Schema conformance | Manifest conforms to §3 YAML schema |
| Identity uniqueness | `manifest_id@version` is unique |
| Version increment | New version > last registered version (if re-registering) |
| Input schema validity | `input_schema` is valid JSON Schema (draft 2020-12) |
| Output schema validity | `output_schema` is valid JSON Schema |
| Error code coverage | At minimum `timeout`, `invalid_input`, `internal_error` must be declared |
| Performance bounds | `quality_score` ∈ [0,1]; `avg_latency_ms` > 0; `cost_per_call` ≥ 0 |
| Feature consistency | `required_environment.models` reference known model IDs |
| Model existence | All referenced models exist in the Model Registry |

---

## 7. Examples

### 7.1 Research Capability (Full)

```yaml
manifest_id: cap://nous-research/research-v2
version: 2.3.0
name: "Nous Research v2"
description: >
  Full-spectrum research capability covering finance, technology,
  and general topics. Supports SEC filing retrieval, news aggregation,
  and citation-grounded analysis.

provider:
  name: "Nous Research"
  homepage: "https://nousresearch.com"
  support_contact: "support@nousresearch.com"

type: research
supported_domains:
  - finance
  - technology
  - science
  - general
supported_languages:
  - en
  - zh
  - ja

interfaces:
  execute:
    input_schema:
      type: object
      required: [query]
      properties:
        query: { type: string, maxLength: 5000 }
        depth: { type: string, enum: [quick, normal, deep], default: normal }
        sources:
          type: array
          items: { type: string, enum: [sec, reuters, bloomberg, arxiv, general] }
    output_schema:
      type: object
      properties:
        summary: { type: string }
        company: { type: object }
        sources:
          type: array
          items:
            type: object
            properties:
              url: { type: string }
              type: { type: string }
              title: { type: string }
              accessed_at: { type: string, format: date-time }
        key_findings:
          type: array
          items: { type: string }

  streaming:
    supported: true
    chunk_schema:
      type: object
      properties:
        content: { type: string }
        source_hint: { type: string }
    max_chunks: 200

  cancel:
    supported: true
    max_cancel_time_ms: 2000

features:
  supported:
    - citation
    - source_attribution
    - web_search
  required_environment:
    models:
      - claude-sonnet-4
      - gpt-4o
    tools:
      - browser
      - search
    memory_types:
      - knowledge
      - cache

performance:
  quality_score: 0.94
  avg_latency_ms: 2500
  p95_latency_ms: 5000
  cost_per_call: 0.02
  cost_per_token: 0.000003
  throughput:
    max_concurrent: 10
    queue_depth: 50

errors:
  supported:
    - timeout
    - rate_limit_exceeded
    - temporary
    - model_unavailable
    - invalid_input
    - internal_error
    - cancelled

lifecycle:
  status: active
```

### 7.2 Python Execution Capability (Minimal)

```yaml
manifest_id: cap://community-sandbox/python-runner
version: 1.0.0
name: "Python Runner"
description: "Executes Python code in a sandboxed environment."

provider:
  name: "Community Sandbox"

type: python
supported_domains:
  - general
  - data_science
  - mathematics
supported_languages:
  - en

interfaces:
  execute:
    input_schema:
      type: object
      required: [code]
      properties:
        code: { type: string, description: "Python code to execute" }
        timeout: { type: integer, default: 30, description: "Max execution seconds" }
        packages:
          type: array
          items: { type: string }
          description: "Required pip packages"
    output_schema:
      type: object
      properties:
        stdout: { type: string }
        stderr: { type: string }
        exit_code: { type: integer }
        result: { }

  cancel:
    supported: true
    max_cancel_time_ms: 1000

features:
  supported:
    - sandboxed_execution
    - pip_install
  required_environment:
    tools:
      - python
    memory_types: []

performance:
  quality_score: 0.90
  avg_latency_ms: 500
  cost_per_call: 0.001

errors:
  supported:
    - timeout
    - invalid_input
    - internal_error
    - cancelled

lifecycle:
  status: active
```

---

## 8. Compliance

Any implementation claiming Agent OS Capability Manifest compatibility **must**:

1. Publish a Manifest conforming to the schema in §3 for every Capability
2. Include valid JSON Schema for both `input_schema` and `output_schema`
3. Declare at minimum `timeout`, `invalid_input`, and `internal_error` in `errors.supported`
4. Follow SemVer for versioning as defined in §5
5. Maintain backward compatibility within MAJOR versions as defined in §5.2
6. Register the Manifest with the Registry before accepting invocations (§6)

---

## 9. Open Questions

1. **Performance verification** — how does the Loop verify a Manifest's self-declared `quality_score` and `cost_per_call`? Should there be a probation period for new Manifests?
2. **Private Manifests** — should the Registry support private/unlisted Manifests accessible only within a specific tenant or organization?
3. **Composite Capabilities** — should a Manifest be able to declare that it internally composes other Capabilities (e.g., a "deep-research" Capability that calls research + python + writing)?
4. **Schema versioning** — input/output JSON Schemas may evolve independently of the Manifest version. Should schemas be addressable separately?

---

## 10. References

| Reference | Relationship |
|-----------|-------------|
| SPEC-0000 §3.7 | Capability Manifest entity |
| SPEC-0000 §3.8 | Capability Requirement entity |
| SPEC-0000 §5 | Identity Convention (`cap://<provider>/<name>` scheme) |
| RFC-0100 §6 | Capability Requirements (what Manifests must match) |
| RFC-0101 §4 | Capability Negotiation (how Manifests are matched) |
| RFC-0101 §4.3 | Match Ranking Algorithm (uses Manifest performance fields) |
| RFC-0200 §4 | Capability Interface (the interface the Manifest describes) |
| RFC-0200 §6 | Contract Validation (registered Manifests validated at invocation time) |
| Constitution Article 7 | Capability implements ability only |
| Constitution Article 11 | Metadata Registry is the only discovery entry point |
