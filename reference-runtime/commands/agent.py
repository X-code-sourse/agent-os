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


def _parse_traits(raw: str | None) -> list[str] | None:
    """Parse a comma-separated trait string into a list."""
    if not raw:
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


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
    persona = getattr(args, "persona", "") or ""
    traits_raw = getattr(args, "traits", None)
    traits = _parse_traits(traits_raw) if traits_raw else None
    avatar = getattr(args, "avatar", "") or ""

    store = AgentStore()
    agent = store.create(name=name, description=description, owner=owner,
                         team_id=team_id, persona=persona,
                         traits=traits, avatar=avatar)

    print()
    print("  ================================================")
    print("    Agent Registered")
    print("  ================================================")
    print()
    print(f"  Agent ID:   {agent.agent_id}")
    print(f"  Name:       {agent.name}")
    if agent.avatar:
        print(f"  Avatar:     {agent.avatar}")
    if agent.description:
        print(f"  Description: {agent.description}")
    if agent.persona:
        print(f"  Role:       {agent.persona}")
    if agent.traits:
        print(f"  Traits:     {', '.join(agent.traits)}")
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
    print(f"  {'Agent ID':<24} {'Name':<28} {'Avatar':<6} {'Status':<10} {'Team':<14}")
    print(f"  {'-'*82}")
    for agent in agents:
        status = getattr(agent, "status", "active") or "?"
        team = getattr(agent, "team_id", None) or "-"
        avatar = getattr(agent, "avatar", "") or "-"
        print(f"  {agent.agent_id:<24} {agent.name:<28} {avatar:<6} {status:<10} {team:<14}")
    print()


