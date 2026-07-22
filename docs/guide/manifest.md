# Writing a Capability Manifest

A Manifest is a YAML file that describes an AI capability — what it does, what input it needs, what output it produces, and what security requirements it has.

Think of it as the **API contract** for an AI capability, independent of any specific model or runtime.

---

## Minimal Manifest

```yaml
kind: Capability
metadata:
  name: hello_world
  version: 1.0.0
  publisher: your-name
  description: "A simple echo capability"
spec:
  input:
    name:
      type: string
      description: "Your name"
  output:
    greeting:
      type: string
      description: "A personalized greeting"
  security:
    risk: low
```

Save this as `hello.yaml` and run:

```bash
intent-os validate hello.yaml
intent-os run hello.yaml -p name="World"
```

---

## Full Manifest Structure

```yaml
kind: Capability
metadata:
  name: translate              # kebab-case identifier
  version: 1.2.0               # semantic version
  publisher: intent-os.org     # publisher identifier
  description: "Translates text between natural languages"
  tags: [nlp, translation]     # search tags

spec:
  # --- Input Schema ---
  input:
    text:
      type: string
      description: "The text to translate"
      min_length: 1
      max_length: 100000
    source_lang:
      type: string
      description: "Source language code (optional — auto-detect if omitted)"
      pattern: "^[a-z]{2}(-[A-Z]{2})?$"
      optional: true
    target_lang:
      type: string
      description: "Target language code"
      pattern: "^[a-z]{2}(-[A-Z]{2})?$"

  # --- Output Schema ---
  output:
    translated_text:
      type: string
      description: "The translated text"
    detected_language:
      type: string
      description: "Detected source language"
      optional: true
    confidence:
      type: number
      description: "Confidence score (0.0 to 1.0)"
      minimum: 0.0
      maximum: 1.0

  # --- Requirements ---
  requirements:
    models: [claude-sonnet-4, gpt-4o]
    min_context: 32000

  # --- Security ---
  security:
    risk: low             # low | medium | high | critical
    network: true
    data_access: false
    require_approval: false
```

---

## Field Types

| Type | YAML | Example |
|------|------|---------|
| String | `type: string` | `"Hello"` |
| Integer | `type: integer` | `42` |
| Number | `type: number` | `3.14` |
| Boolean | `type: boolean` | `true` |
| Array | `type: array` | `["a", "b"]` |
| Object | `type: object` | `{key: "val"}` |

---

## Field Constraints

Each input/output field supports optional constraints:

| Constraint | Applies To | Example |
|------------|-----------|---------|
| `min_length` | string | `min_length: 1` |
| `max_length` | string | `max_length: 100000` |
| `pattern` | string | `pattern: "^[a-z]{2}$"` |
| `minimum` | number | `minimum: 0.0` |
| `maximum` | number | `maximum: 1.0` |
| `enum` | string | `enum: [zh, es, fr, de]` |
| `optional` | any | `optional: true` |

---

## Security Risk Levels

| Level | Meaning | Example |
|-------|---------|---------|
| `low` | Safe, read-only operations | Translation, summarization |
| `medium` | Network access, external data | Web search, data extraction |
| `high` | Code execution, file modification | Code review, file operations |
| `critical` | System-level changes | Deployment, system configuration |

---

## Best Practices

1. **Keep names short and kebab-case** — `text_summarize`, `code_review`, `sentiment_analyze`
2. **Always provide descriptions** — they help both users and LLMs understand the capability
3. **Mark optional fields** — use `optional: true` for any field that isn't strictly required
4. **Set appropriate risk levels** — be honest about what your capability does
5. **Use tags** — they enable semantic search in the registry

---

## Next Steps

- [Explore built-in examples](https://github.com/haihaoxu/intentos/tree/main/examples)
- [Learn about running capabilities](runtime.md)
- [Browse the CLI reference](../cli/commands.md)
