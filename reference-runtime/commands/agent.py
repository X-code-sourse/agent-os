"""Intent OS CLI — agent command: manage AI agent identities.

Register, list, and manage agent identities that are used to
track executions, enforce policies, and generate audit trails.

    intent-os agent create --name "My Agent" [--owner user@email] [--team team_id]
    intent-os agent list [--team team_id]
    intent-os agent get <agent_id>
    intent-os agent delete <agent_id>
    intent-os agent team create --name "My Team" [--description "..."] [--owner user@email]
    intent-os agent team list
    intent-os agent team get <team_id>
    intent-os agent team add --team <team_id> --agent <agent_id>
"""
from __future__ import annotations

import sys
from typing import Any

from core.agent_store import AgentStore


def cmd_agent(args: Any) -> None:
    """Manage AI agent identities and teams."""
    action = args.agent_action

    if action == "create":
        _cmd_create(args)
    elif action == "list":
        _cmd_list(args)
    elif action == "get":
        _cmd_get(args)
    elif action == "update":
        _cmd_update(args)
    elif action == "delete":
        _cmd_delete(args)
    elif action == "status":
        _cmd_status(args)
    elif action == "capability":
        _cmd_capability(args)
    elif action == "team":
        _cmd_team(args)
    else:
        print(f"Unknown agent action: {action}", file=sys.stderr)
        sys.exit(1)


def _cmd_create(args: Any) -> None:
    """Register a new agent."""
    name = getattr(args, "name", "") or "unnamed-agent"
    description = getattr(args, "description", "") or ""
    owner = getattr(args, "owner", "") or ""
    team_id = getattr(args, "team", None)

    store = AgentStore()
    agent = store.create(name=name, description=description, owner=owner, team_id=team_id)

    print()
    print("  ================================================")
    print("    Agent Registered")
    print("  ================================================")
    print()
    print(f"  Agent ID:   {agent.agent_id}")
    print(f"  Name:       {agent.name}")
    if agent.description:
        print(f"  Description: {agent.description}")
    if agent.owner:
        print(f"  Owner:      {agent.owner}")
    if agent.team_id:
        print(f"  Team:       {agent.team_id}")
    print(f"  Created:    {agent.created_at[:19]}")
    print()
    print("  Use this agent ID with the proxy:")
    print(f"    intent-os proxy start --agent {agent.agent_id}")
    print()
    print("  All executions captured by this proxy will be")
    print("  associated with this agent.")
    print()


def _cmd_list(args: Any) -> None:
    """List all registered agents, optionally filtered by team."""
    team_id = getattr(args, "team", None)
    store = AgentStore()
    agents = store.list(team_id=team_id)

    if not agents:
        if team_id:
            print(f"  No agents found in team: {team_id}")
        else:
            print("  No agents registered.")
            print()
            print("  Create your first agent:")
            print("    intent-os agent create --name \"Coding Agent\"")
        print()
        return

    print()
    if team_id:
        print(f"  Agents in Team {team_id}:")
    else:
        print("  Registered Agents:")
    print(f"  {'Agent ID':<24} {'Name':<25} {'Status':<10} {'Team':<14}")
    print(f"  {'-'*73}")
    for agent in agents:
        status = getattr(agent, "status", "active") or "?"
        team = getattr(agent, "team_id", None) or "-"
        print(f"  {agent.agent_id:<24} {agent.name:<25} {status:<10} {team:<14}")
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
    print(f"  Agent ID:     {agent.agent_id}")
    print(f"  Name:         {agent.name}")
    if agent.description:
        print(f"  Description:  {agent.description}")
    if agent.owner:
        print(f"  Owner:        {agent.owner}")
    if agent.team_id:
        # Attempt to resolve team name
        team = store.get_team(agent.team_id)
        team_label = f" ({team['name']})" if team else ""
        print(f"  Team:         {agent.team_id}{team_label}")
    capabilities = getattr(agent, "capabilities", []) or []
    print(f"  Capabilities: {', '.join(capabilities) if capabilities else 'none'}")
    policy_ids = getattr(agent, "policy_ids", []) or []
    print(f"  Policies:     {', '.join(policy_ids) if policy_ids else 'none'}")
    status = getattr(agent, "status", "active") or "?"
    print(f"  Status:       {status}")
    print(f"  Created:      {agent.created_at[:19] if agent.created_at else '?'}")
    if agent.last_seen_at:
        print(f"  Last seen:    {agent.last_seen_at[:19]}")
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


