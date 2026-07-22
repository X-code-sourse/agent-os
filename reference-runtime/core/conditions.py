"""
Intent OS — Condition Evaluator for Adaptive Execution Graph

Provides the condition expression language and evaluator for:
  - Conditional edges: only traverse if condition is met
  - Skip conditions: skip a task if condition is true
  - Dynamic routing: choose between multiple downstream paths

Condition syntax:
  ${task_id.field_path} OPERATOR VALUE

Examples:
  ${search.result_count} > 0        — numeric comparison
  ${classify.category} == "urgent"  — string comparison
  ${fetch.content} exists            — null/empty check

All comparisons are case-insensitive for strings.
Evaluator is stateless and deterministic — given same inputs, same result.
"""

from __future__ import annotations

import re
from typing import Any


# ──────────────────────────────────────────────
# Condition Model
# ──────────────────────────────────────────────

class ConditionSyntaxError(Exception):
    """Raised when a condition expression cannot be parsed."""
    pass


@staticmethod
def _normalize_value(v: Any) -> Any:
    """Normalize a value for comparison.

    Handles type coercion: string numbers are parsed, booleans normalized.
    """
    if isinstance(v, str):
        v_stripped = v.strip().strip('"').strip("'")
        # Try numeric parsing
        try:
            if "." in v_stripped:
                return float(v_stripped)
            return int(v_stripped)
        except (ValueError, TypeError):
            pass
        return v_stripped.lower()
    return v


def evaluate_condition(
    condition: str,
    task_outputs: dict[str, Any],
    input_data: dict[str, Any] | None = None,
) -> bool:
    """Evaluate a condition expression against task outputs.

    Args:
        condition: Condition expression string, e.g. "${search.count} > 0".
        task_outputs: Dict of {task_id: output} from completed tasks.
        input_data: Optional workflow input data.

    Returns:
        True if condition is met, False otherwise.

    Raises:
        ConditionSyntaxError: If the condition cannot be parsed.
    """
    condition = condition.strip()
    if not condition:
        return True  # Empty condition = always pass

    # Parse: ${source.field} OPERATOR value
    pattern = r'\$\{([^}]+)\}\s*([!<>=]+|contains|exists|not_exists|in|not_in)\s*(.+)'
    match = re.match(pattern, condition, re.IGNORECASE)
    if not match:
        # Check for bare "exists" condition: ${source.field} exists
        exists_pattern = r'\$\{([^}]+)\}\s*(exists|not_exists)'
        match = re.match(exists_pattern, condition, re.IGNORECASE)
        if match:
            source_path = match.group(1)
            operator = match.group(2).lower()
            resolved = _resolve_path(source_path, task_outputs, input_data)
            if operator == "exists":
                return resolved is not None
            else:  # not_exists
                return resolved is None

        raise ConditionSyntaxError(
            f"Cannot parse condition: '{condition}'. "
            f"Expected format: ${{task_id.field}} OPERATOR value"
        )

    source_path = match.group(1).strip()
    operator = match.group(2).strip().lower()
    raw_value = match.group(3).strip()

    # Resolve the source value from task outputs
    source_value = _resolve_path(source_path, task_outputs, input_data)

    # Normalize both sides
    left_val = _normalize_value(source_value)
    right_val = _normalize_value(raw_value)

    # Evaluate
    return _apply_operator(left_val, operator, right_val)


def _resolve_path(
    path: str,
    task_outputs: dict[str, Any],
    input_data: dict[str, Any] | None = None,
) -> Any:
    """Resolve a dot-separated path to a value.

    Supports:
      task_id.field.subfield  —  look up in task outputs
      goal.field              —  look up in workflow input data

    Returns None if any part of the path doesn't exist.
    """
    parts = path.split(".", 1)
    source_id = parts[0]

    if source_id == "goal":
        source = input_data or {}
        rest = parts[1] if len(parts) > 1 else ""
    else:
        source = task_outputs.get(source_id, {})
        rest = parts[1] if len(parts) > 1 else ""

    if not source:
        return None

    if not rest:
        return source

    # Navigate nested fields
    current = source
    for key in rest.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, (list, tuple)):
            try:
                idx = int(key)
                current = current[idx] if 0 <= idx < len(current) else None
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None

    return current


def _apply_operator(left: Any, operator: str, right: Any) -> bool:
    """Apply a comparison operator to two normalized values.

    Both values have been normalized by _normalize_value so types
    are coherent (both int, both float, both str, etc.).
    """
    try:
        if operator in (">", "gt"):
            return (left is not None) and (left > right)
        elif operator in ("<", "lt"):
            return (left is not None) and (left < right)
        elif operator in (">=", "gte"):
            return (left is not None) and (left >= right)
        elif operator in ("<=", "lte"):
            return (left is not None) and (left <= right)
        elif operator in ("==", "=", "eq"):
            return left == right
        elif operator in ("!=", "neq"):
            return left != right
        elif operator == "contains":
            if isinstance(left, str):
                return str(right).lower() in left
            elif isinstance(left, (list, tuple)):
                return right in left
            return False
        elif operator == "in":
            if isinstance(right, (list, tuple)):
                return left in right
            # right can be a comma-separated string list
            if isinstance(right, str):
                items = [item.strip().strip('"').strip("'") for item in right.split(",")]
                return left in items
            return left == right
        elif operator == "not_in":
            return not _apply_operator(left, "in", right)
        elif operator == "exists":
            return left is not None
        elif operator == "not_exists":
            return left is None
        else:
            raise ConditionSyntaxError(f"Unknown operator: '{operator}'")
    except (TypeError, ValueError):
        return False
