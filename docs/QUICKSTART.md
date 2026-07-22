# Intent OS — 5-Minute Quickstart

Get started with Intent OS in 5 minutes. No API key required — we'll use Ollama for local inference.

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) (for local execution without API keys)

## Step 1: Install Intent OS

```bash
# Install the CLI and core runtime
pip install intent-os

# Or install with all extras (OpenAI + Anthropic adapters)
pip install "intent-os[all]"

# Install from source
git clone https://github.com/X-code-sourse/intentos.git
cd intent-os/reference-runtime
pip install -e .
```

## Step 2: Start Ollama

```bash
ollama pull llama3.2:1b
ollama serve
```

Keep the Ollama server running in a terminal window.

## Step 3: Write your first Manifest

Create a file called `hello.yaml`:

```yaml
kind: Capability
metadata:
  name: hello_world
  version: 1.0.0
  publisher: intent-os.org
  description: "Greet someone"

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

  security:
    risk: low
    network: false
```

## Step 4: Validate

```bash
intent-os validate hello.yaml
```

Expected output:
```
[OK] Manifest 'hello_world@1.0.0' loaded successfully
[OK] Manifest is valid
```

## Step 5: Execute locally (Ollama)

```bash
intent-os run hello.yaml --adapter ollama --input '{"name": "Intent OS"}'
```

You'll see the ExecutionRecord with latency, cost, and output.

## Step 6: Execute on OpenAI (if you have an API key)

```bash
export OPENAI_API_KEY="sk-..."
intent-os run hello.yaml --adapter openai --input '{"name": "Intent OS"}'
```

## Step 7: Cross-runtime comparison

```bash
intent-os compare hello.yaml --input '{"name": "Intent OS"}'
```

This executes the same Manifest on all available runtimes and compares the ExecutionRecords.

## Step 8: Import an existing tool

```bash
cat > my_tool.json << 'EOF'
{
  "name": "search_web",
  "description": "Search the web",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string"}
    },
    "required": ["query"]
  }
}
EOF

intent-os import openai-function my_tool.json
```

This converts your OpenAI function to an Intent OS Manifest and registers it.

## Step 9: Plan and run a workflow

```bash
# Plan from a goal
intent-os workflow plan "research AI trends"

# Run a predefined workflow
intent-os workflow run examples/research_workflow.yaml \
  --input '{"company": "NVIDIA", "ticker": "NVDA"}'
```

## Next Steps

- [Architecture Overview](../README.md)
- [Specification: Capability Manifest](../specs/SPEC-0001-capability-manifest.md)
- [Examples](../examples/)

## Troubleshooting

| Problem | Solution |
|---|---|
| `No adapters loaded` | Install Ollama and run `ollama serve` |
| `Ollama connection refused` | Run `ollama serve` in a separate terminal |
| `No module named 'openai'` | `pip install intent-os[all]` or `pip install openai` |
| `429: quota exceeded` | Your OpenAI account needs billing set up |
| `402: credits required` | Add credits to your OpenRouter account |