def _cmd_update(args: Any) -> None:
    """Update agent fields (owner, team, status, capabilities, policies)."""
    agent_id = args.agent_id
    store = AgentStore()
    agent = store.get(agent_id)
    if agent is None:
        print(f"  Agent not found: {agent_id}", file=sys.stderr)
        sys.exit(1)

    updates: dict[str, Any] = {}
    for field in ("name", "description", "owner", "team_id", "status"):
        val = getattr(args, field, None)
        if val is not None:
            updates[field] = val

    # Merge capabilities and policies if provided
    caps = getattr(args, "capability", None)
    if caps:
        merged = list(set(agent.capabilities + caps))
        updates["capabilities"] = merged
    pols = getattr(args, "policy", None)
    if pols:
        merged = list(set(agent.policy_ids + pols))
        updates["policy_ids"] = merged

    if not updates:
        print("  No updates provided. Use --name, --owner, --status, --capability, --policy")
        sys.exit(1)

    updated = store.update_agent(agent_id, **updates)
    if updated:
        print()
        print("  ================================================")
        print("    Agent Updated")
        print("  ================================================")
        print()
        print(f"  Agent ID:     {updated.agent_id}")
        print(f"  Name:         {updated.name}")
        if updated.owner:
            print(f"  Owner:        {updated.owner}")
        if updated.team_id:
            print(f"  Team:         {updated.team_id}")
        print(f"  Status:       {updated.status}")
        if updated.capabilities:
            print(f"  Capabilities: {', '.join(updated.capabilities)}")
        if updated.policy_ids:
            print(f"  Policies:     {', '.join(updated.policy_ids)}")
        print()


def _cmd_status(args: Any) -> None:
    """Show agent execution statistics (Blueprint Phase 2.2)."""
    from commands.helpers import get_event_store
    agent_id = args.agent_id
    store = AgentStore()
    agent = store.get(agent_id)
    if agent is None:
        print(f"  Agent not found: {agent_id}", file=sys.stderr)
        sys.exit(1)

    event_store = get_event_store()
    records = event_store.query_records(limit=1000)

    # Filter records for this agent (by agent_id column or by proxy source_agent)
    agent_records = [r for r in records
                     if r.get("agent_id") == agent_id
                     or (isinstance(r.get("agent_name"), str) and r["agent_name"] == agent.name)]
    total_runs = len(agent_records)
    successes = sum(1 for r in agent_records if r.get("status") == "success")
    failures = sum(1 for r in agent_records if r.get("status") in ("failure", "partial"))
    total_cost = sum(r.get("total_cost_usd", 0) or 0 for r in agent_records)
    total_tokens = sum(r.get("total_tokens", 0) or 0 for r in agent_records)

    print()
    print("  ================================================")
    print("    Agent Status")
    print("  ================================================")
    print()
    print(f"  Agent ID:     {agent.agent_id}")
    print(f"  Name:         {agent.name}")
    print(f"  Status:       {agent.status}")
    print(f"  Owner:        {agent.owner or '(none)'}")
    print(f"  Team:         {agent.team_id or '(none)'}")
    print(f"  Created:      {agent.created_at[:19]}")
    if agent.last_seen_at:
        print(f"  Last seen:    {agent.last_seen_at[:19]}")
    print()
    print(f"  Total runs:   {total_runs}")
    if total_runs > 0:
        print(f"  Success rate: {successes/total_runs:.1%}")
    print(f"  Total cost:   ${total_cost:.4f}")
    print(f"  Total tokens: {total_tokens}")
    if agent.capabilities:
        print(f"  Capabilities: {', '.join(agent.capabilities)}")
    print()


