"""
Intent OS — Context Injector (Phase C)

Builds a system prompt from an agent's identity and recent experiences,
designed to be injected into LLM API calls via the proxy.

The injection tells the agent who it is, what it knows, and what it has
learned — giving it runtime self-awareness without modifying the agent's
own system prompt.

Usage::

    from core.context_injector import build_injection_prompt

    prompt = build_injection_prompt("agent_a82f91c3")
    # Returns something like:
    # "You are Financial Analyst, a Financial analyst focused on SEC filings.
    #  Traits: cautious, analytical
    #  Recent context: Q2 2026 earnings analysis
    #
    #  You've learned from past executions:
    #  [FAILURE] API timeout during market open
    #  [SUCCESS] Use DCF for valuation"
"""
from __future__ import annotations

from typing import Any


_MAX_EXPERIENCES = 5          # max experiences to include
_MAX_OBS_LENGTH = 120         # truncate long observations


def build_injection_prompt(agent_id: str,
                           max_experiences: int = _MAX_EXPERIENCES,
                           db_path: str | None = None) -> str | None:
    """Build a system-prompt string from agent identity + recent experiences.

    Returns ``None`` when no agent is found (caller skips injection).

    The prompt is designed to be:
    - Short (~100–250 tokens)
    - Informative (identity + top experiences)
    - Non-interfering (does not override the agent's own system prompt)
    """
    # Lazy imports — never block the proxy on missing stores
    try:
        from core.agent_store import AgentStore
        from core.experience_store import ExperienceStore
    except ImportError:
        return None

    # ── 1. Agent identity ──
    store = AgentStore(db_path)
    agent = store.get(agent_id)
    if agent is None:
        return None

    parts: list[str] = []

    # Role line
    if agent.persona:
        parts.append(f"You are {agent.name}, {agent.persona}.")
    else:
        parts.append(f"You are {agent.name}.")

    # Traits line
    traits = agent.traits or []
    if traits:
        parts.append(f"Traits: {', '.join(traits)}")

    # ── 2. Last context (optional) ──
    try:
        from core.context_store import ContextStore
        ctx_store = ContextStore(db_path)
        latest_ctx = ctx_store.get_latest_for_agent(agent_id)
        if latest_ctx and latest_ctx.get("goal"):
            goal = latest_ctx["goal"]
            if len(goal) > 80:
                goal = goal[:77] + "..."
            parts.append(f"Current context: {goal}")
    except Exception:
        pass

    # ── 3. Recent experiences ──
    try:
        exp_store = ExperienceStore(db_path)
        exps = exp_store.list(agent_id=agent_id, limit=max_experiences)
    except Exception:
        exps = []

    if exps:
        _ICONS = {
            "failure_pattern": "[FAILURE]",
            "success_strategy": "[SUCCESS]",
            "tool_preference": "[TOOL]",
            "model_performance": "[MODEL]",
            "data_source_reliability": "[DATA]",
            "environment_constraint": "[ENV]",
            "user_feedback": "[FEEDBACK]",
        }
        parts.append("")
        parts.append("You've learned from past executions:")

        for exp in exps:
            etype = exp.get("type", "")
            obs = (exp.get("observation") or "").strip()
            if len(obs) > _MAX_OBS_LENGTH:
                obs = obs[:_MAX_OBS_LENGTH - 3] + "..."
            if obs:
                icon = _ICONS.get(etype, "[?]")
                parts.append(f"  {icon} {obs}")

    return "\n".join(parts)


def format_openai_messages(messages: list[dict[str, Any]],
                           injection_prompt: str) -> list[dict[str, Any]]:
    """Insert an injection prompt as a system message in an OpenAI messages list.

    The injection is placed **first** in the list so the agent's own
    system prompt (if any) follows — the agent's own instruction takes
    precedence, but the injection provides context.
    """
    result = list(messages)
    if injection_prompt:
        result.insert(0, {"role": "system", "content": injection_prompt})
    return result
