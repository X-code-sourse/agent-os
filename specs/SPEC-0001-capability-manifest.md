# SPEC-0001: Capability Manifest

> **Status:** Frozen v1.0 — Implemented in reference-runtime v0.4.3
> **Scope:** Defines the format for describing an AI Capability
> **Editor:** Intent OS Project

> **Implementation Note:** This spec is frozen. The reference-runtime parser (`core/parser.py`) is the canonical implementation. Any discrepancy between this document and the parser behavior is a spec bug.

---

## 1. Purpose

The Capability Manifest defines a **standard format for describing AI capabilities**. It answers one question:

> **What is this capability, what does it need, and what does it produce?**

It is analogous to:
- OpenAPI for REST APIs
- OCI Image Manifest for container images
- package.json for npm packages

---

## 2. Design Principles

### P1: Describe Capability, Not Intelligence

The Manifest describes what a capability does at the interface level — not how it does it. It shall **never** contain:
- Model-specific prompts or instructions
- Reasoning strategies or chain-of-thought templates
- Inference parameters (temperature, top_p, etc.)

### P2: Runtime-Agnostic

The Manifest shall not assume or require any specific runtime. It must be equally valid for:
- OpenAI Function Calling
- Anthropic Tool Use
- MCP Server
- Local execution with no model backend
- Future runtimes not yet invented

### P3: Minimal Sufficient

The Manifest shall contain only the fields required for interoperability. Optional fields for optimization, discovery, and metadata are allowed but must not be required for basic execution.

---

## 3. Specification

### 3.1 Top-Level Structure

```yaml
kind: Capability
metadata:
  name: string               # Required. Unique capability name
  version: string             # Required. Semantic versioning
  publisher: string           # Recommended. Publisher identifier
  digest: string              # Optional. Content hash (sha256:<hex>)
  description: string         # Recommended. Human-readable description
  tags: string[]              # Optional. Discovery tags
spec:
  input: Schema               # Required. Input contract
  output: Schema              # Required. Output contract
  requirements: Requirements  # Recommended. Operational requirements
  security: Security          # Optional. Security constraints
  cost: Cost                  # Optional. Cost estimation
```

### 3.2 Metadata Section

```yaml
metadata:
  name: text_summarize
  version: 1.0.0
  publisher: intent-os.org
  digest: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  description: "Summarize text content into key points"
  tags: ["nlp", "summarization", "text"]
```

**Fields:**
- **name** (required): Unique identifier for the capability. Convention: `{domain}-{action}` format (e.g., `web-search`, `financial-analysis`).
- **version** (required): Semantic versioning (MAJOR.MINOR.PATCH). MAJOR for breaking interface changes, MINOR for additive changes, PATCH for bug fixes. The parser accepts pre-release suffixes (e.g., `1.0.0-beta.1`).
- **publisher** (recommended): Identifier of the publishing entity. Should use reverse domain notation (e.g., `org.intent-os`, `com.example`).
- **digest** (optional): SHA-256 hash of the Manifest content for integrity verification. Uses the format `sha256:<hex>` where `<hex>` is the lowercase hex digest. The parser also accepts bare hex digests (without the `sha256:` prefix) for backward compatibility.
- **description** (recommended): Human-readable description of what the capability does.
- **tags** (optional): Keywords for discovery and categorization.

#### Digest Computation

The digest is computed from the **raw YAML bytes** as they appear on disk:

```
"sha256:" + hashlib.sha256(raw_yaml_bytes).hexdigest()
```

Because the digest is computed from raw bytes, it is sensitive to whitespace, key ordering, and formatting differences. Two semantically equivalent manifests that differ only in indentation or key order will produce different digests. The manifest contents are **not canonicalized** before hashing.

When `digest` is not declared in the manifest, the parser **auto-computes** it and stores the computed value on the parsed object.

### 3.3 Spec Section

#### 3.3.1 Input Schema

Defines the input contract — what the capability expects to receive.

```yaml
spec:
  input:
    text:
      type: string
      description: "The text to summarize"
      min_length: 10
      max_length: 100000
    max_length:
      type: integer
      description: "Maximum summary length in words"
      optional: true
      default: 200
```

**Supported types:** `string`, `integer`, `number`, `boolean`, `array`, `object`, `any`

**Field modifiers:**
- **optional** (default: false): Whether the field can be omitted
- **default**: Default value if the field is not provided
- **description**: Human-readable description

**Type-specific constraints:**