def _cmd_capability(args: Any) -> None:
    """Manage agent capabilities (Blueprint Phase 2.2)."""
    sub = getattr(args, "capability_action", None)
    if sub == "grant":
        _cap_grant(args)
    elif sub == "revoke":
        _cap_revoke(args)
    elif sub == "list":
        _cap_list(args)
    else:
        print(f"  Usage: intent-os agent capability {{grant|revoke|list}} ...", file=sys.stderr)
        sys.exit(1)


def _cap_grant(args: Any) -> None:
    store = AgentStore()
    agent = store.get(args.agent)
    if agent is None:
        print(f"  Agent not found: {args.agent}", file=sys.stderr)
        sys.exit(1)
    merged = list(set(agent.capabilities + [args.capability]))
    store.update_agent(args.agent, capabilities=merged)
    print(f"  Granted '{args.capability}' to agent {agent.name}")
    print(f"  Capabilities: {', '.join(merged)}")


def _cap_revoke(args: Any) -> None:
    store = AgentStore()
    agent = store.get(args.agent)
    if agent is None:
        print(f"  Agent not found: {args.agent}", file=sys.stderr)
        sys.exit(1)
    if args.capability not in agent.capabilities:
        print(f"  Capability '{args.capability}' not found on agent {agent.name}")
        sys.exit(1)
    new_caps = [c for c in agent.capabilities if c != args.capability]
    store.update_agent(args.agent, capabilities=new_caps)
    print(f"  Revoked '{args.capability}' from agent {agent.name}")
    if new_caps:
        print(f"  Remaining: {', '.join(new_caps)}")


def _cap_list(args: Any) -> None:
    store = AgentStore()
    agent = store.get(args.agent_id)
    if agent is None:
        print(f"  Agent not found: {args.agent_id}", file=sys.stderr)
        sys.exit(1)
    print(f"  Agent: {agent.name}")
    if agent.capabilities:
        print(f"  Capabilities:")
        for c in agent.capabilities:
            print(f"    - {c}")
    else:
        print(f"  No capabilities assigned.")


# ── Team subcommands ────────────────────────────────────────────


def _cmd_team(args: Any) -> None:
    """Dispatch team subcommands."""
    team_action = getattr(args, "team_action", None)

    if team_action == "create":
        _team_create(args)
    elif team_action == "list":
        _team_list()
    elif team_action == "get":
        _team_get(args)
    elif team_action == "add":
        _team_add(args)
    else:
        print(f"Unknown team action: {team_action}", file=sys.stderr)
        print()
        print("  Available team actions:")
        print("    intent-os agent team create --name <name> [--description ...] [--owner ...]")
        print("    intent-os agent team list")
        print("    intent-os agent team get <team_id>")
        print("    intent-os agent team add --team <team_id> --agent <agent_id>")
        print()
        sys.exit(1)


def _team_create(args: Any) -> None:
    """Create a new team."""
    name = getattr(args, "name", "") or "unnamed-team"
    description = getattr(args, "description", "") or ""
    owner = getattr(args, "owner", "") or ""

    store = AgentStore()
    team = store.create_team(name=name, description=description, owner=owner)

    print()
    print("  ================================================")
    print("    Team Created")
    print("  ================================================")
    print()
    print(f"  Team ID:     {team['team_id']}")
    print(f"  Name:        {team['name']}")
    if team["description"]:
        print(f"  Description: {team['description']}")
    if team["owner"]:
        print(f"  Owner:       {team['owner']}")
    print(f"  Members:     {len(team['member_ids'])}")
    print(f"  Created:     {team['created_at'][:19]}")
    print()
    print("  Add agents to this team:")
    print(f"    intent-os agent team add --team {team['team_id']} --agent <agent_id>")
    print()


