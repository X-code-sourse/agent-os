# The Agent Execution Contract

> **Intent OS is building the portable execution contract for AI agents — the infrastructure layer that lets agents accumulate value over time and carry it across any runtime.**
>
> Status: Frozen v1.0 — 2026-07-24
>
> Agents should get better with every task. Intent OS makes that possible.

---

## The Problem

Today's AI Agent ecosystem is a fragmented archipelago:

```
Claude Agent ──◆ locked to Claude Runtime
OpenAI Agent ──◆ locked to OpenAI Runtime  
LangGraph Agent ──◆ locked to LangGraph Runtime
CrewAI Agent ──◆ locked to CrewAI Runtime
```

An Agent's value is trapped inside the framework that built it. You spend months crafting a financial analysis agent — it can't run anywhere else. It can't be shared. It can't be upgraded independently of its runtime. It can't be traded.

This is not a bug. It is a missing layer of infrastructure.

Every major computing era needed an intermediate layer to make capabilities portable:

| Era | Missing Layer | What Solved It |
|-----|-------------|----------------|
| Software | Code → Hardware | Operating System |
| Web | Server → Network | HTTP |
| Cloud | Application → Infrastructure | Containers + Kubernetes |

The AI Agent era has no equivalent. **There is no standard way to say: "Here is an Agent. Here is what it does. Here is what it needs. This is what it did. Run it anywhere."**

---

## What Intent OS Is Building

**An Execution Contract — a portable, runtime-agnostic specification that defines an Agent's identity, capabilities, context, execution behavior, verification evidence, and governance boundaries.**

It is the missing `???` in this diagram:

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

## The Seven Components

An Execution Contract is not one thing. It is seven. Each answers a question that any Agent — regardless of runtime — must answer before it can be trusted to act autonomously.

### 1. Identity — "Who is this agent?"

```
agent_id: agent_a82f91c3
name: Financial Research Agent
owner: trading_desk
version: 2.1.0
permissions: [market_data_read, report_generate]
```

An Agent without identity is an employee without a badge. Identity makes the Agent a discrete digital entity that can own its actions, carry reputation, and be held accountable across any runtime.

### 2. Capability — "What can this agent do?"

```yaml
kind: Capability
metadata:
  name: financial_analysis
  version: 1.0.0
spec:
  input:
    ticker: {type: string}
    period: {type: string}
  output:
    report: {type: object}
    confidence: {type: number}
  requirements:
    tools: [market_data_api]
```

A Capability Manifest is the Agent's interface — its API. Written once, valid on any runtime. The Manifest defines what the Agent expects and what it guarantees to produce, without specifying *how* any particular runtime achieves it.

### 3. Context — "What environment does this agent need?"

```yaml
context_id: ctx_production_us_equities
goal: Identify undervalued S&P 500 stocks
constraints:
  - SEC filings only
  - No forward-looking speculation
  - Max 10 positions
task_scope: research
variables:
  index: S&P 500
  data_sources: [SEC EDGAR, Bloomberg]
```

Context is not memory. It is the formal specification of the execution environment — the project, the goal, the guardrails. Multiple Agents can share one Context, passing work between them along a defined contract.

### 4. Execution — "What did this agent actually do?"

```json
{
  "execution_id": "exec_a82f91",
  "agent_id": "agent_a82f91c3",
  "context_id": "ctx_production_us_equities",
  "events": [
    {"type": "TaskStarted", "timestamp": "14:02:01Z"},
    {"type": "LlmCall", "model": "claude-sonnet-4", "tokens": 2451},
    {"type": "CapabilityInvoked", "capability": "market_data_query"},
    {"type": "TaskCompleted", "latency_ms": 14200, "cost_usd": 0.08}
  ],
  "status": "success"
}
```

Every action, every call, every decision — structured, immutable, replayable. The Execution Record is not a log. It is the Agent's official behavioral transcript. It is what makes accountability possible.

### 5. Verification — "Can we prove its claims?"

```json
{
  "evidence_id": "evi_a1b2c3",
  "execution_id": "exec_a82f91",
  "claim": "NVIDIA gross margin: 78.4%",
  "source_type": "data",
  "source_ref": "NVIDIA 10-Q, page 47, fiscal Q2 2027",
  "confidence": 0.97,
  "verified": true
}
```

An Agent that says "trust me" will not survive an audit. Evidence gives every output a provable anchor — a document, a calculation, an API response — that can be checked after the fact. When a regulator asks "why did this Agent take that action?", the answer is deterministic, not a shrug.

### 6. Governance — "Was it allowed to do that?"

```yaml
policy:
  agent: Financial Research Agent
  allow:
    - market_data_read
    - report_generate
  deny:
    - trade_execute
    - database_delete
  require_review:
    - email_send_to_external
  audit: all
```