def _cmd_get(args: Any) -> None:
    """Show the agent's full person-card profile: identity, execution history, experiences."""
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

    # ── Resolve team name ──
    team_label = ""
    if agent.team_id:
        team = store.get_team(agent.team_id)
        team_label = f" ({team['name']})" if team else ""

    # ── Execution stats (from EventStore) ──
    try:
        from commands.helpers import get_event_store
        event_store = get_event_store()
        records = event_store.query_records(limit=1000)
        agent_records = [r for r in records
                         if r.get("agent_id") == agent_id
                         or (isinstance(r.get("agent_name"), str) and r["agent_name"] == agent.name)]
        total_runs = len(agent_records)
        successes = sum(1 for r in agent_records if r.get("status") == "success")
        failures = sum(1 for r in agent_records if r.get("status") in ("failure", "partial"))
        total_cost = sum(r.get("total_cost_usd", 0) or 0 for r in agent_records)
        total_tokens = sum(r.get("total_tokens", 0) or 0 for r in agent_records)

        # 5 most recent executions
        recent = sorted(agent_records,
                        key=lambda r: r.get("created_at", "") or "",
                        reverse=True)[:5]
    except Exception:
        total_runs = successes = failures = total_cost = total_tokens = 0
        recent = []

    # ── Experience stats ──
    try:
        from core.experience_store import ExperienceStore
        exp_store = ExperienceStore()
        exps = exp_store.list(agent_id=agent_id, limit=100)
        exp_by_type: dict[str, int] = {}
        for e in exps:
            t = e.get("type", "unknown")
            exp_by_type[t] = exp_by_type.get(t, 0) + 1
        total_exps = len(exps)
    except Exception:
        exp_by_type = {}
        total_exps = 0

    # ── Experience type icons ──
    _EXP_ICONS = {
        "failure_pattern": "[-]",
        "success_strategy": "[+]",
        "tool_preference": "[=]",
        "model_performance": "[M]",
        "data_source_reliability": "[D]",
        "environment_constraint": "[E]",
        "user_feedback": "[U]",
    }
    _EXP_LABELS = {
        "failure_pattern": "failure",
        "success_strategy": "strategy",
        "tool_preference": "tool_pref",
        "model_performance": "model_perf",
        "data_source_reliability": "data_source",
        "environment_constraint": "env_constr",
        "user_feedback": "feedback",
    }

    avatar_line = f" {agent.avatar}" if agent.avatar else ""
    name_line = f"{agent.name}{avatar_line}"
    status_icon = ">" if agent.status == "active" else "o" if agent.status == "paused" else "x"
    last_seen_line = f"Last Run:  {agent.last_seen_at[:19]}" if agent.last_seen_at else "Last Run:  (never)"

    print()
    print(f"  =================================================")
    print(f"    Agent Profile")
    print(f"  =================================================")
    print()
    print(f"  ID:           {agent.agent_id}")
    print(f"  Name:         {name_line}")
    if agent.persona:
        print(f"  Role:         {agent.persona}")
    if agent.owner:
        print(f"  Owner:        {agent.owner}")
    if agent.team_id:
        print(f"  Team:         {agent.team_id}{team_label}")
    status_line = f"{status_icon}  {agent.status}"
    if agent.status == "active":
        status_line += " (receiving executions)"
    print(f"  Status:       {status_line}")
    if agent.traits:
        print(f"  Traits:       {', '.join(agent.traits)}")
    print(f"  Created:      {agent.created_at[:19] if agent.created_at else '?'}")
    print(f"  {last_seen_line}")
    print()

    # ── Capabilities ──
    caps = agent.capabilities or []
    if caps:
        print(f"  Capabilities ({len(caps)}):")
        for c in caps:
            print(f"    ✓ {c}")
        print()

    # ── Experiences ──
    if total_exps > 0:
        print(f"  Experience ({total_exps}):")
        for etype, count in sorted(exp_by_type.items()):
            icon = _EXP_ICONS.get(etype, "[?]")
            label = _EXP_LABELS.get(etype, etype)
            print(f"    {icon} {label:<18} {count}")
        print()

    # ── Execution History ──
    success_rate = successes / total_runs if total_runs > 0 else 0
    avg_cost = total_cost / total_runs if total_runs > 0 else 0
    print(f"  Execution History ({total_runs} runs):")
    if total_runs > 0:
        bar_len = 20
        filled = int(success_rate * bar_len)
        bar = "#" * filled + "." * (bar_len - filled)
        print(f"    ✓ Success:  {successes}  ({success_rate:.0%})  {bar}")
        print(f"    ✗ Failed:   {failures}  ({(1-success_rate):.0%})")
        print(f"    Total cost:    ${total_cost:.4f}")
        print(f"    Avg cost/run:  ${avg_cost:.4f}")
        print(f"    Total tokens:  {total_tokens:,}")
    else:
        print("    (no execution data yet)")
    print()

    # ── Recent Executions ──
    if recent:
        print(f"  Recent Executions:")
        header = f"  {'Date':<22} {'Task':<30} {'Result':<10} {'Cost':<10}"
        print(header)
        print(f"  {'-'*(len(header)-2)}")
        for r in recent:
            created = (r.get("created_at") or "?")[:19]
            task = r.get("manifest_name") or r.get("capability") or "-"
            status_r = r.get("status", "?")
            status_sym = "✓" if status_r == "success" else "✗" if status_r in ("failure", "partial") else "?"
            cost = f"${r.get('total_cost_usd', 0) or 0:.2f}"
            print(f"  {created:<22} {task:<30} {status_sym:<10} {cost:<10}")
        print()

    # ── Next steps ──
    if total_runs == 0:
        print(f"  This agent has no execution data yet.")
        print(f"  Start capturing:  intent-os proxy start --agent {agent.agent_id}")
        print()
    else:
        print(f"  See full execution timeline:  intent-os inspect latest --agent {agent.agent_id}")
        print(f"  View agent experiences:       intent-os experience list --agent {agent.agent_id}")
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
    """Update agent fields (persona, traits, avatar, owner, team, status, capabilities, policies)."""
    agent_id = args.agent_id
    store = AgentStore()
    agent = store.get(agent_id)
    if agent is None:
        print(f"  Agent not found: {agent_id}", file=sys.stderr)
        sys.exit(1)

    updates: dict[str, Any] = {}

    # Simple field replacements
    for field in ("name", "description", "owner", "team_id", "status", "persona", "avatar"):
        val = getattr(args, field, None)
        if val is not None:
            updates[field] = val

    # Trait management: + prefix = add, - prefix = remove, no prefix = replace
    traits_raw = getattr(args, "traits", None)
    if traits_raw is not None:
        parts = [t.strip() for t in traits_raw.split(",") if t.strip()]
        add_traits = [t[1:] for t in parts if t.startswith("+") and len(t) > 1]
        remove_traits = [t[1:] for t in parts if t.startswith("-") and len(t) > 1]
        set_traits = [t for t in parts if not t.startswith("+") and not t.startswith("-")]

        current = list(agent.traits)

        if set_traits:
            # Replace mode
            updates["traits"] = set_traits
        else:
            # Add/remove mode
            result = [t for t in current if t not in remove_traits]
            for t in add_traits:
                if t not in result:
                    result.append(t)
            if result != current:
                updates["traits"] = result

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
        print("  No updates provided. Use --name, --persona, --traits, --avatar, --owner, --status, --capability, --policy")
        sys.exit(1)

    updated = store.update_agent(agent_id, **updates)
    if updated:
        print()
        print("  ================================================")
        print("    Agent Updated")
        print("  ================================================")
        print()
        avatar_line = f" {updated.avatar}" if updated.avatar else ""
        print(f"  Agent ID:  {updated.agent_id}")
        print(f"  Name:      {updated.name}{avatar_line}")
        if updated.persona:
            print(f"  Role:      {updated.persona}")
        if updated.traits:
            print(f"  Traits:    {', '.join(updated.traits)}")
        if updated.owner:
            print(f"  Owner:     {updated.owner}")
        if updated.team_id:
            print(f"  Team:      {updated.team_id}")
        print(f"  Status:    {updated.status}")
        if updated.capabilities:
            print(f"  Capabilities: {', '.join(updated.capabilities)}")
        if updated.policy_ids:
            print(f"  Policies:  {', '.join(updated.policy_ids)}")
        print()