def _team_list() -> None:
    """List all teams."""
    store = AgentStore()
    teams = store.list_teams()

    if not teams:
        print("  No teams registered.")
        print()
        print("  Create your first team:")
        print("    intent-os agent team create --name \"Trading Squad\"")
        print()
        return

    print()
    print("  Registered Teams:")
    print(f"  {'Team ID':<20} {'Name':<22} {'Members':<8} {'Owner':<20}")
    print(f"  {'-'*70}")
    for team in teams:
        member_count = len(team.get("member_ids", []))
        owner = team.get("owner", "") or "-"
        print(f"  {team['team_id']:<20} {team['name']:<22} {member_count:<8} {owner:<20}")
    print()


def _team_get(args: Any) -> None:
    """Show details for a specific team."""
    team_id = args.team_id
    store = AgentStore()
    team = store.get_team(team_id)

    if team is None:
        print(f"  Team not found: {team_id}")
        print()
        print("  List registered teams:")
        print("    intent-os agent team list")
        print()
        return

    member_ids = team.get("member_ids", [])
    policy_ids = team.get("policy_ids", [])

    print()
    print(f"  Team ID:      {team['team_id']}")
    print(f"  Name:         {team['name']}")
    if team["description"]:
        print(f"  Description:  {team['description']}")
    if team["owner"]:
        print(f"  Owner:        {team['owner']}")
    print(f"  Members:      {len(member_ids)}")
    if member_ids:
        for mid in member_ids:
            agent = store.get(mid)
            label = f" {agent.name}" if agent else ""
            print(f"    - {mid}{label}")
    print(f"  Policies:     {', '.join(policy_ids) if policy_ids else 'none'}")
    print(f"  Created:      {team['created_at'][:19]}")
    print()


def _team_add(args: Any) -> None:
    """Add an agent to a team."""
    team_id = getattr(args, "team", None)
    agent_id = getattr(args, "agent", None)

    if not team_id or not agent_id:
        print("  Both --team and --agent are required.", file=sys.stderr)
        print()
        print("  Usage: intent-os agent team add --team <team_id> --agent <agent_id>")
        print()
        sys.exit(1)

    store = AgentStore()

    # Validate team exists
    team_before = store.get_team(team_id)
    if team_before is None:
        print(f"  Team not found: {team_id}", file=sys.stderr)
        sys.exit(1)

    # Validate agent exists
    agent = store.get(agent_id)
    if agent is None:
        print(f"  Agent not found: {agent_id}", file=sys.stderr)
        sys.exit(1)

    before_members = team_before.get("member_ids", [])

    if agent_id in before_members:
        print(f"  Agent {agent_id} is already a member of team {team_id}.")
        print()
        return

    success = store.add_team_member(team_id, agent_id)

    if not success:
        print(f"  Failed to add agent {agent_id} to team {team_id}.", file=sys.stderr)
        sys.exit(1)

    # Fetch team again for after state
    team_after = store.get_team(team_id)

    print()
    print("  ================================================")
    print("    Agent Added to Team")
    print("  ================================================")
    print()
    print(f"  Team:       {team_id} ({team_before['name']})")
    print(f"  Agent:      {agent_id} ({agent.name})")
    print()
    print(f"  Before:     {len(before_members)} member(s)")
    if before_members:
        for mid in before_members:
            a = store.get(mid)
            label = f" {a.name}" if a else ""
            print(f"    - {mid}{label}")
    else:
        print("    (none)")
    print()
    after_members = team_after.get("member_ids", [])
    print(f"  After:      {len(after_members)} member(s)")
    for mid in after_members:
        a = store.get(mid)
        label = f" {a.name}" if a else ""
        marker = "  <-- new" if mid == agent_id else ""
        print(f"    - {mid}{label}{marker}")
    print()
