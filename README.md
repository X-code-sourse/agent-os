<p align="center">
  <h1 align="center">Intent OS</h1>
  <p align="center"><strong>Your AI agent is amazing. But every day, it starts over.</strong></p>
  <p align="center"><strong>Give it a memory. Give it a life.</strong></p>
</p>

<p align="center">
  <a href="https://pypi.org/project/intentos/"><img src="https://img.shields.io/badge/pip-install%20intentos-blue?style=flat&logo=python" alt="pip install"></a>
  <a href="https://haihaoxu.github.io/intentos/"><img src="https://img.shields.io/badge/docs-online-blue?style=flat" alt="Docs"></a>
  <a href="https://github.com/haihaoxu/intentos"><img src="https://img.shields.io/badge/github-haihaoxu/intentos-blue?style=flat&logo=github" alt="GitHub"></a>
  <a href="https://github.com/haihaoxu/intentos/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPLv3-blue?style=flat" alt="License"></a>
  <a href="https://github.com/haihaoxu/intentos/actions"><img src="https://img.shields.io/badge/tests-849%20passed-brightgreen?style=flat" alt="Tests"></a>
</p>

---

```bash
pip install intentos

# What happened? What went wrong? What did it cost?
intent-os doctor

# Every step your agent took, every model it called.
intent-os inspect latest

# Who is this agent? What does it know? What has it learned?
intent-os agent get <id>
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

---

## AI agents have amnesia.

Claude Code spends 30 minutes solving your problem — researching, trying approaches, failing, learning from mistakes. You close the session, and **everything it learned is gone**. Tomorrow, it's a blank slate. The same struggles. The same dead ends. The same lessons it already learned.

This is the real bottleneck in AI today. Not capability. **Amnesia.**

Intent OS is the flight recorder — and the long-term memory — for your AI agents. It records everything they do, turns it into structured experience, and gives them an identity that persists across sessions.

Even better: that identity — role, traits, execution history, experience — can one day move with them across runtimes. From Claude to Codex to whatever comes next. Your agent doesn't have to start over when you switch tools.

---

## How it works

```bash
# Start the flight recorder
intent-os proxy start

# Point your agent at it — zero code changes
export OPENAI_BASE_URL=http://localhost:8377
export ANTHROPIC_BASE_URL=http://localhost:8377

# Use your agent normally. Every action is recorded.
claude "refactor the payment module"

# See what happened, what went wrong, and what it learned
intent-os doctor
intent-os inspect latest
intent-os cost
```

Works with **Claude Code, Cursor, GitHub Copilot, or any agent** that speaks OpenAI or Anthropic APIs. One environment variable. Nothing else. Everything runs locally. One SQLite file. No cloud. No account.

---

## What you get

| Command | What it tells you |
|---------|-------------------|
| `intent-os doctor` | Health check: what happened, what went wrong, how to fix it |
| `intent-os inspect latest` | Full timeline: every model call, tool use, cost |
| `intent-os cost` | Spending: by agent, by model, daily trends |
| `intent-os proxy start` | Start recording — intercepts any OpenAI/Anthropic agent |
| `intent-os proxy doctor` | Proxy health: running status, traffic stats |
| `intent-os agent create --name "X" --persona "..." --traits "..."` | Create an agent with a role and personality |
| `intent-os agent get <id>` | Full person-card: role, traits, execution history, experience |
| `intent-os experience list --agent <id>` | What this agent learned from its past runs |
| `intent-os scan` | Security scan: dangerous tool calls in traces |
| `intent-os audit report --format html` | Compliance report: full audit trail |

---

## Which of these have you felt?

- **"It worked yesterday. Today it doesn't."** — Same task, different session. The agent doesn't remember what it learned last time. No experience carries over.

- **"I'm afraid to give it a big task."** — The agent is capable, but the bigger the task, the more files it touches. You don't know what it changed.

- **"Something went wrong. I have no idea what."** — Agent ran for 30 minutes. Failed. No stack trace. No record of what happened.

- **"Why is my API bill $300 this month?"** — Which agent? Which task? Which model? You can't answer any of those questions.

Intent OS gives you the answer to all four — before you even ask.

---

## For teams

When multiple people use multiple agents, "who did what" becomes a business question:

- **Accountability** — `intent-os cost --by agent` — who's spending what, on which model
- **Governance** — `intent-os security policy apply` — define what agents can and can't do
- **Compliance** — `intent-os audit report --format html` — full execution record, any timeframe
- **Identity** — every agent gets an ID and a profile, every execution links back to its owner

---

## Why local-first?

| Instead of... | Intent OS is... |
|--------------|----------------|
| Cloud-only tracing (LangSmith, LangFuse) | **Local-first.** Your data never leaves your machine. |
| Siloed per-platform logs | **Universal.** Works with any OpenAI/Anthropic agent. |
| Just logging | **Structured traces.** One execution → many API calls → one timeline. |
| Postgres + Redis + S3 | **One SQLite file.** No infrastructure needed. |

No API key to sign up. No dashboard to log into. Your agent's execution data is yours — it lives in `~/.intent-os/intent.db`.

---

## The bigger picture: an agent that grows with you

Intent OS is not just a tool. It is the first implementation of a **portable execution contract for AI agents** — the missing layer that lets an Agent be defined, executed, verified, and moved across any runtime.

```
                    Agent Capability
                          │
                    ┌─────▼──────┐
                    │  Execution  │
                    │  Contract   │  ← Intent OS
                    └─────┬──────┘
                          │
         ┌────────────────┼────────────────┐
         │                │                │
    Claude RT       OpenAI RT        Ollama RT
```

The seven layers of Intent OS — Context, Identity, Execution, Verification, Governance, Interoperability, Experience — are the components of this contract. Together they answer the questions any organization must ask of an autonomous system: who was it, what was it supposed to do, what did it do, what evidence did it have, what did it learn, and who authorized it.

This is **Agent Accountability infrastructure.** The equivalent for autonomous AI of what audit trails are to finance and what version control is to software.

[7 specs](https://github.com/haihaoxu/intentos/tree/main/specs), all frozen. 26 event types. 6 adapters. One contract. Any runtime.

---

## Tested

**842 tests, 8 skipped, 0 failures** — CI across Python 3.10, 3.11, and 3.12.

---

## License

AGPLv3 + Commercial Option. See [LICENSE](LICENSE).

Open-source use is free under AGPLv3. Commercial use requires a commercial license.

---

*Your agent doesn't have to start over every day. Give it a life.*
