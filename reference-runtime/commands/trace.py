"""Intent OS — inspect command: Agent Flight Recorder.

Shows what an AI agent did, step by step — the black box for AI agents.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

from commands.helpers import get_event_store

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── Helpers ──

_STATUS_ICON = {
    "success": "[OK]",
    "failure": "[!!]",
    "partial": "[..]",
    "running": "[..]",
    "pending": "[--]",
}

_MARKER_MAP = {
    "TaskStarted": "> START",
    "CapabilityInvoked": "> INVOKE",
    "TaskCompleted": "OK DONE ",
    "TaskFailed": "!! FAIL ",
    "TaskRetried": ".. RETRY",
    "TaskSkipped": "-- SKIP ",
    "TaskCancelled": "xx CANCEL",
    "WorkflowStarted": "> START",
    "WorkflowCompleted": "OK DONE ",
    "WorkflowFailed": "!! FAIL ",
    "CostAccumulated": "$$ COST ",
}


def _resolve_trace_id(store: Any, trace_id: str) -> str:
    """Resolve special identifiers ('latest') to a real trace ID."""
    if trace_id == "latest":
        all_ids = store.get_all_trace_ids()
        if not all_ids:
            print("No traces found. Run a capability first:")
            print()
            print("    pip install intent-os")
            print("    pip install 'intent-os[all]'")
            print("    export OPENAI_API_KEY=sk-...")
            print("    intent-os run translate -p text=hello -p target_lang=zh")
            print()
            print("  Or try the demo:")
            print("    intent-os demo --auto")
            print()
            sys.exit(0)
        return all_ids[0]
    return trace_id


def _build_trace_data(store: Any, trace_id: str) -> dict[str, Any]:
    """Fetch events + record and return a structured trace dict."""
    events = store.get_events_by_trace(trace_id)
    record = store.get_record(trace_id)
    return {"trace_id": trace_id, "events": events, "record": record}


def _format_timeline(events: list[dict[str, Any]]) -> list[str]:
    """Render the event timeline as a list of formatted strings."""
    lines = []
    for evt in events:
        ts = evt.get("timestamp", "")[11:23] if evt.get("timestamp") else ""
        etype = evt.get("event_type", "")
        source = evt.get("source", "")
        cap = evt.get("capability", "")
        task = evt.get("task_id", "")

        marker = _MARKER_MAP.get(etype, f"  {etype}")

        details = f"({source})" if source else ""
        if cap:
            details += f" {cap}"
        if task and task != "capability":
            details += f" task={task}"

        payload = evt.get("payload", {})
        if isinstance(payload, dict) and payload:
            extra = []
            if payload.get("latency_ms"):
                extra.append(f"{payload['latency_ms']}ms")
            if payload.get("attempt"):
                extra.append(f"attempt {payload['attempt']}")
            if payload.get("reason"):
                extra.append(f'reason="{payload["reason"]}"')
            if extra:
                details += " — " + " ".join(extra)

        lines.append(f"  [{ts}] {marker} {details}")
    return lines


def _print_terminal(data: dict[str, Any]) -> None:
    """Render trace to terminal (default output)."""
    trace_id = data["trace_id"]
    events = data["events"]
    record = data["record"]

    print()
    print("  ================================================")
    print("    Agent Flight Recorder - Execution Trace")
    print("  ================================================")
    print()

    # Identity section
    if record:
        name = record.get("manifest_name", "?")
        version = record.get("manifest_version", "?")
        status = record.get("status", "?")
        runtime = record.get("runtime_id", "?")
        adapter = record.get("adapter", "?")
        latency = record.get("total_latency_ms", 0)
        cost = record.get("total_cost_usd", 0.0)
        tokens = record.get("total_tokens", 0)
        error = record.get("error")

        icon = _STATUS_ICON.get(status, "❓")
        print(f"  {icon}  Goal:        {name}")
        print(f"     Version:    {version}")
        print(f"     Runtime:    {runtime} ({adapter})")
        print(f"     Duration:   {latency:.0f}ms")
        print(f"     Cost:       ${cost:.4f}")
        print(f"     Tokens:     {tokens}")
        if error:
            print(f"     Error:      {error}")
    print()

    # Timeline
    timeline = _format_timeline(events)
    if timeline:
        print(f"  -- Timeline ({len(events)} events) --")
        print()
        for line in timeline:
            print(line)
        print()

    print(f"  Execution ID: exec_{trace_id[:12]}")
    print(f"  Trace ID: {trace_id}")
    print()


def _export_html(data: dict[str, Any]) -> str:
    """Render trace as a standalone HTML string for sharing."""
    trace_id = data["trace_id"]
    events = data["events"]
    record = data["record"]

    # Build data for the template
    name = "—"
    version = "—"
    status = "—"
    runtime = "—"
    adapter = "—"
    latency = 0
    cost = 0.0
    tokens = 0
    error = None

    if record:
        name = record.get("manifest_name", "—")
        version = record.get("manifest_version", "—")
        status = record.get("status", "—")
        runtime = record.get("runtime_id", "—")
        adapter = record.get("adapter", "—")
        latency = record.get("total_latency_ms", 0)
        cost = record.get("total_cost_usd", 0.0)
        tokens = record.get("total_tokens", 0)
        error = record.get("error")

    status_color = "green" if status == "success" else "red" if status == "failure" else "orange"

    # Build timeline HTML
    timeline_rows = ""
    for evt in events:
        ts = evt.get("timestamp", "")[11:23] if evt.get("timestamp") else ""
        etype = evt.get("event_type", "")
        source = evt.get("source", "")
        cap = evt.get("capability", "")
        marker_html = etype
        icon_html = _MARKER_MAP.get(etype, etype).split()[0] if _MARKER_MAP.get(etype) else "•"

        row_class = ""
        if "FAIL" in str(_MARKER_MAP.get(etype, "")):
            row_class = "class='event-error'"
        elif "DONE" in str(_MARKER_MAP.get(etype, "")):
            row_class = "class='event-success'"

        timeline_rows += f"""
        <tr {row_class}>
          <td class='time'>{ts}</td>
          <td class='icon'>{icon_html}</td>
          <td class='type'>{etype}</td>
          <td class='detail'>{source} {cap}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Agent Flight Recorder — {name}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; background: #0d1117; color: #e6edf3; }}
  h1 {{ font-size: 1.5em; border-bottom: 1px solid #30363d; padding-bottom: 12px; }}
  .summary {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin: 20px 0; }}
  .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .label {{ color: #8b949e; font-size: 0.85em; }}
  .value {{ font-size: 1.1em; font-weight: 600; }}
  .status-badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.85em; font-weight: 600; background: {status_color}; color: white; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 0.85em; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #21262d; font-size: 0.9em; }}
  .time {{ color: #8b949e; font-family: monospace; white-space: nowrap; }}
  .icon {{ font-size: 1em; width: 28px; }}
  .type {{ font-family: monospace; }}
  .detail {{ color: #8b949e; }}
  .event-error {{ background: rgba(248,81,73,0.08); }}
  .event-success {{ background: rgba(63,185,80,0.08); }}
  .footer {{ margin-top: 30px; padding-top: 16px; border-top: 1px solid #30363d; color: #8b949e; font-size: 0.8em; }}
</style>
</head>
<body>
<h1>&#x1f6f8; Agent Flight Recorder</h1>

<div class="summary">
  <div style="margin-bottom:12px;">
    <span class="status-badge">{status.upper()}</span>
    <strong style="margin-left:8px;">{name}</strong>
    <span style="color:#8b949e;font-size:0.85em;">v{version}</span>
  </div>
  <div class="summary-grid">
    <div><div class="label">Runtime</div><div class="value">{runtime}</div></div>
    <div><div class="label">Adapter</div><div class="value">{adapter}</div></div>
    <div><div class="label">Duration</div><div class="value">{int(latency)}ms</div></div>
    <div><div class="label">Cost</div><div class="value">${cost:.4f}</div></div>
    <div><div class="label">Tokens</div><div class="value">{tokens}</div></div>
    <div><div class="label">Events</div><div class="value">{len(events)}</div></div>
  </div>
  {f'<div style="margin-top:12px;color:red;">❌ {error}</div>' if error else ''}
</div>

<h2>Timeline</h2>
<table>
<thead><tr><th>Time</th><th></th><th>Event</th><th>Detail</th></tr></thead>
<tbody>
{timeline_rows}
</tbody>
</table>

<div class="footer">
  Generated by Intent OS — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
  Execution ID: exec_{trace_id[:12]}<br>
  Trace ID: {trace_id}
</div>
</body>
</html>"""
    return html


def cmd_inspect(args: Any) -> None:
    """Display or export an agent execution trace.

    Shows what an AI agent did, which models it called, what tools it
    used, how much it cost, and whether it succeeded or failed.

    Use ``latest`` to view the most recent trace, or pass a specific
    trace ID from a previous run.
    """
    store = get_event_store()
    trace_id = _resolve_trace_id(store, getattr(args, "trace_id", "latest"))
    data = _build_trace_data(store, trace_id)

    if not data["events"] and not data["record"]:
        print(f"No trace found for '{args.trace_id}'.")
        sys.exit(1)

    if getattr(args, "html", False):
        html = _export_html(data)
        filename = f"intent-os-trace-{trace_id[:12]}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Trace exported to {filename}")
        print(f"Open in browser: file://{os.path.abspath(filename)}")
        return

    _print_terminal(data)
