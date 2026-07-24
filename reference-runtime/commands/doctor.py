"""Intent OS — doctor command: AI Agent Health Report.

The first thing a user runs when something feels wrong.
No understanding of traces, events, or manifests required.

    intent-os doctor

Shows whether the last agent run succeeded or failed,
what went wrong, and how to fix it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from commands.helpers import get_event_store, setup_executor, find_builtin_manifest

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _get_agent_status(record: dict[str, Any] | None) -> str:
    """Classify the agent's last run as healthy, failed, or unknown."""
    if record is None:
        return "unknown"
    status = record.get("status", "")
    if status == "success":
        return "healthy"
    elif status == "failure":
        return "failed"
    elif status == "partial":
        return "partial"
    return "unknown"


def _summarize_failure(events: list[dict[str, Any]], record: dict[str, Any] | None) -> dict[str, Any]:
    """Analyze failure: find the failed step and reason."""
    result = {
        "failed_events": [],
        "error_message": None,
        "suggestion": None,
        "failed_at": None,
    }

    if record and record.get("error"):
        result["error_message"] = record["error"]

    # Scan events for failures
    for evt in events:
        etype = evt.get("event_type", "")
        if etype in ("TaskFailed", "WorkflowFailed"):
            cap = evt.get("capability", "")
            source = evt.get("source", "")
            result["failed_events"].append(f"{cap} ({source})")
            result["failed_at"] = cap or source or "unknown"

            # Extract error from payload (stored as JSON string in Event Store)
            raw_payload = evt.get("payload", "{}")
            if isinstance(raw_payload, str):
                import json
                try:
                    payload = json.loads(raw_payload)
                except json.JSONDecodeError:
                    payload = {}
            else:
                payload = raw_payload
            if isinstance(payload, dict) and payload.get("error_message"):
                result["error_message"] = payload["error_message"]

    # Generate suggestion from error patterns
    err = (result["error_message"] or "").lower()
    if "timeout" in err or "timed out" in err:
        result["suggestion"] = "Increase timeout duration or retry with a simpler request."
    elif "rate limit" in err or "429" in err:
        result["suggestion"] = "You're being rate-limited. Slow down requests or check your API plan."
    elif "authentication" in err or "api key" in err or "unauthorized" in err:
        result["suggestion"] = "Check that your API key is set and valid."
    elif "context" in err and ("length" in err or "token" in err):
        result["suggestion"] = "The input was too long. Try a shorter prompt or use a model with larger context."
    elif "connect" in err or "connection" in err:
        result["suggestion"] = "Could not reach the API. Check your network or if the service is down."
    elif "permission" in err or "denied" in err or "forbidden" in err:
        result["suggestion"] = "Permission denied. Check file permissions or access rights."
    elif "not found" in err or "no such" in err:
        result["suggestion"] = "A required file or resource was not found. Check the path exists."
    elif "server error" in err or "500" in err or "502" in err or "503" in err:
        result["suggestion"] = "The API server returned an error. This is usually temporary — try again."
    else:
        result["suggestion"] = "Check the full trace for details."

    return result


def _suggest_next_step(record: dict[str, Any] | None) -> str:
    """Suggest what the user should do next."""
    if record is None:
        return "Run a capability first:  intent-os run translate -p text=hello -p target_lang=zh"
    return "View full trace:           intent-os inspect latest"


def cmd_doctor(args: Any) -> None:
    """Check the health of your last AI agent execution.

    Analyzes the most recent execution record and tells you:
    - Did it succeed or fail?
    - What went wrong?
    - How to fix it?
    - How much it cost?
    """
    store = get_event_store()
    all_ids = store.get_all_trace_ids()

    if not all_ids:
        # No traces yet — guide the user through first-run setup
        print()
        print("  ================================================")
        print("    Intent OS Doctor - Health Check")
        print("  ================================================")
        print()
        print("  No agent executions found.")
        print()
        print("  Get started in 4 steps:")
        print()
        print("    1. Start the proxy:")
        print("       intent-os proxy start")
        print()
        print("    2. Set environment variables:")
        print("       export OPENAI_BASE_URL=http://localhost:8377")
        print("       export ANTHROPIC_BASE_URL=http://localhost:8377")
        print()
        print("    3. Use your AI agent normally (Claude Code, Cursor, etc.)")
        print()
        print("    4. Come back and run doctor:")
        print("       intent-os doctor")
        print()
        return

    # Get latest trace
    trace_id = all_ids[0]
    record = store.get_record(trace_id)
    events = store.get_events_by_trace(trace_id)

    status = _get_agent_status(record)

    print()
    print("  ================================================")
    print("    Intent OS Doctor - Health Check")
    print("  ================================================")
    print()

    if status == "healthy":
        name = record.get("manifest_name", "?") if record else "?"
        version = record.get("manifest_version", "?") if record else "?"
        runtime = record.get("runtime_id", "?") if record else "?"
        adapter = record.get("adapter", "?") if record else "?"
        latency = record.get("total_latency_ms", 0) if record else 0
        cost = record.get("total_cost_usd", 0.0) if record else 0.0
        tokens = record.get("total_tokens", 0) if record else 0

        print(f"  [OK]  Last Agent Run: Healthy")
        print()
        print(f"  Capability:")
        print(f"    {name}@{version}")
        print()
        print(f"  Runtime:     {runtime} ({adapter})")
        print(f"  Duration:    {latency:.0f}ms")
        print(f"  Steps:       {len(events)}")
        print(f"  Cost:        ${cost:.4f}")
        print(f"  Tokens:      {tokens}")

    elif status == "failed":
        name = record.get("manifest_name", "?") if record else "?"
        analysis = _summarize_failure(events, record)

        print(f"  [!!]  Last Agent Run: Failed")
        print()
        print(f"  Capability:  {name}")

        if analysis["failed_at"]:
            print(f"  Failed at:   {analysis['failed_at']}")

        print()
        print("  Problem:")
        print(f"    {analysis['error_message'] or 'Unknown error'}")
        print()

        if analysis["failed_events"]:
            print("  Failed events:")
            for fe in analysis["failed_events"]:
                print(f"    - {fe}")
            print()

        if analysis["suggestion"]:
            print("  Suggestion:")
            print(f"    {analysis['suggestion']}")
            print()

    elif status == "partial":
        print(f"  [..]  Last Agent Run: Partial")
        print()
        print("  Some steps succeeded, some failed.")

    else:
        print(f"  [?]   Last Agent Run: Unknown")
        print()

    # Next step suggestion
    print()
    next_step = _suggest_next_step(record)
    print(f"  {'=' * 48}")
    print(f"  {next_step}")
    print(f"  {'=' * 48}")
    print()
