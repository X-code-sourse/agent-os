"""Intent OS CLI — cost command: API spending breakdown.

Shows how much your AI agents are spending on API calls, broken down
by agent, model, and time period.

    intent-os cost              # Total spending overview
    intent-os cost --by agent   # Per-agent breakdown
    intent-os cost --by model   # Per-model breakdown
    intent-os cost --days 7     # Last 7 days only
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from commands.helpers import get_event_store

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if f == f else default  # NaN check
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _parse_payload(payload_str: str) -> dict[str, Any]:
    """Parse a JSON payload string from the Event Store."""
    import json
    if not payload_str:
        return {}
    try:
        payload = json.loads(payload_str)
        return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def cmd_cost(args: Any) -> None:
    """Show API cost breakdown."""
    store = get_event_store()
    days = getattr(args, "days", 30)
    by = getattr(args, "by", None)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    all_ids = store.get_all_trace_ids()

    if not all_ids:
        print("  No execution data found.")
        print()
        print("  To begin tracking costs:")
        print()
        print("    1. Start the proxy to intercept API calls:")
        print("       intent-os proxy start")
        print()
        print("    2. Point your agent to the proxy:")
        print("       export OPENAI_BASE_URL=http://localhost:8377")
        print("       export ANTHROPIC_BASE_URL=http://localhost:8377")
        print()
        print("    3. Use your AI agent — costs will be tracked automatically.")
        print()
        return

    # Aggregate from execution records + proxy events
    records_aggregated = 0
    agent_costs: dict[str, dict[str, Any]] = {}
    model_costs: dict[str, dict[str, Any]] = {}
    daily_costs: dict[str, float] = {}
    total_cost = 0.0
    total_tokens = 0
    total_runs = 0

    for trace_id in all_ids[:500]:  # Limit to 500 traces for performance
        record = store.get_record(trace_id)
        events = store.get_events_by_trace(trace_id)

        # Track this record's contribution
        record_cost = 0.0
        record_tokens = 0

        # Check execution record fields
        if record:
            record_cost = _safe_float(record.get("total_cost_usd", 0))
            record_tokens = _safe_int(record.get("total_tokens", 0))
            created = record.get("created_at", "")
            if created:
                day = created[:10]
                daily_costs[day] = daily_costs.get(day, 0) + record_cost
            total_cost += record_cost
            total_tokens += record_tokens
            total_runs += 1
            records_aggregated += 1

        # Check proxy-traced events (CapabilityInvoked from proxy tracer)
        for evt in events:
            etype = evt.get("event_type", "")
            capability = evt.get("capability", "")

            if etype in ("LlmCall", "CapabilityInvoked") and capability and capability.startswith("llm."):
                payload = _parse_payload(evt.get("payload", "{}"))
                source_agent = payload.get("source_agent", "unknown")
                model = payload.get("model", capability.replace("llm.", "", 1))
                cost = _safe_float(payload.get("cost_usd", 0))
                tokens = _safe_int(payload.get("total_tokens", 0))
                ts = evt.get("timestamp", "")
                day = ts[:10] if ts else ""

                # Track by agent
                if source_agent not in agent_costs:
                    agent_costs[source_agent] = {"runs": 0, "cost": 0.0, "tokens": 0}
                agent_costs[source_agent]["runs"] += 1
                agent_costs[source_agent]["cost"] += cost
                agent_costs[source_agent]["tokens"] += tokens

                # Track by model
                if model not in model_costs:
                    model_costs[model] = {"runs": 0, "cost": 0.0, "tokens": 0}
                model_costs[model]["runs"] += 1
                model_costs[model]["cost"] += cost
                model_costs[model]["tokens"] += tokens

                if day:
                    daily_costs[day] = daily_costs.get(day, 0) + cost
                total_cost += cost
                total_tokens += tokens
                total_runs += 1

    if total_runs == 0:
        # Fallback: aggregate from execution records directly
        print("  No detailed cost data from proxy events.")
        print("  Start the proxy to track per-agent and per-model costs:")
        print()
        print("    intent-os proxy start")
        print("    export OPENAI_BASE_URL=http://localhost:8377")
        print()
        print(f"  Found {records_aggregated} execution records with")
        print(f"  total cost: ${total_cost:.4f}")
        print()
        return

    # Print report
    print()
    print("  ================================================")
    print("    Cost Report")
    print("  ================================================")
    print()
    print(f"  Period:       Last {days} days")
    print(f"  Total runs:   {total_runs}")
    print(f"  Total cost:   ${total_cost:.4f}")
    print(f"  Total tokens: {total_tokens:,}")
    if total_runs > 0:
        print(f"  Avg cost/run: ${total_cost / total_runs:.4f}")
    print()

    if by == "agent" and agent_costs:
        print(f"  -- By Agent --")
        print(f"  {'Agent':<25} {'Runs':<8} {'Cost':<12} {'Tokens':<12}")
        print(f"  {'-'*57}")
        for agent, data in sorted(agent_costs.items(), key=lambda x: x[1]["cost"], reverse=True):
            print(f"  {agent:<25} {data['runs']:<8} ${data['cost']:<9.4f} {data['tokens']:<12,}")
        print()

    elif by == "model" and model_costs:
        print(f"  -- By Model --")
        print(f"  {'Model':<30} {'Runs':<8} {'Cost':<12} {'Tokens':<12}")
        print(f"  {'-'*62}")
        for model, data in sorted(model_costs.items(), key=lambda x: x[1]["cost"], reverse=True):
            print(f"  {model:<30} {data['runs']:<8} ${data['cost']:<9.4f} {data['tokens']:<12,}")
        print()

    else:
        # Default: show agent breakdown if available, otherwise model
        if agent_costs:
            print(f"  -- By Agent --")
            print(f"  {'Agent':<25} {'Runs':<8} {'Cost':<12} {'Tokens':<12}")
            print(f"  {'-'*57}")
            for agent, data in sorted(agent_costs.items(), key=lambda x: x[1]["cost"], reverse=True):
                print(f"  {agent:<25} {data['runs']:<8} ${data['cost']:<9.4f} {data['tokens']:<12,}")
            print()

        if model_costs:
            print(f"  -- By Model --")
            print(f"  {'Model':<30} {'Runs':<8} {'Cost':<12} {'Tokens':<12}")
            print(f"  {'-'*62}")
            for model, data in sorted(model_costs.items(), key=lambda x: x[1]["cost"], reverse=True):
                print(f"  {model:<30} {data['runs']:<8} ${data['cost']:<9.4f} {data['tokens']:<12,}")
            print()

    # Daily trend (last 7 days)
    if daily_costs:
        sorted_days = sorted(daily_costs.items(), key=lambda x: x[0])
        print(f"  -- Daily Trend (last 7 days) --")
        print(f"  {'Date':<14} {'Cost':<12}")
        print(f"  {'-'*26}")
        for day, cost in sorted_days[-7:]:
            print(f"  {day:<14} ${cost:<9.4f}")
        print()
