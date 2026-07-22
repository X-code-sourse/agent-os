# Quickstart

Get Intent OS running in 60 seconds.

## 1. Install

```bash
pip install intentos
```

Or install with support for a specific AI provider:

```bash
pip install "intentos[openai]"    # OpenAI support
pip install "intentos[anthropic]" # Anthropic support
pip install "intentos[all]"       # All providers
```

Verify the installation:

```bash
intent-os --version
# intent-os 0.4.1
```

## 2. Validate a Manifest

Manifests are YAML files that describe AI capabilities. Try validating one of the built-in examples:

```bash
intent-os validate examples/translate.yaml
```

You should see:

```
[OK] Manifest 'translate@1.2.0' loaded successfully
Manifest: translate@1.2.0
Input fields: ['text', 'source_lang', 'target_lang']
Output fields: ['translated_text', 'detected_language', 'confidence']
Security risk: low
[OK] Manifest is valid
```

## 3. Run a Capability

### With Ollama (free, local)

If you have [Ollama](https://ollama.com) installed and running:

```bash
ollama pull llama3.2:latest
ollama serve

# In another terminal:
intent-os run translate -p text="Hello world" -p target_lang=zh
```

### With a cloud provider

Set your API key:

```bash
export OPENAI_API_KEY=sk-...
# or
export ANTHROPIC_API_KEY=sk-ant-...
```

Then run:

```bash
intent-os run translate --adapter openai -p text="Hello world" -p target_lang=zh
```

### Without any API key (simulated)

No Ollama, no API key? The runtime automatically falls back to a simulated adapter:

```bash
intent-os run translate -p text="Hello world" -p target_lang=zh
# Adapters loaded: simulated (no real runtime available)
```

## 4. Use Natural Language

With Ollama or an API key configured:

```bash
intent-os ask "translate 'good morning' to Japanese"
```

Or enter interactive mode:

```bash
intent-os ask
> translate this text to French
> 用 OpenAI 重跑           # switch adapter mid-conversation
> exit
```

## 5. See What's Available

```bash
intent-os list
intent-os registry search "code"
intent-os demo --auto
```

---

## What's Next?

- [Learn how to write your own Manifest](guide/manifest.md)
- [Explore all 16 CLI commands](cli/commands.md)
- [Browse built-in examples](https://github.com/haihaoxu/intentos/tree/main/examples)
