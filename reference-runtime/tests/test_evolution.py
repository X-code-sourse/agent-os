"""
Intent OS — Evolution Loop Tests

Tests cover:
  1. EvolutionLoop.iterate() — full iteration cycle
  2. Auto-apply high-confidence suggestions
  3. Queue medium/low confidence suggestions
  4. approve_suggestion() / reject_suggestion()
  5. get_pending_count() / get_pending_suggestions()
  6. Edge cases — empty EventStore, all auto-applied, all queued
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.evolution import EvolutionLoop, EvolutionLoopError


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

def _make_suggestion(**overrides: Any) -> dict[str, Any]:
    base = {
        "type": "runtime_optimization",
        "suggestion": "Use cheaper runtime",
        "rationale": "Cost analysis shows savings",
        "expected_impact": "~50% cost reduction",
        "confidence": "high",
    }
    base.update(overrides)
    return base


@pytest.fixture
def mock_store():
    return MagicMock()


@pytest.fixture
def mock_analytics():
    return MagicMock()


def _make_loop(store, analytics, tmp_dir: Path, name: str = "evo.db") -> EvolutionLoop:
    return EvolutionLoop(store, analytics, db_path=str(tmp_dir / name))


# ====================================================================
# 1. Iterate — Empty
# ====================================================================

class TestIterateEmpty:
    def test_empty_store_returns_zero_suggestions(self, mock_store, mock_analytics, tmp_path):
        mock_analytics.get_optimization_suggestions.return_value = []
        loop = _make_loop(mock_store, mock_analytics, tmp_path, "empty.db")
        result = loop.iterate()
        assert result["total"] == 0
        assert result["applied_count"] == 0
        assert result["queued_count"] == 0


# ====================================================================
# 2. Iterate — With Suggestions
# ====================================================================

class TestIterateWithSuggestions:
    def test_high_confidence_auto_applies(self, mock_store, mock_analytics, tmp_path):
        mock_analytics.get_optimization_suggestions.return_value = [
            _make_suggestion(confidence="high"),
        ]
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        result = loop.iterate()
        assert result["applied_count"] == 1
        assert result["queued_count"] == 0
        assert result["total"] == 1

    def test_low_confidence_queued(self, mock_store, mock_analytics, tmp_path):
        mock_analytics.get_optimization_suggestions.return_value = [
            _make_suggestion(confidence="low"),
        ]
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        result = loop.iterate()
        assert result["applied_count"] == 0
        assert result["queued_count"] == 1

    def test_medium_confidence_queued(self, mock_store, mock_analytics, tmp_path):
        mock_analytics.get_optimization_suggestions.return_value = [
            _make_suggestion(confidence="medium"),
        ]
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        result = loop.iterate()
        assert result["queued_count"] == 1

    def test_mixed_suggestions(self, mock_store, mock_analytics, tmp_path):
        mock_analytics.get_optimization_suggestions.return_value = [
            _make_suggestion(confidence="high", suggestion="Auto-apply this"),
            _make_suggestion(confidence="low", suggestion="Review this"),
            _make_suggestion(confidence="medium", suggestion="Review this too"),
        ]
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        result = loop.iterate()
        assert result["total"] == 3
        assert result["applied_count"] == 1
        assert result["queued_count"] == 2


# ====================================================================
# 3. Queue Persistence
# ====================================================================

class TestQueuePersistence:
    def test_pending_count(self, mock_store, mock_analytics, tmp_path):
        mock_analytics.get_optimization_suggestions.return_value = [
            _make_suggestion(confidence="low"),
            _make_suggestion(confidence="low"),
        ]
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        loop.iterate()
        assert loop.get_pending_count() == 2

    def test_pending_suggestions_returns_details(self, mock_store, mock_analytics, tmp_path):
        mock_analytics.get_optimization_suggestions.return_value = [
            _make_suggestion(confidence="low", suggestion="Test suggestion",
                             rationale="Test rationale", expected_impact="Test impact"),
        ]
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        loop.iterate()
        pending = loop.get_pending_suggestions()
        assert len(pending) == 1
        s = pending[0]
        assert s["type"] == "runtime_optimization"
        assert s["suggestion"] == "Test suggestion"
        assert s["rationale"] == "Test rationale"

    def test_empty_queue(self, mock_store, mock_analytics, tmp_path):
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        assert loop.get_pending_suggestions() == []
        assert loop.get_pending_count() == 0


# ====================================================================
# 4. Approve / Reject
# ====================================================================

class TestApproveReject:
    def test_approve_suggestion(self, mock_store, mock_analytics, tmp_path):
        mock_analytics.get_optimization_suggestions.return_value = [
            _make_suggestion(confidence="low"),
        ]
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        loop.iterate()
        sid = loop.get_pending_suggestions()[0]["id"]
        assert loop.approve_suggestion(sid)
        assert loop.get_pending_count() == 0

    def test_reject_suggestion(self, mock_store, mock_analytics, tmp_path):
        mock_analytics.get_optimization_suggestions.return_value = [
            _make_suggestion(confidence="low"),
        ]
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        loop.iterate()
        sid = loop.get_pending_suggestions()[0]["id"]
        assert loop.reject_suggestion(sid)
        assert loop.get_pending_count() == 0

    def test_approve_nonexistent_returns_false(self, mock_store, mock_analytics, tmp_path):
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        assert not loop.approve_suggestion(999)

    def test_reject_nonexistent_returns_false(self, mock_store, mock_analytics, tmp_path):
        loop = _make_loop(mock_store, mock_analytics, tmp_path)
        assert not loop.reject_suggestion(999)


# ====================================================================
# 5. CLI Integration
# ====================================================================

class TestEvolutionCLI:
    def test_evolution_run_no_data(self):
        from commands.evolution import cmd_evolution
        with patch("commands.evolution.get_event_store") as mock_es:
            mock_store = MagicMock()
            mock_es.return_value = mock_store
            out, err, code = self._run_cmd(cmd_evolution, {"action": "run"})
            assert code == 0

    def test_evolution_status_no_data(self):
        from commands.evolution import cmd_evolution
        with patch("commands.evolution.get_event_store") as mock_es:
            mock_store = MagicMock()
            mock_es.return_value = mock_store
            out, err, code = self._run_cmd(cmd_evolution, {"action": "status"})
            assert code == 0

    def _run_cmd(self, cmd_func, args_dict):
        import io
        args = type("Args", (), {})()
        for k, v in args_dict.items():
            setattr(args, k, v)
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = [0]
        def fake_exit(code=0):
            exit_code[0] = code
            raise SystemExit(code)
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr), patch("sys.exit", fake_exit):
            try:
                cmd_func(args)
            except SystemExit:
                pass
            except Exception:
                import traceback
                stderr.write(traceback.format_exc())
                exit_code[0] = 1
        return stdout.getvalue(), stderr.getvalue(), exit_code[0]