def _cmd_status(args: Any) -> None:
    """Quick execution stats for an agent."""
    from commands.helpers import get_event_store
    agent_id = args.agent_id
    store = AgentStore()
    agent = store.get(agent_id)
    if agent is None:
        print(f"  Agent not found: {agent_id}", file=sys.stderr)
        sys.exit(1)

    event_store = get_event_store()
    records = event_store.query_records(limit=1000)

    agent_records = [r for r in records
                     if r.get("agent_id") == agent_id
                     or (isinstance(r.get("agent_name"), str) and r["agent_name"] == agent.name)]
    total_runs = len(agent_records)
    successes = sum(1 for r in agent_records if r.get("status") == "success")
    failures = sum(1 for r in agent_records if r.get("status") in ("failure", "partial"))
    total_cost = sum(r.get("total_cost_usd", 0) or 0 for r in agent_records)
    total_tokens = sum(r.get("total_tokens", 0) or 0 for r in agent_records)

    avatar_line = f" {agent.avatar}" if agent.avatar else ""
    status_icon = ">" if agent.status == "active" else "o"
    print()
    print(f"  ==========================================══")
    print(f"    Agent: {agent.name}{avatar_line}")
    print(f"  ==========================================══")
    print()
    print(f"  {status_icon}  Status:       {agent.status}")
    if agent.persona:
        print(f"  Role:         {agent.persona}")
    if agent.traits:
        print(f"  Traits:       {', '.join(agent.traits)}")
    print(f"  Created:      {agent.created_at[:19]}")
    if agent.last_seen_at:
        print(f"  Last seen:    {agent.last_seen_at[:19]}")
    print()
    print(f"  Execution Stats:")
    print(f"    Total runs:   {total_runs}")
    if total_runs > 0:
        print(f"    Success rate: {successes/total_runs:.1%}")
    print(f"    Total cost:   ${total_cost:.4f}")
    print(f"    Total tokens: {total_tokens:,}")
    print()
    print(f"  Full profile:  intent-os agent get {agent_id}")
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
