"""Intent OS CLI — feedback command: record user feedback as experiences.

Allows users to tell the system whether a diagnosis, execution, or
interaction was helpful — recorded as ``user_feedback`` experiences
that the agent can learn from.

    intent-os feedback <agent_id> --helpful --observation "Correct diagnosis"
    intent-os feedback <agent_id> --not-helpful "Missed the real issue"
"""
from __future__ import annotations

import sys
from typing import Any


def cmd_feedback(args: Any) -> None:
    """Record user feedback as an experience."""
    from core.experience_store import ExperienceStore
    from core.agent_store import AgentStore

    agent_id = getattr(args, "agent_id", None)
    if not agent_id:
        print("  Error: agent_id is required.", file=sys.stderr)
        sys.exit(1)

    helpful = getattr(args, "helpful", False)
    not_helpful = getattr(args, "not_helpful", False)
    observation = getattr(args, "observation", "") or ""
    recommendation = observation

    # --observation is the main content; --not-helpful provides alternative
    if not observation and not_helpful:
        if isinstance(not_helpful, str):
            observation = not_helpful
    elif not observation:
        observation = "User provided feedback"

    if helpful:
        obs = f"[HELPFUL] {observation}"
    else:
        obs = f"[NOT HELPFUL] {observation}"

    store = AgentStore()
    agent = store.get(agent_id)
    if agent is None:
        print(f"  Agent not found: {agent_id}", file=sys.stderr)
        sys.exit(1)

    exp_store = ExperienceStore()
    result = exp_store.create(
        agent_id=agent_id,
        type="user_feedback",
        observation=obs[:500],
        recommendation=recommendation[:500],
        structured_situation="user feedback",
        structured_mistake=observation[:200] if not helpful else "",
        structured_lesson=observation[:200] if helpful else "",
        structured_trigger="user_feedback",
    )

    print()
    print("  ================================================")
    print("    Feedback Recorded")
    print("  ================================================")
    print()
    print(f"  Agent:       {agent.name} ({agent_id})")
    print(f"  Type:        {'Helpful' if helpful else 'Not Helpful'}")
    print(f"  Observation: {observation[:100]}")
    print(f"  Experience:  {result['experience_id']}")
    print()
    print(f"  View agent experiences:  intent-os experience list --agent {agent_id}")
    print()
