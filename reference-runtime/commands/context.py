"""Intent OS CLI — context command: manage execution contexts.

Create, list, inspect, and manage execution contexts that define
the task-level environment for agent execution boundaries.

    intent-os context create --name "US Stock Analysis" --goal "Find undervalued"
    intent-os context list
    intent-os context get <context_id>
    intent-os context assign <context_id> --agent <agent_id>
    intent-os context agents <context_id>
    intent-os context delete <context_id>
"""
from __future__ import annotations

import sys
from typing import Any

from core.context_store import ContextStore


def cmd_context(args: Any) -> None:
    """Manage execution contexts."""
    action = args.context_action

    if action == "create":
        _cmd_create(args)
    elif action == "list":
        _cmd_list(args)
    elif action in ("get", "inspect"):
        _cmd_get(args)
    elif action == "assign":
        _cmd_assign(args)
    elif action == "agents":
        _cmd_agents(args)
    elif action == "delete":
        _cmd_delete(args)
    else:
        print(f"Unknown context action: {action}", file=sys.stderr)
        sys.exit(1)


def _cmd_create(args: Any) -> None:
    """Create a new execution context."""
    name = getattr(args, "name", None)
    if not name:
        print("Error: --name is required for context create", file=sys.stderr)
        sys.exit(1)

    goal = getattr(args, "goal", "") or ""
    constraints = getattr(args, "constraint", None) or []
    scope = getattr(args, "scope", "") or ""
    parent = getattr(args, "parent", None)
    created_by = getattr(args, "created_by", "") or ""

    store = ContextStore()
    ctx = store.create(
        name=name,
        goal=goal,
        constraints=constraints,
        task_scope=scope,
        parent_context_id=parent,
        created_by=created_by,
    )

    print()
    print("  ================================================")
    print("    Execution Context Created")
    print("  ================================================")
    print()
    print(f"  Context ID:     {ctx['context_id']}")
    print(f"  Name:           {ctx['name']}")
    if ctx["goal"]:
        print(f"  Goal:           {ctx['goal']}")
    if ctx["constraints"]:
        print(f"  Constraints:    {', '.join(ctx['constraints'])}")
    if ctx["task_scope"]:
        print(f"  Scope:          {ctx['task_scope']}")
    if ctx["parent_context_id"]:
        print(f"  Parent:         {ctx['parent_context_id']}")
    if ctx["created_by"]:
        print(f"  Created by:     {ctx['created_by']}")
    print(f"  Created:        {ctx['created_at'][:19]}")
    print()
    print("  Assign an agent to this context:")
    print(f"    intent-os context assign {ctx['context_id']} --agent <agent_id>")
    print()


def _cmd_list(args: Any) -> None:
    """List execution contexts, optionally filtered by creator or assigned agent."""
    created_by = getattr(args, "created_by", None)
    agent_id = getattr(args, "agent", None)
    store = ContextStore()

    if agent_id:
        contexts = store.get_contexts_for_agent(agent_id)
        filter_label = f"agent: {agent_id}"
    elif created_by:
        contexts = store.list(created_by=created_by)
        filter_label = f"created by: {created_by}"
    else:
        contexts = store.list()
        filter_label = None

    if not contexts:
        print("  No execution contexts found.")
        print()
        print("  Create your first context:")
        print('    intent-os context create --name "My Task" --goal "Analyze ..."')
        print()
        return

    print()
    if filter_label:
        print(f"  Execution Contexts ({filter_label}):")
    else:
        print("  Execution Contexts:")
    print(f"  {'Context ID':<22} {'Name':<25} {'Scope':<14} {'Created'}")
    print(f"  {'-'*73}")
    for ctx in contexts:
        cid = ctx["context_id"]
        name = ctx["name"][:24]
        scope = (ctx["task_scope"] or "-")[:13]
        created = ctx["created_at"][:19] if ctx["created_at"] else "?"
        print(f"  {cid:<22} {name:<25} {scope:<14} {created}")
    print()


def _cmd_get(args: Any) -> None:
    """Show details for a specific execution context."""
    ctx_id = args.context_id
    store = ContextStore()
    ctx = store.get(ctx_id)

    if ctx is None:
        print(f"  Context not found: {ctx_id}")
        print()
        print("  List all contexts:")
        print("    intent-os context list")
        print()
        return

    agents = store.get_assigned_agents(ctx_id)

    print()
    print(f"  Context ID:     {ctx['context_id']}")
    print(f"  Name:           {ctx['name']}")
    if ctx["goal"]:
        print(f"  Goal:           {ctx['goal']}")
    print(f"  Scope:          {ctx['task_scope'] or '-'}")
    if ctx["constraints"]:
        print(f"  Constraints:")
        for c in ctx["constraints"]:
            print(f"    - {c}")
    if ctx["variables"]:
        print(f"  Variables:")
        for k, v in ctx["variables"].items():
            print(f"    {k}: {v}")
    if ctx["parent_context_id"]:
        print(f"  Parent:         {ctx['parent_context_id']}")
    if ctx["created_by"]:
        print(f"  Created by:     {ctx['created_by']}")
    print(f"  Created:        {ctx['created_at'][:19] if ctx['created_at'] else '?'}")
    if ctx["expires_at"]:
        print(f"  Expires:        {ctx['expires_at'][:19]}")
    if agents:
        print(f"  Assigned Agents ({len(agents)}):")
        for agent_id in agents:
            print(f"    - {agent_id}")
    else:
        print(f"  Assigned Agents: (none)")
    print()


def _cmd_assign(args: Any) -> None:
    """Assign an agent to an execution context."""
    ctx_id = args.context_id
    agent_id = getattr(args, "agent", None)

    if not agent_id:
        print("Error: --agent is required for context assign", file=sys.stderr)
        sys.exit(1)

    store = ContextStore()

    # Verify the context exists
    ctx = store.get(ctx_id)
    if ctx is None:
        print(f"  Context not found: {ctx_id}", file=sys.stderr)
        print()
        print("  List all contexts:")
        print("    intent-os context list")
        print()
        sys.exit(1)

    ok = store.assign_agent(ctx_id, agent_id)
    if ok:
        print()
        print(f"  Agent '{agent_id}' assigned to context '{ctx_id}'")
        print()
        print(f"  View context details:")
        print(f"    intent-os context get {ctx_id}")
        print()
    else:
        print(f"  Failed to assign agent '{agent_id}' to context '{ctx_id}'", file=sys.stderr)
        sys.exit(1)


def _cmd_agents(args: Any) -> None:
    """List agents assigned to an execution context."""
    ctx_id = args.context_id
    store = ContextStore()

    ctx = store.get(ctx_id)
    if ctx is None:
        print(f"  Context not found: {ctx_id}", file=sys.stderr)
        sys.exit(1)

    agents = store.get_assigned_agents(ctx_id)

    print()
    if not agents:
        print(f"  No agents assigned to context '{ctx_id}'")
        print()
        print("  Assign an agent:")
        print(f"    intent-os context assign {ctx_id} --agent <agent_id>")
        print()
        return

    print(f"  Agents assigned to '{ctx['name']}' ({ctx_id}):")
    print(f"  {'Agent ID':<24}")
    print(f"  {'-'*24}")
    for agent_id in agents:
        print(f"  {agent_id}")
    print()


def _cmd_delete(args: Any) -> None:
    """Delete an execution context."""
    ctx_id = args.context_id
    store = ContextStore()

    if store.delete(ctx_id):
        print(f"  Context deleted: {ctx_id}")
    else:
        print(f"  Context not found: {ctx_id}", file=sys.stderr)
        sys.exit(1)
