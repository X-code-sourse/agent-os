"""
Intent OS — Relationship Context (SPEC-0010 Layer 5)

Aggregates an agent's teams and collaboration history from existing
SQLite data. Pure computation — no new tables.

Usage::

    from core.relationship_context import compute_relationships

    rel = compute_relationships("agent_a82f91c3")
    for team in rel.teams:
        print(f"{team.name}: {team.member_count} members")
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TeamInfo:
    """A team this agent belongs to."""
    team_id: str
    name: str
    member_count: int = 0
    member_ids: list[str] = field(default_factory=list)


@dataclass
class CollaborationSummary:
    """How often this agent has worked with another agent."""
    teammate_id: str
    teammate_name: str = ""
    shared_tasks: int = 0
    shared_success_rate: float = 0.0


@dataclass
class RelationshipProfile:
    """Who this agent works with."""
    teams: list[TeamInfo] = field(default_factory=list)
    collaborations: list[CollaborationSummary] = field(default_factory=list)


def compute_relationships(agent_id: str,
                          agent_name: str | None = None,
                          db_path: str | None = None) -> RelationshipProfile:
    """Compute relationship context from teams + execution data.

    Args:
        agent_id: The agent to profile.
        agent_name: Optional name for matching in execution_records.
        db_path: Optional custom database path (for testing).

    Returns:
        A :class:`RelationshipProfile`.
    """
    from core.agent_store import AgentStore
    from core.event_store import EventStore

    store = AgentStore(db_path)
    teams: list[TeamInfo] = []
    collaborations: list[CollaborationSummary] = []

    # ── Teams ──
    try:
        all_teams = store.list_teams()
        for team_raw in all_teams:
            member_ids = team_raw.get("member_ids", []) or []
            if agent_id in member_ids:
                teams.append(TeamInfo(
                    team_id=team_raw["team_id"],
                    name=team_raw.get("name", ""),
                    member_count=len(member_ids),
                    member_ids=member_ids,
                ))
    except Exception:
        pass

    # ── Collaborations from execution_records ──
    try:
        event_store = EventStore(db_path)
        conn = event_store.get_connection()

        # Find context_ids this agent has used
        context_rows = conn.execute(
            """SELECT DISTINCT context_id FROM execution_records
               WHERE agent_id = ? AND context_id IS NOT NULL""",
            (agent_id,),
        ).fetchall()

        context_ids = [r["context_id"] for r in context_rows]
        if context_ids:
            placeholders = ",".join("?" for _ in context_ids)
            # Find other agents that shared those contexts
            collab_rows = conn.execute(
                f"""SELECT agent_id, agent_name, COUNT(*) AS task_count,
                           SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count
                    FROM execution_records
                    WHERE context_id IN ({placeholders})
                      AND agent_id != ?
                    GROUP BY agent_id
                    ORDER BY task_count DESC
                    LIMIT 10""",
                (*context_ids, agent_id),
            ).fetchall()

            for row in collab_rows:
                tid = row["agent_id"] or "unknown"
                total = row["task_count"] or 0
                successes = row["success_count"] or 0
                collaborations.append(CollaborationSummary(
                    teammate_id=tid,
                    teammate_name=row["agent_name"] or "",
                    shared_tasks=total,
                    shared_success_rate=successes / max(total, 1),
                ))
        conn.close()
    except Exception:
        pass

    return RelationshipProfile(teams=teams, collaborations=collaborations)


def format_relationships(profile: RelationshipProfile | None = None,
                         agent_id: str | None = None) -> str:
    """Format relationship context for prompt injection."""
    if profile is None and agent_id:
        profile = compute_relationships(agent_id)
    elif profile is None:
        return ""

    lines: list[str] = []
    if profile.teams:
        for t in profile.teams:
            lines.append(f"Team: {t.name} ({t.member_count} members)")
    if profile.collaborations:
        collab_strs = []
        for c in profile.collaborations[:3]:
            name = c.teammate_name or c.teammate_id[:16]
            collab_strs.append(f"{name} ({c.shared_tasks} shared tasks)")
        if collab_strs:
            lines.append(f"Collaborators: {' | '.join(collab_strs)}")
    return "\n".join(lines)
