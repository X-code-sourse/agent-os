<p align="center">
  <h1 align="center">Intent OS</h1>
  <p align="center"><strong>See exactly what your AI agent did.</strong></p>
  <p align="center">Intent OS is an open-source flight recorder for AI agents.</p>
</p>

<p align="center">
  <a href="https://pypi.org/project/intentos/"><img src="https://img.shields.io/badge/pip-install%20intentos-blue?style=flat&logo=python" alt="pip install"></a>
  <a href="https://x-code-sourse.github.io/intentos/"><img src="https://img.shields.io/badge/docs-intent--os.org-blue?style=flat" alt="Docs"></a>
  <a href="https://github.com/X-code-sourse/intentos"><img src="https://img.shields.io/badge/github-X--code--sourse/intentos-blue?style=flat&logo=github" alt="GitHub"></a>
  <a href="https://github.com/X-code-sourse/intentos/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPLv3-blue?style=flat" alt="License"></a>
</p>

---

```bash
pip install intentos

# See what your last agent did
intent-os doctor

# Try the demo
intent-os demo --auto
```

---

## Trace · Debug · Cost

AI agents are powerful. But they are black boxes.

You don't know:
- **what they did** — which tools they called, what steps they took
- **why they failed** — what went wrong, where it happened
- **how much they cost** — tokens, latency, model calls

Intent OS records everything your agent does and gives you answers.

```bash
# What happened?
intent-os doctor

# See every step
intent-os inspect latest

# Export as HTML
intent-os inspect latest --html
```

Example output:

```
[OK]  Goal:        refactor-auth-to-jwt
     Runtime:    anthropic (AnthropicAdapter)
     Duration:   14,327ms
     Cost:       $0.0842
     Tokens:     4,891

[14:02:01] > START (planner)
[14:02:06] > INVOKE (adapter) -- 2451 tokens
[14:02:08] OK DONE  (3241ms)
[14:02:09] > INVOKE (adapter) model=claude-sonnet-4
[14:02:14] OK DONE  (5824ms)
[14:02:27] !! FAIL  (12713ms) -- reason="test_jwt_verify failed"
```

---

## Record any AI agent

Intent OS can record **any** AI agent that calls OpenAI or Anthropic APIs — Claude Code, Cursor, Copilot, or your own:

```bash
# Start the proxy
intent-os proxy start

# Point your agent at it
export OPENAI_BASE_URL=http://localhost:8377
export ANTHROPIC_BASE_URL=http://localhost:8377

# Everything is recorded automatically
intent-os doctor
```

No SDK changes. No code modifications. Just a single environment variable.

---

## Quick Start

```bash
# Install
pip install intentos

# Check your agent's health
intent-os doctor

# Run a capability and trace it
intent-os run translate -p text="Hello world" -p target_lang=zh

# See the full trace
intent-os inspect latest

# Export as shareable HTML
intent-os inspect latest --html
```

---

## Features

| | |
|---|---|
| **Trace** | Full execution timeline — every model call, tool invocation, file change |
| **Debug** | Failure analysis with actionable suggestions |
| **Cost** | Token tracking, cost estimation per model and agent |
| **Security** | Policy engine, audit log, compliance reporting |
| **Cross-Runtime** | Run the same capability on OpenAI, Anthropic, Ollama, or local |

---

## Architecture

```
AI Agent → Intent OS → LLM (OpenAI / Anthropic / Ollama)
                │
                ├── Event Store (execution log)
                ├── inspect / doctor / cost
                └── Security Policy Engine
```

Intent OS is more than a flight recorder — it's an agent operating layer with security policies, cross-runtime execution, cost models, and workflow orchestration. But the flight recorder is where you start.

---

## Why not just use MCP?

[MCP](https://modelcontextprotocol.io) standardizes **connection** — how an AI tool talks to a runtime. Intent OS standardizes **execution** — how a capability is described, traced, secured, and recorded across runtimes. They are complementary.

---

## Tested

**709 tests passed, 8 skipped, 0 failed** — CI matrix across Python 3.10, 3.11, and 3.12.

---

## License

AGPLv3 + Commercial Option. See [LICENSE](LICENSE).

Personal / open-source use is free under AGPLv3. Commercial use requires a commercial license.

---

*Built by one person, for every developer who's asked "what did my agent just do?"*
