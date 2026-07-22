"""Intent OS — Tool Call Guard: optional proxy security inspection layer.

When enabled on the proxy (--guard), this module intercepts LLM responses,
parses function/tool calls, evaluates them against SecurityManager policies,
and flags or blocks dangerous operations.

This is an OPTIONAL layer — the base proxy works without it.

Design:
- Parses tool_calls from OpenAI response format
- Classifies tool risk by name/operation type
- Evaluates against loaded security policies
- Does NOT modify the forwarding path — only adds inspection
"""
from __future__ import annotations

import json
from typing import Any

from core.security import SecurityManager, SecurityDecision, SecurityRisk, PolicyStore


# ── Tool Risk Classification ──

_DANGEROUS_TOOL_PATTERNS: dict[str, dict[str, Any]] = {
    # Filesystem
    "write_file": {"risk": "high", "category": "filesystem"},
    "edit_file": {"risk": "medium", "category": "filesystem"},
    "delete_file": {"risk": "critical", "category": "filesystem"},
    "remove_file": {"risk": "critical", "category": "filesystem"},
    "create_file": {"risk": "medium", "category": "filesystem"},
    "rename_file": {"risk": "medium", "category": "filesystem"},
    "chmod": {"risk": "high", "category": "filesystem"},
    # Shell execution
    "bash": {"risk": "high", "category": "shell"},
    "execute_command": {"risk": "high", "category": "shell"},
    "run_shell": {"risk": "high", "category": "shell"},
    "exec": {"risk": "critical", "category": "shell"},
    "subprocess": {"risk": "critical", "category": "shell"},
    # Network / Data
    "database_query": {"risk": "high", "category": "data"},
    "sql": {"risk": "high", "category": "data"},
    "delete_database": {"risk": "critical", "category": "data"},
    "drop_table": {"risk": "critical", "category": "data"},
    "api_call": {"risk": "medium", "category": "network"},
    "http_request": {"risk": "medium", "category": "network"},
    "fetch_url": {"risk": "medium", "category": "network"},
    # Deployment
    "deploy": {"risk": "critical", "category": "deployment"},
    "kubernetes": {"risk": "critical", "category": "deployment"},
    "docker": {"risk": "high", "category": "deployment"},
    "terraform": {"risk": "critical", "category": "deployment"},
    # Identity / Auth
    "add_ssh_key": {"risk": "critical", "category": "auth"},
    "create_user": {"risk": "high", "category": "auth"},
    "delete_user": {"risk": "critical", "category": "auth"},
    "change_permissions": {"risk": "high", "category": "auth"},
    "sudo": {"risk": "critical", "category": "auth"},
    # Sensitive data
    "read_database": {"risk": "high", "category": "data"},
    "query_database": {"risk": "high", "category": "data"},
    "read_file": {"risk": "low", "category": "filesystem"},
    "list_directory": {"risk": "low", "category": "filesystem"},
}

_DEFAULT_RISK = {"risk": "medium", "category": "unknown"}

# ── Sensitive Data Patterns ──

_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    ("API key", r"sk-[a-zA-Z0-9\-]{20,}"),
    ("OpenAI key", r"sk-[A-Za-z0-9\-]{32,}"),
    ("Anthropic key", r"sk-ant-[a-zA-Z0-9\-]{20,}"),
    ("AWS key", r"AKIA[0-9A-Z]{16}"),
    ("GitHub token", r"gh[ps]_[a-zA-Z0-9]{36,}"),
    ("Bearer token", r"Bearer [A-Za-z0-9\-\._~\+/]{20,}"),
    ("Password env", r"(?i)password\s*[=:]\s*['\"].+['\"]"),
    ("JWT token", r"eyJ[a-zA-Z0-9\-_]+\.eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+"),
    ("Private key", r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
]


def classify_tool_risk(tool_name: str) -> dict[str, Any]:
    """Classify a tool/function name into a risk level.

    Returns dict with keys: risk, category
    """
    name_lower = tool_name.lower().strip()
    # Try exact match first
    if name_lower in _DANGEROUS_TOOL_PATTERNS:
        return dict(_DANGEROUS_TOOL_PATTERNS[name_lower])

    # Try partial match for compound names
    for pattern, info in _DANGEROUS_TOOL_PATTERNS.items():
        if pattern in name_lower or name_lower in pattern:
            return dict(info)

    return dict(_DEFAULT_RISK)


