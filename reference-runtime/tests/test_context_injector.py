"""Tests for Context Injector (Phase C — runtime self-awareness)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.agent_store import AgentStore
from core.experience_store import ExperienceStore


class TestContextInjector:
    """build_injection_prompt() produces useful system prompts."""

    def test_build_with_agent_only(self, tmp_path: Path) -> None:
        """A basic agent without experiences gets identity prompt."""
        from core.context_injector import build_injection_prompt

        db = tmp_path / "test_i1.db"
        store = AgentStore(str(db))
        agent = store.create(name="Research Bot", persona="Stock analyst",
                             traits=["cautious", "analytical"])

        prompt = build_injection_prompt(agent.agent_id, db_path=str(db))
        assert prompt is not None
        assert "Research Bot" in prompt
        assert "Stock analyst" in prompt
        assert "cautious" in prompt
        assert "analytical" in prompt

    def test_build_no_persona(self, tmp_path: Path) -> None:
        """Agent with no persona — prompt does not break."""
        from core.context_injector import build_injection_prompt

        db = tmp_path / "test_i2.db"
        store = AgentStore(str(db))
        agent = store.create(name="Minimal Agent")

        prompt = build_injection_prompt(agent.agent_id, db_path=str(db))
        assert prompt is not None
        assert "Minimal Agent" in prompt

    def test_build_no_agent(self, tmp_path: Path) -> None:
        """Non-existent agent returns None."""
        from core.context_injector import build_injection_prompt

        assert build_injection_prompt("nonexistent") is None

    def test_build_with_experiences(self, tmp_path: Path) -> None:
        """Agent with experiences gets them in the prompt."""
        from core.context_injector import build_injection_prompt

        db = tmp_path / "test_i3.db"
        store = AgentStore(str(db))
        agent = store.create(name="Exp Bot", persona="Tester")
        exp_store = ExperienceStore(str(db))
        exp_store.create(agent_id=agent.agent_id, type="failure_pattern",
                         observation="API timeout during market open",
                         recommendation="Queue requests")
        exp_store.create(agent_id=agent.agent_id, type="success_strategy",
                         observation="Use DCF for valuation",
                         recommendation="Cross-reference SEC filings")

        prompt = build_injection_prompt(agent.agent_id, db_path=str(db))
        assert prompt is not None
        assert "You've learned" in prompt
        assert "API timeout" in prompt
        assert "Use DCF" in prompt

    def test_build_empty_traits(self, tmp_path: Path) -> None:
        """Agent without traits — no traits line."""
        from core.context_injector import build_injection_prompt

        db = tmp_path / "test_i4.db"
        store = AgentStore(str(db))
        agent = store.create(name="No Traits Bot", persona="Worker")

        prompt = build_injection_prompt(agent.agent_id, db_path=str(db))
        assert prompt is not None
        assert "No Traits" in prompt
        assert "Traits:" not in prompt

    def test_build_experiences_capped(self, tmp_path: Path) -> None:
        """More than MAX experiences only includes the top ones."""
        from core.context_injector import build_injection_prompt

        db = tmp_path / "test_i5.db"
        store = AgentStore(str(db))
        agent = store.create(name="Many Exp Bot", persona="Tester")
        exp_store = ExperienceStore(str(db))
        for i in range(10):
            exp_store.create(agent_id=agent.agent_id,
                             type="failure_pattern",
                             observation=f"Error pattern {i}",
                             recommendation=f"Fix {i}")

        prompt = build_injection_prompt(agent.agent_id, max_experiences=3, db_path=str(db))
        assert prompt is not None
        # Only 3 should be included
        lines = prompt.split("\n")
        exp_lines = [l for l in lines if l.startswith("  [")]
        assert len(exp_lines) == 3

    def test_format_openai_messages(self) -> None:
        """format_openai_messages injects as first system message."""
        from core.context_injector import format_openai_messages

        msgs = [{"role": "user", "content": "hello"}]
        result = format_openai_messages(msgs, "You are X.")
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are X."
        assert result[1]["role"] == "user"
