"""Tests for Relationship Context (SPEC-0010 Layer 5)."""
from __future__ import annotations

from core.relationship_context import (
    RelationshipProfile,
    TeamInfo,
    CollaborationSummary,
    compute_relationships,
    format_relationships,
)


class TestRelationshipProfile:
    """RelationshipProfile and sub-dataclasses."""

    def test_empty_profile(self) -> None:
        """Agent with no teams returns empty profile."""
        rel = compute_relationships("agent_nonexistent")
        assert isinstance(rel, RelationshipProfile)
        assert rel.teams == []
        assert rel.collaborations == []

    def test_format_empty(self) -> None:
        """Empty profile formats to empty string."""
        text = format_relationships(RelationshipProfile())
        assert text == ""

    def test_format_with_team(self) -> None:
        """Profile with a team includes team info."""
        profile = RelationshipProfile(
            teams=[TeamInfo(team_id="team_1", name="Research", member_count=3)]
        )
        text = format_relationships(profile)
        assert "Research" in text
        assert "3" in text

    def test_format_with_collaboration(self) -> None:
        """Profile with collaborators includes them."""
        profile = RelationshipProfile(
            collaborations=[
                CollaborationSummary(teammate_id="agent_b", teammate_name="Helper",
                                     shared_tasks=15, shared_success_rate=0.9)
            ]
        )
        text = format_relationships(profile)
        assert "Helper" in text
        assert "15" in text


class TestTeamInfo:
    """TeamInfo dataclass."""

    def test_create(self) -> None:
        t = TeamInfo(team_id="team_1", name="Traders", member_count=5)
        assert t.team_id == "team_1"
        assert t.name == "Traders"
        assert t.member_count == 5

    def test_defaults(self) -> None:
        t = TeamInfo(team_id="team_1", name="Test")
        assert t.member_count == 0


class TestCollaborationSummary:
    """CollaborationSummary dataclass."""

    def test_create(self) -> None:
        c = CollaborationSummary(teammate_id="agent_b", shared_tasks=10,
                                 shared_success_rate=0.85)
        assert c.teammate_id == "agent_b"
        assert c.shared_tasks == 10
        assert c.shared_success_rate == 0.85
