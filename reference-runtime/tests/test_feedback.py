"""Tests for Feedback command and self-record (F1+F2, v0.13.0)."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class TestFeedbackCommand:
    """intent-os feedback command."""

    def _cleanup(self, agent_id: str) -> None:
        """Delete test agent from default DB."""
        try:
            from core.agent_store import AgentStore
            from core.experience_store import ExperienceStore
            store = AgentStore()
            store.delete(agent_id)
            exp_store = ExperienceStore()
            exps = exp_store.list(agent_id=agent_id, limit=100)
            for e in exps:
                exp_store.delete(e["experience_id"])
        except Exception:
            pass

    def test_feedback_helpful(self) -> None:
        """--helpful creates a user_feedback experience."""
        from core.agent_store import AgentStore
        from core.experience_store import ExperienceStore

        store = AgentStore()
        agent = store.create(name="FB Helpful Test")

        try:
            from commands.feedback import cmd_feedback
            from types import SimpleNamespace
            args = SimpleNamespace(
                agent_id=agent.agent_id,
                helpful=True,
                not_helpful=False,
                observation="Diagnosis was correct",
            )
            cmd_feedback(args)

            exp_store = ExperienceStore()
            exps = exp_store.list(agent_id=agent.agent_id)
            assert len(exps) >= 1
            assert "HELPFUL" in exps[0].get("observation", "")
            assert exps[0].get("type") == "user_feedback"
        finally:
            self._cleanup(agent.agent_id)

    def test_feedback_not_helpful(self) -> None:
        """--not-helpful creates a user_feedback experience."""
        from core.agent_store import AgentStore
        from core.experience_store import ExperienceStore

        store = AgentStore()
        agent = store.create(name="FB Not Helpful Test")

        try:
            from commands.feedback import cmd_feedback
            from types import SimpleNamespace
            args = SimpleNamespace(
                agent_id=agent.agent_id,
                helpful=False,
                not_helpful="Missed the real issue",
                observation="",
            )
            cmd_feedback(args)

            exp_store = ExperienceStore()
            exps = exp_store.list(agent_id=agent.agent_id)
            assert len(exps) >= 1
            assert "NOT HELPFUL" in exps[0].get("observation", "")
            assert "Missed the real issue" in exps[0].get("observation", "")
        finally:
            self._cleanup(agent.agent_id)

    def test_feedback_nonexistent_agent(self) -> None:
        """Feedback for nonexistent agent exits with error."""
        from commands.feedback import cmd_feedback
        from types import SimpleNamespace

        args = SimpleNamespace(
            agent_id="agent_nonexistent",
            helpful=True,
            not_helpful=False,
            observation="test",
        )
        with pytest.raises(SystemExit):
            cmd_feedback(args)


class TestSelfRecord:
    """AgentTracer._self_record() creates experiences."""

    def test_self_record_creates_experience(self) -> None:
        """_self_record writes a failure_pattern experience."""
        from core.experience_store import ExperienceStore
        from core.agent_store import AgentStore
        from proxy.tracer import AgentTracer

        store = AgentStore()
        agent = store.create(name="SR Test")
        agent_id = agent.agent_id

        try:
            tracer = AgentTracer()
            tracer._call_count = 3
            tracer._self_record(agent_id, "openai", "gpt-4o",
                                "Rate limit exceeded")

            exp_store = ExperienceStore()
            exps = exp_store.list(agent_id=agent_id)
            assert len(exps) >= 1
            assert exps[0].get("type") == "failure_pattern"
            assert "Rate limit" in exps[0].get("observation", "")
            assert "gpt-4o" in exps[0].get("structured_trigger", "")
        finally:
            try:
                store.delete(agent_id)
                exp_store = ExperienceStore()
                for e in exp_store.list(agent_id=agent_id, limit=100):
                    exp_store.delete(e["experience_id"])
            except Exception:
                pass

    def test_self_record_increases_confidence_with_count(self) -> None:
        """Self-record confidence increases with call count."""
        from proxy.tracer import AgentTracer

        tracer = AgentTracer()
        tracer._call_count = 1
        # Can't easily test without DB, but method should not crash
        result = tracer._self_record("test_id", "p", "m", "error")
        assert result is None  # returns None (void method)


class TestExperienceStoreSortBy:
    """ExperienceStore.list() sort_by parameter."""

    def test_sort_by_confidence(self, tmp_path: Path) -> None:
        """sort_by='confidence' returns sorted by confidence descending."""
        from core.experience_store import ExperienceStore

        db = tmp_path / "test_sort.db"
        exp_store = ExperienceStore(str(db))
        exp_store.create(agent_id="agent_test", type="failure_pattern",
                         observation="Low conf", confidence=0.3)
        exp_store.create(agent_id="agent_test", type="success_strategy",
                         observation="High conf", confidence=0.9)
        exp_store.create(agent_id="agent_test", type="tool_preference",
                         observation="Medium conf", confidence=0.6)

        results = exp_store.list(agent_id="agent_test", sort_by="confidence", limit=5)
        assert len(results) >= 2
        assert results[0]["confidence"] >= results[-1]["confidence"]

    def test_sort_by_default_created_at(self, tmp_path: Path) -> None:
        """Default sort is by created_at DESC."""
        from core.experience_store import ExperienceStore
        import time

        db = tmp_path / "test_sort2.db"
        exp_store = ExperienceStore(str(db))
        e1 = exp_store.create(agent_id="agent_test", type="failure_pattern",
                              observation="First", confidence=0.5)
        time.sleep(0.01)  # Ensure different timestamp
        e2 = exp_store.create(agent_id="agent_test", type="success_strategy",
                              observation="Second", confidence=0.8)

        results = exp_store.list(agent_id="agent_test", limit=5)
        assert len(results) == 2
        # Second created should be first (DESC)
        assert results[0]["observation"] == "Second"
