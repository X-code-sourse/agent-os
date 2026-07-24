# SPEC-0009: Agent Asset Model

> **Status:** Draft v0.1
> **Phase:** Phase A — Agent Profile Deepening
> **对应代码:** v0.6.0
> **作者:** Intent OS Project

---

## 1. Purpose

Define the standardized data model for an **Agent Asset** — the portable representation of an AI agent as a digital entity with identity, personality, capabilities, experience, and reputation.

This spec formalizes the "Agent as a Person" concept: a different agent is a different person. An agent's asset can be created, enriched through execution, exported, and imported across any runtime.

## 2. Agent Profile Fields

An Agent Profile represents **who this agent is** — its identity, role, and character. It is the foundational layer of the Agent Asset.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agent_id` | string | yes | Unique identifier (`agent_<8hex>`) |
| `name` | string | yes | Human-readable name |
| `persona` | string | no | Role description — who this agent IS (e.g. "Financial analyst focused on SEC filings") |
| `traits` | string[] | no | Behavioural characteristics (e.g. `["cautious", "analytical", "detail-oriented"]`) |
| `avatar` | string | no | Emoji or icon representing this agent (e.g. `"📊"`) |
| `description` | string | no | Free-text description |
| `owner` | string | no | User ID or email who owns this agent |
| `capabilities` | string[] | no | Registered capability references |
| `status` | enum | yes | `active` | `paused` | `revoked` |
| `created_at` | ISO 8601 | yes | When the agent was created |
| `last_seen_at` | ISO 8601 | no | Last execution timestamp |

### 2.1 Traits

Traits are free-form short strings that describe the agent's behavioural or professional characteristics. They are intentionally not constrained to an enum — different roles need different trait vocabularies.

**Examples:**
- Professional traits: `cautious`, `analytical`, `detail-oriented`, `creative`, `conservative`
- Role-based: `technical`, `financial`, `legal`, `medical`, `creative`
- Communication: `concise`, `verbose`, `visual`, `formal`, `casual`

### 2.2 Persona vs Description

| | Persona | Description |
|---|---|---|
| Purpose | Role identity — WHO the agent is | Summary — WHAT the agent does |
| Example | "Financial analyst focused on SEC filings" | "Analyzes quarterly reports for valuation insights" |
| Used in | Character card, agent selection, context injection | Agent list, search |
| Tone | First-person / role-defining | Third-person / functional |

## 3. Reputation Summary

An agent's reputation is derived from its execution history and evidence verification. It is a computed summary, not a stored field.

| Field | Type | Source |
|-------|------|--------|
| `total_executions` | integer | Event Store |
| `success_rate` | float (0.0–1.0) | Successful / Total |
| `total_cost_usd` | float | Sum of all execution costs |
| `total_tokens` | integer | Sum of all execution tokens |
| `avg_cost_per_run` | float | total_cost / total_executions |
| `preferred_models` | string[] | Most-used models from execution records |

## 4. Agent Asset Package (.agent)

> **Phase B — format draft, not yet implemented.**

An `.agent` package bundles the Agent Profile, capabilities, experiences, and reputation summary into one portable JSON file.

```json
{
  "spec_version": "1.0",
  "format": "intent-os-agent-v1",
  "identity": {
    "agent_id": "agent_a82f91c3",
    "name": "Financial Research Assistant",
    "avatar": "📊",
    "persona": "Financial analyst focused on SEC filings",
    "traits": ["cautious", "analytical", "detail-oriented"],
    "owner": "hai@example.com",
    "capabilities": ["market_data_read", "report_generate"],
    "created_at": "2026-07-20T14:02:01"
  },
  "reputation": {
    "total_executions": 47,
    "success_rate": 0.89,
    "avg_cost_per_run": 0.26,
    "total_tokens": 485000,
    "preferred_models": ["claude-sonnet-4"]
  },
  "experiences": [
    {
      "type": "failure_pattern",
      "observation": "Rate limit when querying EDGAR during market open",
      "recommendation": "Queue requests during 9:30-10:00 ET",
      "confidence": 0.85
    }
  ]
}
```

## 5. Lifecycle

```
Create (agent create --persona --traits)
    │
    ▼
Enrich (proxy start --agent → execution data accumulates)
    │
    ▼
Update (agent update --traits +newtrait --persona "...")
    │
    ▼
Package (agent export → .agent)  ← Phase B
    │
    ▼
Import (agent import → new runtime)  ← Phase B
```

## 6. Design Constraints

- **Agent Profile is Metadata Plane** — Identity data, not Control Plane state. CONSTITUTION R1 does not apply.
- **No user-preference memory** — An Agent is a person/role, not a "preference store." What the agent remembers about the user is role-specific (a secretary-agent may remember preferences; a CEO-agent does not).
- **Traits are free-form** — Not constrained to an enum. Different roles need different vocabularies.
- **Reputation is computed** — Derived from Event Store, never stored as a static value.
- **Backward compatibility** — Existing agents without persona/traits/avatar default to empty strings. All CLI commands that read agents work with v0.5.x data.

## 7. Future Work (Phase B)

- Agent Package format (.agent) — export/import
- Cross-Runtime Agent Identity — agent profiles consumed by Claude, Codex, OpenClaw
- Agent Discovery — registry-based agent asset search
