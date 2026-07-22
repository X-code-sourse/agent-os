"""
Intent OS — Condition Evaluator Tests

Tests cover the condition expression language used for adaptive execution:
  1. evaluate_condition() — basic operators
  2. Numeric comparisons (>, <, >=, <=, ==, !=)
  3. String comparisons
  4. Exists/not_exists checks
  5. Contains operator
  6. In/not_in operators
  7. Edge cases (empty, malformed, nulls)
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.conditions import evaluate_condition, ConditionSyntaxError


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

SAMPLE_OUTPUTS = {
    "search": {
        "result_count": 5,
        "first_result": "Hello world",
        "results": ["A", "B", "C"],
        "status": "ok",
    },
    "classify": {
        "category": "urgent",
        "confidence": 0.95,
    },
    "fetch": {
        "content": "Some article text here",
        "empty_field": None,
    },
}

SAMPLE_INPUT = {
    "company": "NVIDIA",
    "max_results": 50,
}


# ====================================================================
# 1. Basic Numeric
# ====================================================================

class TestConditionNumeric:
    def test_gt(self):
        assert evaluate_condition("${search.result_count} > 0", SAMPLE_OUTPUTS)
        assert not evaluate_condition("${search.result_count} > 10", SAMPLE_OUTPUTS)

    def test_lt(self):
        assert evaluate_condition("${search.result_count} < 10", SAMPLE_OUTPUTS)
        assert not evaluate_condition("${search.result_count} < 3", SAMPLE_OUTPUTS)

    def test_gte(self):
        assert evaluate_condition("${search.result_count} >= 5", SAMPLE_OUTPUTS)
        assert not evaluate_condition("${search.result_count} >= 6", SAMPLE_OUTPUTS)

    def test_lte(self):
        assert evaluate_condition("${search.result_count} <= 5", SAMPLE_OUTPUTS)
        assert not evaluate_condition("${search.result_count} <= 4", SAMPLE_OUTPUTS)

    def test_eq(self):
        assert evaluate_condition("${search.result_count} == 5", SAMPLE_OUTPUTS)
        assert not evaluate_condition("${search.result_count} == 3", SAMPLE_OUTPUTS)

    def test_neq(self):
        assert evaluate_condition("${search.result_count} != 3", SAMPLE_OUTPUTS)
        assert not evaluate_condition("${search.result_count} != 5", SAMPLE_OUTPUTS)


# ====================================================================
# 2. String
# ====================================================================

class TestConditionString:
    def test_string_eq(self):
        assert evaluate_condition('${classify.category} == "urgent"', SAMPLE_OUTPUTS)
        assert not evaluate_condition('${classify.category} == "low"', SAMPLE_OUTPUTS)

    def test_string_case_insensitive(self):
        assert evaluate_condition('${classify.category} == "URGENT"', SAMPLE_OUTPUTS)

    def test_string_neq(self):
        assert evaluate_condition('${classify.category} != "low"', SAMPLE_OUTPUTS)

    def test_string_contains(self):
        assert evaluate_condition('${search.first_result} contains "Hello"', SAMPLE_OUTPUTS)
        assert not evaluate_condition('${search.first_result} contains "Goodbye"', SAMPLE_OUTPUTS)

    def test_in_list(self):
        assert evaluate_condition('${classify.category} in "urgent"', SAMPLE_OUTPUTS)
        assert not evaluate_condition('${classify.category} in "low,medium"', SAMPLE_OUTPUTS)

    def test_not_in(self):
        assert evaluate_condition('${classify.category} not_in "casual,standard"', SAMPLE_OUTPUTS)


# ====================================================================
# 3. Exists / Not Exists
# ====================================================================

class TestConditionExists:
    def test_exists_true(self):
        assert evaluate_condition("${search.result_count} exists", SAMPLE_OUTPUTS)

    def test_exists_false(self):
        assert not evaluate_condition("${fetch.empty_field} exists", SAMPLE_OUTPUTS)

    def test_not_exists_true(self):
        assert evaluate_condition("${search.nonexistent} not_exists", SAMPLE_OUTPUTS)

    def test_not_exists_false(self):
        assert not evaluate_condition("${search.first_result} not_exists", SAMPLE_OUTPUTS)


# ====================================================================
# 4. Goal References
# ====================================================================

class TestConditionGoalRefs:
    def test_goal_reference(self):
        assert evaluate_condition('${goal.company} == "NVIDIA"', SAMPLE_OUTPUTS, SAMPLE_INPUT)

    def test_goal_mismatch(self):
        assert not evaluate_condition('${goal.company} == "AMD"', SAMPLE_OUTPUTS, SAMPLE_INPUT)


# ====================================================================
# 5. Edge Cases
# ====================================================================

class TestConditionEdgeCases:
    def test_empty_condition(self):
        """Empty condition should return True (always pass)."""
        assert evaluate_condition("", SAMPLE_OUTPUTS)

    def test_none_value_from_missing_task(self):
        """Referencing a non-existent task should return False."""
        assert not evaluate_condition("${nonexistent.field} > 0", SAMPLE_OUTPUTS)

    def test_unknown_operator(self):
        """Unknown operator should raise."""
        with pytest.raises(ConditionSyntaxError):
            evaluate_condition("${search.count} >>> 5", SAMPLE_OUTPUTS)

    def test_malformed_syntax(self):
        """Malformed expression should raise."""
        with pytest.raises(ConditionSyntaxError):
            evaluate_condition("this is not a condition", SAMPLE_OUTPUTS)

    def test_nested_field_access(self):
        """Nested paths should resolve."""
        outputs = {"task": {"nested": {"deep": {"value": 42}}}}
        assert evaluate_condition("${task.nested.deep.value} == 42", outputs)

    def test_whitespace_handling(self):
        """Extra whitespace should be tolerated."""
        assert evaluate_condition('  ${search.result_count}   >   0  ', SAMPLE_OUTPUTS)

    def test_float_comparison(self):
        """Float values should compare correctly."""
        outputs = {"calc": {"score": 0.95}}
        assert evaluate_condition("${calc.score} > 0.9", outputs)
        assert not evaluate_condition("${calc.score} < 0.9", outputs)