Identity tells you *who*. Governance tells you *whether they should have*. Policy, permission, and audit — the layer that transforms an Agent from a script anyone ran into a governed digital entity.

### 7. Experience — "What did this agent learn from doing?"

```
experience_id: exp_a1b2c3d4e5
agent_id: agent_a82f91c3
type: failure_pattern
observation: "Agent hallucinates revenue figures when SEC EDGAR API returns 503.
              Verified against 10-K page 47 — model filled gap with plausible but
              incorrect number."
recommendation: "Always gate financial_analysis on EDGAR health check. If EDGAR
                 unavailable, return PARTIAL_DATA_UNAVAILABLE not a guess."
execution_ids: [exec_a82f91]
confidence: 0.94
domain: financial_research
tags: [hallucination, api_failure, data_gap]
validated: true
```

An Agent that never learns from its mistakes is just an expensive random number generator. Experience captures the patterns that emerge across executions — what went wrong, what worked, which tools are reliable, which models perform best for which tasks, which data sources fail under what conditions. It closes the loop: Execution data feeds Experience, Experience feeds better decisions, better decisions produce cleaner Execution data.

**The 7 experience types:**

| Icon | Type | What it captures |
|------|------|-----------------|
| `[-]` | `failure_pattern` | Recurring failure modes: hallucinations, tool misuse, API timeouts, in-context confusion |
| `[+]` | `success_strategy` | Proven patterns: prompt structures, tool chains, fallback sequences that reliably succeed |
| `[=]` | `tool_preference` | Which tools work best for which tasks, including reliability scores and latencies |
| `[M]` | `model_performance` | Per-model metrics: accuracy on specific task types, cost efficiency, latency under load |
| `[D]` | `data_source_reliability` | Which APIs, databases, and documents are reliable — and under what conditions |
| `[E]` | `environment_constraint` | Environmental gotchas: OS-specific bugs, Python version incompatibilities, network quirks |
| `[U]` | `user_feedback` | Explicit human correction: "that analysis was wrong," "use this source instead" |

**CLI:**
```bash
intent-os experience record --agent <id> --type failure_pattern \
    --observation "Agent hallucinates when API returns 503" \
    --recommendation "Add health check gate" --execution exec_a82f91 \
    --confidence 0.94 --domain financial_research --tag hallucination

intent-os experience list --agent <id> --type success_strategy
intent-os experience get exp_a1b2c3d4e5
intent-os experience extract --agent <id>          # auto-summarize all types
intent-os experience query "EDGAR API failure"      # keyword search
intent-os experience validate exp_a1b2c3d4e5 --valid --success
```

**Why experience matters for the Execution Contract:**

Without Experience, the contract is static — a snapshot of one execution. With Experience, the contract becomes self-improving. Patterns discovered in Layer 7 flow back to Layer 1 (Context — "add this constraint"), Layer 2 (Identity — "this agent needs this capability"), Layer 4 (Verification — "add this claim to the evidence check"), and Layer 5 (Governance — "deny this tool under these conditions"). Experience is the feedback loop that turns a flight recorder into a learning engine.

---

## Why Flight Recorder First?

You cannot build a contract that no one can see being executed.

Before you can standardize an Agent's behavior, you must observe it. Before you can govern it, you must record it. Before you can port it, you must know what it actually did. Before you can learn from it, you must capture what worked and what failed. The Flight Recorder — `intent-os proxy start` — is the data engine for the Execution Contract. Every model call, every tool use, every cost accrual captured today becomes the empirical foundation for the standard tomorrow. Every pattern that emerges from that data becomes the Experience that makes tomorrow's Agent smarter than today's.

```
Phase 1: Observe     → Flight Recorder captures Execution Data
Phase 2: Standardize → Freeze the Execution Contract (Identity + Manifest + Context + Evidence + Record + Experience)
Phase 3: Portable    → Same Agent, any Runtime
Phase 4: Economy     → Agent becomes tradeable asset
```

The strategy is not "build a monitoring tool and hope to grow." It is "use the entry point that already hurts to collect the data that will define the standard."

---

## The Long Bet

When a developer creates a new AI capability, their first thought should be to write an **Intent OS Manifest** — just as naturally as writing an OpenAPI spec for an API. When an enterprise deploys an Agent, they should demand an **Intent OS Execution Record** — just as naturally as demanding an audit trail from a financial system. When an Agent moves from Claude to GPT to an on-premise model, it should carry its **Intent OS Execution Contract** — its identity, its capabilities, its evidence, its governance, and its hard-won experience — intact.

This is not a monitoring tool. This is not a debugger. This is the missing infrastructure layer between AI capabilities and the runtimes that execute them.

**Intent OS is building the portable execution contract for AI agents.**
