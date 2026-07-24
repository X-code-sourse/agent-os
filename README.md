<p align="center">
  <h1 align="center">Intent OS</h1>
  <p align="center"><strong>Your AI agent ran for 20 minutes. It says "done."</strong></p>
  <p align="center"><strong>Can you explain what it did?</strong></p>
</p>

<p align="center">
  <a href="https://pypi.org/project/intentos/"><img src="https://img.shields.io/badge/pip-install%20intentos-blue?style=flat&logo=python" alt="pip install"></a>
  <a href="https://haihaoxu.github.io/intentos/"><img src="https://img.shields.io/badge/docs-online-blue?style=flat" alt="Docs"></a>
  <a href="https://github.com/haihaoxu/intentos"><img src="https://img.shields.io/badge/github-haihaoxu/intentos-blue?style=flat&logo=github" alt="GitHub"></a>
  <a href="https://github.com/haihaoxu/intentos/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPLv3-blue?style=flat" alt="License"></a>
  <a href="https://github.com/haihaoxu/intentos/actions"><img src="https://img.shields.io/badge/tests-731%20passed-brightgreen?style=flat" alt="Tests"></a>
</p>

---

```bash
pip install intentos

# What just happened?
intent-os doctor

# See every step your agent took
intent-os inspect latest

# Track what it cost
intent-os cost
```

**You get this:**

```
[14:02:01] > START
[14:02:09] > MODEL CALL  claude-sonnet-4  (2,451 tokens)
[14:02:14] > TOOL        filesystem.write
[14:02:27] !! FAILED     test_jwt_verify failed

Goal:        refactor-auth-module
Agent:       claude-code
Duration:    14.3s
Cost:        $0.08
Tokens:      4,891
```

No more guessing. No more "I think it called the API three times." You see exactly what happened — every model call, every tool use, every failure, every dollar.

---

## You're not alone

You've been here:

- **"What did it actually do?"** — Claude Code says "task complete." The file changed. But you didn't see it happen. You don't know if it wrote 3 lines or deleted a function.
- **"Why did it fail?"** — Agent runs for 30 minutes. Fails. No stack trace. No log. Just "error."
- **"Where is the money going?"** — API bill shows $47 this month. Which agent? Which model? Which task?

Intent OS is the **flight recorder for AI agents.** It intercepts every API call your agent makes and turns it into a structured, searchable execution trace. Your data stays on your machine. No cloud. No account. Just `pip install`.

---

## Works with your agent in 30 seconds

```bash
# Start the recorder
intent-os proxy start

# Point your agent at it
export OPENAI_BASE_URL=http://localhost:8377
export ANTHROPIC_BASE_URL=http://localhost:8377

# Use your agent normally — every call is recorded
claude "refactor this module"

# See what happened
intent-os doctor
intent-os inspect latest
```

Works with **Claude Code, Cursor, GitHub Copilot, or any agent** that speaks OpenAI or Anthropic APIs. Zero changes to your agent. Just one environment variable.

---

## What you get

| Command | What it tells you |
|---------|-------------------|
| `intent-os doctor` | One-command health check: what your agent did, what went wrong, how to fix it |
| `intent-os inspect latest` | Full execution timeline: every model call, tool use, cost, and duration |
| `intent-os cost` | Spending breakdown: by agent, by model, daily trends |
| `intent-os proxy start` | Start recording — intercepts Claude Code, Cursor, any agent |
| `intent-os proxy doctor` | Check proxy health: running status, traffic stats, agent detection |
| `intent-os agent create --name "My Agent"` | Register agent identity for tracking across sessions |
| `intent-os scan` | Security scan: detect dangerous tool calls and sensitive data in traces |
| `intent-os audit report --format html` | Compliance report for teams: full audit trail with HTML/CSV export |
| `intent-os event prune --older-than 90` | Data lifecycle: clean up old traces, keep your disk under control |

---

## For teams

As your team grows:

- **Cost tracking** — `intent-os cost --by agent` — who's spending what, on which model
- **Security policies** — define what agents can and can't do: `intent-os security policy apply`
- **Compliance audit** — full execution records: `intent-os audit report --format html`
- **Agent identity** — every agent gets an ID, every execution links back to its owner

---

## Why local-first?

| Instead of... | Intent OS is... |
|--------------|----------------|
| Cloud-only tracing (LangSmith, LangFuse) | **Local-first.** Your data never leaves your machine. |
| Siloed per-platform logs | **Universal.** Works with any OpenAI/Anthropic agent. |
| Just logging | **Structured traces.** One execution → many API calls → one timeline. |
| Postgres + Redis + S3 | **One SQLite file.** No infrastructure needed. |

No API key to sign up. No dashboard to log into. Your agent's execution data is yours — it lives in `~/.intent-os/events.db`.

---

## Architecture

```
AI Agent → Intent OS Proxy → LLM (OpenAI / Anthropic / Ollama)
                │
                ├── Flight Recorder (observe / debug / cost)
                ├── Security Guard (scan / policy / audit)
                └── Event Store (SQLite — local, append-only, queryable)
```

Intent OS is **building the execution layer for AI agents.** Today it's a flight recorder. Tomorrow it will make agents portable, governable, and composable across any runtime.

---

## Tested

**731 tests, 8 skipped, 0 failures** — CI across Python 3.10, 3.11, and 3.12.

---

## License

AGPLv3 + Commercial Option. See [LICENSE](LICENSE).

Open-source use is free under AGPLv3. Commercial use requires a commercial license.

---

*Built by one person, for every developer who's asked "what did my agent just do?"*
