<p align="center">
  <h1 align="center">Intent OS</h1>
  <p align="center"><strong>AI agents are becoming autonomous.</strong></p>
  <p align="center"><strong>But you still can't trust what you can't see.</strong></p>
</p>

<p align="center">
  <a href="https://pypi.org/project/intentos/"><img src="https://img.shields.io/badge/pip-install%20intentos-blue?style=flat&logo=python" alt="pip install"></a>
  <a href="https://haihaoxu.github.io/intentos/"><img src="https://img.shields.io/badge/docs-online-blue?style=flat" alt="Docs"></a>
  <a href="https://github.com/haihaoxu/intentos"><img src="https://img.shields.io/badge/github-haihaoxu/intentos-blue?style=flat&logo=github" alt="GitHub"></a>
  <a href="https://github.com/haihaoxu/intentos/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPLv3-blue?style=flat" alt="License"></a>
  <a href="https://github.com/haihaoxu/intentos/actions"><img src="https://img.shields.io/badge/tests-834%20passed-brightgreen?style=flat" alt="Tests"></a>
</p>

---

```bash
pip install intentos

# Trust, but verify.
intent-os doctor

# Every step your agent took.
intent-os inspect latest

# Every dollar it spent.
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

---

## The problem is not that AI agents aren't capable. It's that you can't trust them.

AI agents are crossing a line. They used to answer questions. Now they modify code, call APIs, write files, spend money — all on their own. And when something goes wrong, you have nothing. No trace. No evidence. No way to explain what happened.

That gap — between the authority we give agents and the visibility we have into what they do — is the real bottleneck. Not model capability. Trust.

Intent OS closes that gap.

---

## Give your agents a record of responsibility

```bash
# Start the flight recorder
intent-os proxy start

# Point your agent at it — zero code changes
export OPENAI_BASE_URL=http://localhost:8377
export ANTHROPIC_BASE_URL=http://localhost:8377

# Use your agent normally. Every action is recorded.
claude "refactor the payment module"

# When you need to know what happened:
intent-os doctor
intent-os inspect latest
intent-os cost
```

Works with **Claude Code, Cursor, GitHub Copilot, or any agent** that speaks OpenAI or Anthropic APIs. One environment variable. Nothing else.

Everything runs locally. Your data stays on your machine. One SQLite file. No cloud. No account.

---

## Which of these have you felt?

- **"I'm afraid to give it a big task."** — The agent is capable, but the bigger the task, the more files it touches. You don't know what it changed or why. So you keep giving it small, safe work. The trust gap is capping how much you use AI.

- **"Something went wrong. I have no idea what."** — Agent ran for 30 minutes. Failed. No stack trace. The file is different but you didn't see it happen. You don't know if it wrote 3 lines or deleted a function.

- **"Why is my API bill $300 this month?"** — AI agents call models. A lot. Which agent? Which task? Which model? You can't answer any of those questions.

- **"It worked yesterday. Today it doesn't."** — Same prompt, different result. Model changed? Context shifted? Tool state was different? There's no record of what the execution environment looked like when it succeeded.

Intent OS gives you the answer to all four — before you even ask.

---

## What you get

| Command | What it tells you |
|---------|-------------------|
| `intent-os doctor` | One-command health check: what happened, what went wrong, how to fix it |
| `intent-os inspect latest` | Full execution timeline: every model call, tool use, cost, and duration |
| `intent-os cost` | Spending breakdown: by agent, by model, daily trends |
| `intent-os proxy start` | Start recording — intercepts Claude Code, Cursor, any agent |
| `intent-os proxy doctor` | Check proxy health: running status, traffic stats, agent detection |
| `intent-os agent create --name "My Agent"` | Give every agent a unique identity with role, traits, and avatar |
| `intent-os agent get <id>` | Full person-card profile: role, traits, execution history, experiences |
| `intent-os scan` | Security scan: detect dangerous tool calls and sensitive data in traces |
| `intent-os audit report --format html` | Compliance report for teams: full audit trail with HTML/CSV export |

---

## For teams

When multiple people use multiple agents, "what happened" becomes a business question:

- **Accountability** — `intent-os cost --by agent` — who's spending what, on which model
- **Governance** — `intent-os security policy apply` — define what agents can and can't do
- **Compliance** — `intent-os audit report --format html` — full execution record, any timeframe
- **Identity** — every agent gets an ID, every execution links back to its owner

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

## The first implementation of an Agent Execution Contract

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

**834 tests, 8 skipped, 0 failures** — CI across Python 3.10, 3.11, and 3.12.

---

## License

AGPLv3 + Commercial Option. See [LICENSE](LICENSE).

Open-source use is free under AGPLv3. Commercial use requires a commercial license.

---

*The biggest bottleneck in AI today is not capability. It's trust.*
