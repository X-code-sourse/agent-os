<p align="center">
  <h1 align="center">Intent OS</h1>
  <p align="center"><strong>An open-source flight recorder for AI agents.</strong></p>
  <p align="center">See what your agent did, why it failed, and what it cost.</p>
</p>

<p align="center">
  <a href="https://pypi.org/project/intentos/"><img src="https://img.shields.io/badge/pip-install%20intentos-blue?style=flat&logo=python" alt="pip install"></a>
  <a href="https://haihaoxu.github.io/intentos/"><img src="https://img.shields.io/badge/docs-intent--os.org-blue?style=flat" alt="Docs"></a>
  <a href="https://github.com/haihaoxu/intentos"><img src="https://img.shields.io/badge/github-haihaoxu/intentos-blue?style=flat&logo=github" alt="GitHub"></a>
  <a href="https://github.com/haihaoxu/intentos/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPLv3-blue?style=flat" alt="License"></a>
</p>

---

```bash
pip install intentos

# What happened?
intent-os doctor

# What did it do?
intent-os inspect latest

# What did it cost?
intent-os cost
```

---

## Trace · Debug · Cost

AI agents are becoming powerful, but debugging them is still painful.

You give an agent a task. It runs for minutes. Then it fails. And you don't know:
- **what tools it called** — which steps it took
- **where it failed** — what went wrong
- **how much it cost** — tokens, model calls, latency

Intent OS records everything your agent does. One command shows the full picture.

```
[14:02:01] START
[14:02:09] MODEL CALL  claude-sonnet-4  (2,451 tokens)
[14:02:14] TOOL        filesystem.write
[14:02:27] FAILED      test_jwt_verify failed

Goal:        refactor-auth-module
Duration:    14.3s
Cost:        $0.08
Tokens:      4,891
```

---

## Record any AI agent

Intent OS records **any** agent that uses OpenAI or Anthropic APIs — Claude Code, Cursor, or your own. Just set one environment variable:

```bash
intent-os proxy start

export OPENAI_BASE_URL=http://localhost:8377
export ANTHROPIC_BASE_URL=http://localhost:8377
```

Everything runs locally. Your data stays on your machine.

---

## For teams

As your team grows, Intent OS grows with you:

| | |
|---|---|
| **Cost tracking** | `intent-os cost --by agent` — see spending per agent, per model |
| **Security policies** | Define what agents can and can't do. `intent-os security policy apply` |
| **Compliance audit** | Full execution records with HTML/CSV export. `intent-os audit report` |
| **Security scanning** | Scan traces for sensitive data and dangerous patterns. `intent-os scan` |

---

## Quick start

```bash
# Install
pip install intentos

# Check your agent's health
intent-os doctor

# Run a capability and trace it
intent-os run translate -p text="Hello world" -p target_lang=zh

# See the full trace
intent-os inspect latest

# Track spending
intent-os cost

# Record any agent's API calls
intent-os proxy start
```

---

## Why Intent OS?

| Instead of... | Intent OS is... |
|--------------|----------------|
| Cloud-only tracing (LangSmith, LangFuse) | **Local-first.** Your data never leaves your machine. |
| Siloed per-platform logs | **Universal.** Works with any OpenAI/Anthropic agent. |
| Just logging | **Structured traces.** One intent → many API calls → one timeline. |

---

## Architecture

```
AI Agent → Intent OS → LLM (OpenAI / Anthropic / Ollama)
                │
                ├── Flight Recorder (doctor / inspect / trace)
                ├── Observability (cost / analytics)
                └── Governance (security / audit)
```

---

## Tested

**709 tests passed, 8 skipped, 0 failed** — CI across Python 3.10, 3.11, and 3.12.

---

## License

AGPLv3 + Commercial Option. See [LICENSE](LICENSE).

Personal and open-source use is free under AGPLv3. Commercial use requires a commercial license.

---

*Built by one person, for every developer who's asked "what did my agent just do?"*
