"""Intent OS CLI — agent command: manage AI agent identities.

Register, list, and manage agent identities that are used to
track executions, enforce policies, and generate audit trails.

    intent-os agent create --name "My Agent"
    intent-os agent list
    intent-os agent get <agent_id>
    intent-os agent delete <agent_id>
"""
from __future__ import annotations

import sys
from typing import Any

from core.agent_store import AgentStore


def cmd_agent(args: Any) -> None:
    """Manage AI agent identities."""
    action = args.agent_action

    if action == "create":
        _cmd_create(args)
    elif action == "list":
        _cmd_list()
    elif action == "get":
        _cmd_get(args)
    elif action == "delete":
        _cmd_delete(args)
    else:
        print(f"Unknown agent action: {action}", file=sys.stderr)
        sys.exit(1)


def _cmd_create(args: Any) -> None:
    """Register a new agent."""
    name = getattr(args, "name", "") or "unnamed-agent"
    description = getattr(args, "description", "") or ""

    store = AgentStore()
    agent = store.create(name=name, description=description)

    print()
    print("  ================================================")
    print("    Agent Registered")
    print("  ================================================")
    print()
    print(f"  Agent ID:   {agent.agent_id}")
    print(f"  Name:       {agent.name}")
    if agent.description:
        print(f"  Description: {agent.description}")
    print(f"  Created:    {agent.created_at[:19]}")
    print()
    print("  Use this agent ID with the proxy:")
    print(f"    intent-os proxy start --agent {agent.agent_id}")
    print()
    print("  All executions captured by this proxy will be")
    print("  associated with this agent.")
    print()


def _cmd_list() -> None:
    """List all registered agents."""
    store = AgentStore()
    agents = store.list()

    if not agents:
        print("  No agents registered.")
        print()
        print("  Create your first agent:")
        print("    intent-os agent create --name \"Coding Agent\"")
        print()
        return

    print()
    print("  Registered Agents:")
    print(f"  {'Agent ID':<24} {'Name':<25} {'Executions':<12}")
    print(f"  {'-'*61}")
    for agent in agents:
        print(f"  {agent.agent_id:<24} {agent.name:<25}")
    print()


def _cmd_get(args: Any) -> None:
    """Show details for a specific agent."""
    agent_id = args.agent_id
    store = AgentStore()
    agent = store.get(agent_id)

    if agent is None:
        print(f"  Agent not found: {agent_id}")
        print()
        print("  List registered agents:")
        print("    intent-os agent list")
        print()
        return

    print()
    print(f"  Agent ID:    {agent.agent_id}")
    print(f"  Name:        {agent.name}")
    if agent.description:
        print(f"  Description: {agent.description}")
    print(f"  Created:     {agent.created_at[:19] if agent.created_at else '?'}")
    if agent.last_seen_at:
        print(f"  Last seen:   {agent.last_seen_at[:19]}")
    print()


def _cmd_delete(args: Any) -> None:
    """Remove an agent."""
    agent_id = args.agent_id
    store = AgentStore()

    if store.delete(agent_id):
        print(f"  Agent deleted: {agent_id}")
    else:
        print(f"  Agent not found: {agent_id}", file=sys.stderr)
        sys.exit(1)