def check_sensitive_data(text: str) -> list[dict[str, Any]]:
    """Scan text for potential sensitive data exposure.

    Returns list of {type, match_preview} dicts.
    """
    import re
    findings: list[dict[str, Any]] = []
    for name, pattern in _SENSITIVE_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            for m in matches[:3]:
                preview = m[:20] + "..." if len(m) > 20 else m
                findings.append({"type": name, "match_preview": preview})
    return findings


def parse_openai_tool_calls(response_body: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract tool/function calls from an OpenAI response."""
    calls: list[dict[str, Any]] = []
    choices = response_body.get("choices", [])
    for choice in choices:
        msg = choice.get("message", {})
        tool_calls = msg.get("tool_calls", []) or msg.get("function_call", [])
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                func = tc.get("function", tc)
                name = func.get("name", "")
                args_raw = func.get("arguments", "{}")
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except (json.JSONDecodeError, TypeError):
                    args = {}
                calls.append({"name": name, "arguments": args, "type": "tool_call"})
        elif isinstance(tool_calls, dict):
            # Single function_call
            name = tool_calls.get("name", "")
            args_raw = tool_calls.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except (json.JSONDecodeError, TypeError):
                args = {}
            calls.append({"name": name, "arguments": args, "type": "function_call"})
    return calls


def parse_anthropic_tool_calls(response_body: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract tool use blocks from an Anthropic response."""
    calls: list[dict[str, Any]] = []
    content = response_body.get("content", [])
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            calls.append({
                "name": block.get("name", ""),
                "arguments": block.get("input", {}),
                "type": "tool_use",
            })
    return calls


class ToolCallGuard:
    """Optional security guard for proxy traffic.

    Inspects LLM responses for tool calls, classifies their risk,
    and evaluates against SecurityManager policies.
    """

    def __init__(
        self,
        policy_store_path: str = "intent_os_policies.db",
        event_store=None,
    ) -> None:
        self._policy_store = PolicyStore(policy_store_path)
        self._manager = SecurityManager(
            policy_store=self._policy_store,
            event_store=event_store,
        )

    def inspect_openai_response(
        self,
        response_body: dict[str, Any],
        trace_id: str = "",
    ) -> list[dict[str, Any]]:
        """Inspect an OpenAI response for tool call safety.

        Returns a list of inspection results, each with:
          name, risk, decision, rationale
        """
        tool_calls = parse_openai_tool_calls(response_body)
        return self._inspect_tool_calls(tool_calls, trace_id)

    def inspect_anthropic_response(
        self,
        response_body: dict[str, Any],
        trace_id: str = "",
    ) -> list[dict[str, Any]]:
        """Inspect an Anthropic response for tool call safety."""
        tool_calls = parse_anthropic_tool_calls(response_body)
        return self._inspect_tool_calls(tool_calls, trace_id)

    def _inspect_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        trace_id: str = "",
    ) -> list[dict[str, Any]]:
        """Inspect parsed tool calls against security policies."""
        results: list[dict[str, Any]] = []

        for tc in tool_calls:
            tool_name = tc.get("name", "unknown")
            risk_info = classify_tool_risk(tool_name)
            risk_str = risk_info.get("risk", "medium")

            result = self._manager.evaluate(
                capability_name=f"tool.{tool_name}",
                risk_level=risk_str,
            )

            # Also check sensitive data in arguments
            args_str = json.dumps(tc.get("arguments", {}))
            sensitive = check_sensitive_data(args_str)

            entry = {
                "tool": tool_name,
                "risk": risk_str,
                "category": risk_info.get("category", "unknown"),
                "decision": result.decision.value,
                "rationale": result.rationale,
                "tool_call_type": tc.get("type", "unknown"),
                "sensitive_data_found": sensitive if sensitive else None,
            }
            results.append(entry)

        return results
