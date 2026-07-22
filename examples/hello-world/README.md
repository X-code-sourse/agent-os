# Hello World -- Intent OS Quickstart

A minimal example that demonstrates the basic building block of Intent OS: a **Capability Manifest**.

---

## What is a Capability Manifest?

A Capability Manifest is a YAML (or JSON) file that describes an AI capability in a **runtime-agnostic** way. It answers three questions:

> **What is this capability? What does it need? What does it produce?**

It is analogous to:
- **OpenAPI** for REST APIs
- **package.json** for npm packages
- **OCI Image Manifest** for container images

The Manifest describes the **interface** of a capability -- never the intelligence behind it. It says nothing about which model to use, how prompts are written, or what reasoning strategy to follow. This separation is the core design principle of Intent OS:

> **Intent OS does not standardize intelligence. It standardizes interaction.**

Because the Manifest is runtime-agnostic, the same `.yaml` file can be executed against OpenAI, Anthropic, Ollama (local), or any future runtime -- without modification.

---

## File: `hello_world.yaml` -- Field-by-Field Walkthrough

```yaml
kind: Capability
metadata:
  name: hello_world
  version: 1.0.0
  publisher: intent-os.org
  description: "A simple hello world capability that greets the user"

spec:
  input:
    name:
      type: string
      description: "The name to greet"
      default: "World"

  output:
    greeting:
      type: string
      description: "The generated greeting"
    message:
      type: string
      description: "An additional message"

  requirements:
    models:
      - gpt-4o
      - claude-sonnet-4

  security:
    risk: low
    network: false
```

### Top-Level

| Field | Value | Meaning |
|---|---|---|
| `kind` | `Capability` | The document type. Must be `Capability` for all capability manifests. This is how runtimes identify what kind of document they are parsing. |
| `metadata` | (block) | Identification and discovery information. Every Manifest starts with this section. |
| `spec` | (block) | The technical contract: what goes in, what comes out, and what is needed to run. |

### `metadata`

| Field | Value | Meaning |
|---|---|---|
| `name` | `hello_world` | A unique identifier for the capability. Convention is `{domain}-{action}` (e.g., `web-search`, `text-summarize`). Here the name is simply `hello_world` since it is a teaching example. |
| `version` | `1.0.0` | Semantic versioning (`MAJOR.MINOR.PATCH`). MAJOR for breaking interface changes, MINOR for additive changes, PATCH for bug fixes. This field is **required**. |
| `publisher` | `intent-os.org` | The entity that published this capability. Uses reverse-domain or org-based naming. This field is **recommended** but not required. |
| `description` | `"A simple hello world capability that greets the user"` | A human-readable summary of what the capability does. Shown in registries, listings, and discovery tools. This field is **recommended** but not required. |

### `spec.input`

Defines the **contract for what the capability expects to receive**.

```yaml
input:
  name:
    type: string
    description: "The name to greet"
    default: "World"
```

Here there is a single input field called `name`:

| Property | Value | Meaning |
|---|---|---|
| `type` | `string` | The data type. Supported types: `string`, `integer`, `number`, `boolean`, `array`, `object`, `any`. |
| `description` | `"The name to greet"` | Human-readable explanation of this field. |
| `default` | `"World"` | A fallback value when the caller does not provide this field. Because a default is specified, `name` is effectively **optional** -- if omitted, the runtime substitutes `"World"`. Without a default, the field would be required and the runtime would reject invocations that omit it. |

**Constraints and modifiers** that can also appear on input fields:

| Modifier | Purpose |
|---|---|
| `optional: true` | Explicitly marks a field as optional (implied when `default` is set). |
| `default: <value>` | Fallback value when the field is omitted. |
| `min_length` / `max_length` | String length constraints. |
| `min` / `max` | Numeric range constraints. |
| `pattern` | Regex validation (strings). |
| `enum` | Allowlist of valid values. |
| `format` | Semantic format hint (e.g., `uri`, `email`, `date-time`). |

### `spec.output`

Defines the **contract for what the capability guarantees to produce**.

```yaml
output:
  greeting:
    type: string
    description: "The generated greeting"
  message:
    type: string
    description: "An additional message"
```

Two output fields are declared:

| Field | Type | Description |
|---|---|---|
| `greeting` | `string` | The generated greeting (e.g., "Hello, World!"). |
| `message` | `string` | An additional message (e.g., a welcome message or fun fact). |