| Type | Constraints |
|---|---|
| `string` | `min_length`, `max_length`, `pattern` (regex), `format` (semantic hint: `uri`, `email`, etc.), `enum` |
| `integer`, `number` | `minimum`, `maximum` |
| `array` | `min_items`, `max_items`, `items` (element schema) |
| `object` | `properties` (map of property name to field schema) |

Constraints are validated to appear only on the correct types. Applying `min_length` to an integer field, `minimum` to a string field, or `min_items` to a non-array field produces a validation error.

#### 3.3.2 Output Schema

Defines the output contract — what the capability guarantees to produce.

```yaml
spec:
  output:
    summary:
      type: string
      description: "The generated summary"
    key_points:
      type: array
      description: "Key points extracted from the text"
      items:
        type: string
      optional: true
```

Output Schema follows the same type system and constraint rules as Input Schema.

#### 3.3.3 Nested Schema (Recursive FieldSchema)

Arrays and objects support fully recursive field definitions. The `items` key (for arrays) and the `properties` key (for objects) each accept a full `FieldSchema` with type, description, constraints, and further nesting. Validation recurses through all levels.

```yaml
# Example: nested object with array of objects
spec:
  input:
    results:
      type: array
      min_items: 1
      max_items: 100
      items:
        type: object
        properties:
          title:
            type: string
            min_length: 1
          url:
            type: string
            format: uri
          scores:
            type: array
            items:
              type: number
              minimum: 0.0
              maximum: 1.0
```

Each nested `FieldSchema` is validated independently — type-specific constraints are checked at every depth.

#### 3.3.4 Requirements

Defines what the capability needs to execute correctly.

```yaml
spec:
  requirements:
    models:
      - gpt-4
      - claude-3-sonnet
      - gemini-pro
    tools:
      - browser
      - search_api
    min_context: 16000
```

**Fields:**
- **models** (optional): List of model identifiers. Model identifiers are free-form strings. Publishers SHOULD use consistent naming, but the runtime does **not** validate or enforce any particular model identifier format.
- **tools** (optional): List of required tool capabilities. If a tool is listed, the runtime must provide it or the capability may fail.
- **min_context** (optional): Minimum context window length required (in tokens). Must be >= 1024 if specified.

#### 3.3.5 Security

Defines security constraints and risk level.

```yaml
spec:
  security:
    risk: low                         # low | medium | high | critical
    network: true                      # Does this capability make network calls?
    data_access: false                 # Does this access user/organization data?
    require_approval: false            # Does this require human approval?
```

**Risk levels:**
- **low**: Read-only, no side effects (e.g., text summarization, translation)
- **medium**: Has side effects but low impact (e.g., web search, file read)
- **high**: Significant side effects (e.g., file write, email send, API modification)
- **critical**: Could cause material harm (e.g., payment execution, system administration)

Unknown security keys beyond `risk`, `network`, `data_access`, and `require_approval` are silently ignored by the parser.

#### 3.3.6 Cost (Optional)

Provides hints for cost estimation.

```yaml
spec:
  cost:
    estimated_tokens: 0.1_per_char    # Token estimation formula
    estimated_latency: 2000ms          # Expected latency
    pricing_hint: 0.001_per_1k_tokens # Cost estimation
```

---

## 4. Complete Example

```yaml
kind: Capability
metadata:
  name: web_search
  version: 1.0.0
  publisher: org.intent-os
  digest: sha256:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2
  description: "Search the web and return relevant results"
  tags:
    - search
    - web
    - information-retrieval

spec:
  input:
    query:
      type: string
      description: "The search query"
      min_length: 1
      max_length: 500
    max_results:
      type: integer
      description: "Maximum number of results to return"
      optional: true
      default: 10
      minimum: 1
      maximum: 100

  output:
    results:
      type: array
      description: "Search result items"
      min_items: 0
      items:
        type: object
        properties:
          title:
            type: string
          url:
            type: string
            format: uri
          snippet:
            type: string
      optional: true
    total_results:
      type: integer
      description: "Total number of results found"
      optional: true

  requirements:
    models:
      - gpt-4
    tools:
      - search_api
      - browser

  security:
    risk: low
    network: true
    data_access: false

  cost:
    estimated_tokens: 0.05_per_query
    estimated_latency: 1500ms
```

---

## 5. Validation Rules

### 5.1 Structural Validation

The parser enforces the following structural rules at parse time:

| Rule | Enforcement |
|---|---|
| Root document must be a YAML mapping (dictionary) | Fatal parse error |
| `kind` must be present and equal to `"Capability"` | Validation error |
| `metadata` must be a mapping | Validation error (falls back to empty) |
| `spec` must be a mapping | Validation error (falls back to empty) |
| `metadata.name` is required | Validation error |
| `metadata.version` is required | Validation error |
| `metadata.version` must match `MAJOR.MINOR.PATCH` with optional pre-release suffix | Validation error |
| `spec.input` is required and must have at least one field | Validation error |
| `spec.output` is required and must have at least one field | Validation error |

### 5.2 Semantic Rules

1. All field names in `spec.input` and `spec.output` must be unique within their section.
2. If `min_context` is specified, it must be >= 1024.
3. Type-specific constraints (`min_length`, `max_length`, `pattern`, `format`) are only valid on `string`-typed fields.
4. Type-specific constraints (`minimum`, `maximum`) are only valid on `integer`- and `number`-typed fields.
5. Type-specific constraints (`min_items`, `max_items`) are only valid on `array`-typed fields.
6. `items` is only valid on `array`-typed fields; `properties` is only valid on `object`-typed fields.
7. Nested `FieldSchema` definitions (via `items` or `properties`) are validated recursively.

### 5.3 Digest Rules

1. When `digest` is declared in the manifest, the parser compares it against the computed digest of the raw YAML bytes and emits a warning on mismatch.
2. Both prefixed (`sha256:<hex>`) and bare hex digest formats are accepted for declared digests.
3. All computed digests (including auto-computed when no digest is declared) use the `sha256:<hex>` prefixed format.

### 5.4 Version Rules

1. Version must follow `MAJOR.MINOR.PATCH` format.
2. Pre-release suffixes are accepted: `1.0.0-beta.1`, `2.0.0-rc.3`, etc.
3. The pre-release suffix regex is `-[a-zA-Z0-9.]+`.

### 5.5 Security Defaults

If `security` is omitted, the following defaults apply:
```yaml
security:
  risk: low
  network: false
  data_access: false
  require_approval: false
```

---

## 6. Versioning

### 6.1 Version Compatibility

| Change | MAJOR | MINOR | PATCH |
|---|---|---|---|
| Remove input field | Yes | No | No |
| Add required input field | Yes | No | No |
| Add optional input field | No | Yes | No |
| Change output schema | Yes | No | No |
| Add output field | No | Yes | No |
| Bug fix in description | No | No | Yes |
| Change requirements | No | Yes | No |
| Change security risk level | Yes | No | No |

### 6.2 Publisher Enforcement

Publishers are expected to:
- Increment MAJOR when making incompatible changes to `spec.input` or `spec.output`
- Increment MINOR when adding functionality in a backward-compatible manner
- Increment PATCH for backward-compatible bug fixes

### 6.3 Pre-Release Versions

Pre-release versions (e.g., `1.0.0-beta.1`, `2.0.0-rc.3`) are accepted by the parser. Pre-release versions indicate a capability that is not yet considered stable. Runtimes MAY treat pre-release capabilities differently (e.g., require explicit opt-in, exclude from default discovery).

---

## 7. Serialization Formats

The canonical Manifest format is **YAML** (for human readability).

JSON is also valid (for machine generation/consumption).

Conversion between YAML and JSON should be lossless given that all field names conform to both formats' constraints.

---

## 8. Security Considerations

1. **Digest Verification**: When `digest` is present, consumers should verify the Manifest content matches the digest before execution. The parser performs this check automatically and warns on mismatch.
2. **Security Claims**: The `security.risk` field is a self-declared claim. In production environments, this should be verified or overridden by organizational policy.
3. **Requirements Injection**: The `requirements.tools` field should be validated against an allowlist in production environments to prevent capability-scoped privilege escalation.

---

## 9. Future Extensions (Phase 2+)

The following fields are reserved for future versions. None are implemented in the v0.4.3 runtime.

| Field | Purpose | Phase |
|---|---|---|
| `spec.context` | Declares which context dimensions the capability reads/writes | Phase 2+ |
| `spec.constraints` | Latency, cost, or quality bounds | Phase 2+ |
| `spec.test_schema` | Input/output examples for verification | Phase 2+ |
| `spec.dependencies` | Other capabilities this one depends on | Phase 2+ |
| `spec.telemetry` | What execution data this capability emits | Phase 2+ |

---

## 10. References

- OpenAPI Specification 3.x — for interface contract patterns
- OCI Image Spec — for manifest + digest conventions
- JSON Schema — for type system patterns
