"""Intent OS — Agent Hook Tracer: records LLM API calls to Event Store.

Detects the source AI agent (Claude Code, Cursor, Copilot, etc.)
from HTTP headers and creates structured ``LlmCall`` events
(``EventType.LLM_CALL`` — distinct from ``CapabilityInvoked`` which
tracks Manifest-based executions).

Each captured call records provider, model, token usage, cost,
latency, and source agent identity.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.event_store import EventStore, Event
from core.models import EventType


# ── Agent Detection ──

_AGENT_SIGNATURES: list[tuple[str, str, str]] = [
    # (header_name, header_value_substring, agent_name)
    ("user-agent", "claude-code", "claude-code"),
    ("user-agent", "ClaudeCode", "claude-code"),
    ("user-agent", "Cursor", "cursor"),
    ("user-agent", "cursor", "cursor"),
    ("user-agent", "GitHubCopilot", "github-copilot"),
    ("user-agent", "Copilot", "github-copilot"),
    ("user-agent", "openai-python", "openai-sdk"),
    ("user-agent", "OpenAI", "openai-sdk"),
    ("user-agent", "python-requests", "python-sdk"),
    ("user-agent", "Python", "python-sdk"),
    ("user-agent", "o1", "custom-agent"),
    ("x-request-id", "", "custom-agent"),
]


def detect_agent(headers: dict[str, str]) -> str:
    """Try to identify the AI agent from request headers.

    Returns a short string like ``"claude-code"``, ``"cursor"``,
    ``"github-copilot"``, or ``"unknown"``.
    """
    headers_lower = {k.lower(): v for k, v in headers.items()}
    for hdr_name, hdr_value, agent_name in _AGENT_SIGNATURES:
        val = headers_lower.get(hdr_name, "")
        if hdr_value and hdr_value.lower() in val.lower():
            return agent_name
        if not hdr_value and val:
            return agent_name
    return "unknown"


# ── Cost Lookup (delegated to core.pricing) ──

from core.pricing import estimate_cost, get_price, load_pricing  # noqa: E402


# ── Tracer ──


class AgentTracer:
    """Records LLM API calls (OpenAI / Anthropic) to the Intent OS Event Store.

    Each API call is recorded as an ``LlmCall`` event with
    provider, model, tokens, cost, latency, and source agent info.
    This is distinct from ``CapabilityInvoked``, which tracks
    Manifest-based capability executions.
    """

    def __init__(self, store: EventStore | None = None) -> None:
        if store is None:
            store_dir = Path.home() / ".intent-os"
            store_dir.mkdir(parents=True, exist_ok=True)
            store = EventStore(str(store_dir / "events.db"))
        self._store = store
        self._trace_id: str | None = None

    @property
    def trace_id(self) -> str:
        if self._trace_id is None:
            self._trace_id = f"proxy-{uuid.uuid4().hex[:12]}"
        return self._trace_id

    def trace_call(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        status: str,
        source_agent: str,
        endpoint: str = "",
        error_message: str | None = None,
        agent_id: str | None = None,
        context_id: str | None = None,
    ) -> str:
        """Record one LLM API call as an Event Store event.

        Args:
            agent_id: Optional registered agent ID to associate with this call.
            context_id: Optional execution context ID to associate with this call.

        Returns the trace_id for later inspection.
        """
        total_tokens = input_tokens + output_tokens
        cost = estimate_cost(model, input_tokens, output_tokens)

        # Update agent's last_seen_at if agent_id is provided
        if agent_id:
            try:
                from core.agent_store import AgentStore
                store = AgentStore()
                store.record_execution(agent_id)
            except Exception:
                pass

        event = Event(
            event_id=str(uuid.uuid4()),
            trace_id=self.trace_id,
            event_type=EventType.LLM_CALL,
            timestamp=datetime.now(timezone.utc),
            source="proxy",
            sequence=0,
            capability=f"llm.{provider}.{model}",
        )
        event.payload = {
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_usd": round(cost, 6),
            "latency_ms": round(latency_ms, 2),
            "status": status,
            "source_agent": source_agent,
            "endpoint": endpoint,
        }
        if agent_id:
            event.payload["agent_id"] = agent_id
        if context_id:
            event.payload["context_id"] = context_id
        if error_message:
            event.payload["error"] = error_message

        event.metrics = {
            "latency_ms": round(latency_ms, 2),
            "token_count": {"input": input_tokens, "output": output_tokens, "total": total_tokens},
            "cost_usd": round(cost, 6),
        }

        self._store.save_event(event)
        return self.trace_id