Every field in `output` follows the same type system as `input`. Fields are considered **required** by default unless marked `optional: true`. The runtime guarantees that the returned structure conforms to this schema.

### `spec.requirements`

Declares what the capability needs to execute correctly.

```yaml
requirements:
  models:
    - gpt-4o
    - claude-sonnet-4
```

| Field | Value | Meaning |
|---|---|---|
| `models` | `[gpt-4o, claude-sonnet-4]` | A list of model identifiers this capability is known to work with. The runtime uses this to select a compatible model. Model URIs follow the format `{provider}-{model-name}`. This is **optional** -- if omitted, any capable model may be used. |

Other optional requirement fields (not used here):

| Field | Purpose |
|---|---|
| `tools` | List of required tool capabilities (e.g., `browser`, `search_api`). |
| `min_context` | Minimum context window length in tokens (default: 4096). |

### `spec.security`

Defines the capability's security posture.

```yaml
security:
  risk: low
  network: false
```

| Field | Value | Meaning |
|---|---|---|
| `risk` | `low` | The risk level of execution. Levels: `low` (read-only, no side effects), `medium` (side effects but low impact), `high` (significant side effects), `critical` (could cause material harm). Since this capability only generates a greeting string, the risk is `low`. |
| `network` | `false` | Whether the capability makes network calls. This one does not -- it runs entirely locally. |

When `security` is omitted entirely, the defaults are:

```yaml
security:
  risk: low
  network: false
  data_access: false
  require_approval: false
```

### Summary: What `hello_world.yaml` Declares

In plain English, this Manifest says:

> "I am a capability called `hello_world` version 1.0.0, published by `intent-os.org`. I take an optional name (defaulting to 'World') and return a greeting and a message. I work with gpt-4o or claude-sonnet-4. I am low risk and make no network calls."

---

## How to Run It

### Prerequisites

Install Intent OS and ensure at least one model adapter is available.

```bash
pip install intent-os
```

### Validate the Manifest

Before running, validate that the manifest is well-formed:

```bash
intent-os validate hello_world.yaml
```

A successful validation exits with code 0 and prints nothing (or a brief confirmation). Any structural or semantic errors are reported with line numbers.

### Run with Ollama (Local, No API Key Required)

```bash
intent-os run hello_world.yaml --adapter ollama \
  --input '{"name": "World"}'
```

Ollama runs entirely on your machine. No API key, no network calls. The `--input` flag passes JSON matching the `spec.input` schema. Because `name` has a default of `"World"`, this is equivalent to:

```bash
intent-os run hello_world.yaml --adapter ollama --input '{}'
```

### Run with OpenAI

```bash
intent-os run hello_world.yaml --adapter openai \
  --input '{"name": "World"}'
```

Requires `OPENAI_API_KEY` to be set in your environment. The same manifest runs without changes -- only the `--adapter` flag differs.

### Run with Anthropic

```bash
intent-os run hello_world.yaml --adapter anthropic \
  --input '{"name": "World"}'
```

Requires `ANTHROPIC_API_KEY` to be set. The exact same manifest, a different adapter.

### Custom Input

```bash
intent-os run hello_world.yaml --adapter openai \
  --input '{"name": "Alice"}'
```

This should produce output similar to:

```json
{
  "greeting": "Hello, Alice!",
  "message": "Welcome to Intent OS -- the interoperability layer for AI capabilities."
}
```

(The exact text will vary by model, but the structure will always match `spec.output`.)

### Export for Other Platforms

Intent OS manifests can be exported to platform-specific formats. For example, to export as an OpenAI function-calling tool definition:

```bash
intent-os export openai hello_world.yaml --as-tool
```

This lets you take a capability described once in a runtime-agnostic manifest and use it directly within OpenAI's ecosystem. Export targets include OpenAI, Anthropic tool-use, and MCP server definitions.

---

## What This Demonstrates

This hello-world example illustrates the three core principles of Capability Manifests:

1. **Describe capability, not intelligence** -- the manifest says what the capability does and what it needs, but nothing about how the AI should generate the greeting.
2. **Runtime-agnostic** -- the same `.yaml` file runs against Ollama, OpenAI, and Anthropic by changing only the `--adapter` flag.
3. **Minimal sufficient** -- the manifest contains only the fields needed for interoperability: name, version, input schema, output schema, and security posture.

From here, explore the `text-summarize` example for a more realistic capability, or read `SPEC-0001-capability-manifest.md` for the full specification.
