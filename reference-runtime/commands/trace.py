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
from core.experience_store import ExperienceStore
from core.cost_intelligence import CostIntelligence

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
    "LlmCall": "> MODEL ",
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
            print("    intent-os run translate -p text=hello -p target_lang=zh")
            print()
            print("  Or try the demo:")
            print("    intent-os demo --auto")
            print()
            print("  Or start the proxy to record your own agent:")
            print("    intent-os proxy start")
            print("    export OPENAI_BASE_URL=http://localhost:8377")
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


def _print_intelligence(data: dict[str, Any], store: Any = None) -> None:
    """Print deep execution intelligence after the timeline.

    Adds bottleneck detection, efficiency scoring, comparative context,
    replay readiness, and related experiences.
    """
    trace_id = data["trace_id"]
    events = data["events"]
    record = data["record"]

    print("  " + "=" * 48)
    print("    Execution Intelligence")
    print("  " + "=" * 48)
    print()

    # ── 1. BOTTLENECK DETECTION ──────────────────────────────────
    _print_bottleneck(events)

    # ── 2. EFFICIENCY SCORE ─────────────────────────────────────
    _print_efficiency(events, record)

    # ── 3. COMPARATIVE CONTEXT ──────────────────────────────────
    if store and record:
        _print_comparative(store, record, trace_id)

    # ── 4. REPLAY READINESS ─────────────────────────────────────
    _print_replay_readiness(record, events)

    # ── 5. RELATED EXPERIENCES ──────────────────────────────────
    _print_related_experiences(record, events)
    print()


# ── Intelligence sub-functions ───────────────────────────────────────

def _parse_event_ts(evt: dict[str, Any]) -> float | None:
    """Parse the timestamp from an event dict, returning seconds since epoch or None."""
    ts = evt.get("timestamp", "")
    if not ts:
        return None
    import datetime as _dt
    try:
        # Handle both 'T' separated and space-separated timestamps
        if "T" in str(ts):
            if str(ts).endswith("Z"):
                ts = str(ts)[:-1] + "+00:00"
            dt = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        else:
            dt = _dt.datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _print_bottleneck(events: list[dict[str, Any]]) -> None:
    """Detect and print the execution bottleneck."""
    if len(events) < 2:
        return

    max_gap = 0.0
    max_gap_idx = 0
    gaps: list[tuple[int, float]] = []

    for i in range(1, len(events)):
        t1 = _parse_event_ts(events[i - 1])
        t2 = _parse_event_ts(events[i])
        if t1 is not None and t2 is not None:
            gap = t2 - t1
            gaps.append((i, gap))
            if gap > max_gap:
                max_gap = gap
                max_gap_idx = i

    if max_gap <= 0:
        print("  Bottleneck:  (all events within the same second -- no gap detected)")
        print()
        return

    # Identify what happened at the bottleneck
    prev_evt = events[max_gap_idx - 1] if max_gap_idx > 0 else {}
    next_evt = events[max_gap_idx] if max_gap_idx < len(events) else {}

    prev_type = prev_evt.get("event_type", "?")
    next_type = next_evt.get("event_type", "?")
    prev_cap = prev_evt.get("capability", "") or prev_evt.get("source", "?")
    next_cap = next_evt.get("capability", "") or next_evt.get("source", "?")

    # Check if it's a model call
    is_model = next_type == "LlmCall"
    note = ""
    if is_model:
        raw = next_evt.get("payload", "{}")
        if isinstance(raw, str):
            import json as _json
            try:
                p = _json.loads(raw)
            except (_json.JSONDecodeError, TypeError):
                p = {}
        else:
            p = raw
        if isinstance(p, dict):
            tokens = p.get("total_tokens") or p.get("token_count", 0)
            if tokens:
                note = f" ({tokens} tokens)"

    # Check if it's a tool call
    is_tool = next_type == "CapabilityInvoked"

    detail = ""
    if is_model:
        detail = f" -- Model call to {next_cap}{note}"
    elif is_tool:
        detail = f" -- Tool invocation: {next_cap}"
    elif prev_type == "LlmCall" and is_tool:
        detail = f" -- After model call, next tool: {next_cap}"

    print(f"  Bottleneck:  Step {max_gap_idx} ({max_gap:.1f}s between {prev_type} and {next_type}){detail}")

    # If it's > 30s, flag it
    if max_gap > 30:
        print(f"               [!!] This gap is unusually large. Consider:")
        if is_model:
            print(f"                    - Using a faster model or reducing prompt size")
            print(f"                    - Streaming responses to reduce perceived latency")
        else:
            print(f"                    - Checking if the tool has network/IO delays")
            print(f"                    - Adding a timeout or caching results")
    print()


def _print_efficiency(events: list[dict[str, Any]], record: dict[str, Any] | None) -> None:
    """Calculate and print efficiency metrics."""
    total = len(events)
    useful = sum(
        1 for e in events
        if e.get("event_type") in ("CapabilityInvoked", "TaskCompleted")
    )
    efficiency_pct = (useful / total * 100) if total > 0 else 0

    # Output tokens per dollar
    tokens = (record.get("total_tokens", 0) or 0) if record else 0
    cost = (record.get("total_cost_usd", 0.0) or 0.0) if record else 0.0
    tok_per_dollar = (tokens / cost) if cost > 0 else 0

    # Efficiency bar (20 chars)
    filled = int(efficiency_pct / 5)  # 5% per block
    bar = "[EFFICIENCY] [" + (chr(0x2588) * filled).ljust(20) + f"] {efficiency_pct:.0f}%"

    print(f"  {bar}")
    print(f"               {useful}/{total} useful events (CapabilityInvoked + TaskCompleted)")
    if tok_per_dollar > 0:
        print(f"               {tok_per_dollar:,.0f} output tokens per dollar of cost")
    elif cost == 0 and tokens > 0:
        print(f"               {tokens:,} tokens -- cost was $0.00 (free tier / local model)")
    print()


def _print_comparative(store: Any, record: dict[str, Any], trace_id: str) -> None:
    """Compare this execution against the average for the same manifest."""
    manifest = record.get("manifest_name", "")
    if not manifest:
        return

    siblings = store.query_records(manifest_name=manifest, limit=100)
    # Filter out self
    others = [s for s in siblings if s.get("trace_id") != trace_id]

    if len(others) < 1:
        print("  Comparative: (first run for this capability -- no baseline yet)")
        print()
        return

    # Compute averages
    avg_lat = sum(s.get("total_latency_ms", 0) or 0 for s in others) / len(others)
    avg_cost = sum(s.get("total_cost_usd", 0) or 0 for s in others) / len(others)

    this_lat = record.get("total_latency_ms", 0) or 0
    this_cost = record.get("total_cost_usd", 0.0) or 0.0

    lat_diff_pct = ((this_lat - avg_lat) / avg_lat * 100) if avg_lat > 0 else 0
    cost_diff_pct = ((this_cost - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0

    faster_slower = "faster" if lat_diff_pct < 0 else "slower"
    more_less = "less" if cost_diff_pct < 0 else "more"

    print(f"  Comparative: ({len(others)} previous runs of '{manifest}')")
    print(f"               This execution was {abs(lat_diff_pct):.0f}% {faster_slower} than your average")
    print(f"               (avg: {avg_lat:,.0f}ms, this: {this_lat:,.0f}ms)")
    print(f"               This execution cost {abs(cost_diff_pct):.0f}% {more_less} than average")
    print(f"               (avg: ${avg_cost:.4f}, this: ${this_cost:.4f})")
    print()


def _print_replay_readiness(record: dict[str, Any] | None, events: list[dict[str, Any]]) -> None:
    """Check and report replay readiness."""
    if not record:
        print("  Replay:      (no execution record)")
        print()
        return

    has_input = record.get("input") is not None
    has_output = record.get("output") is not None
    has_events = len(events) > 0

    missing: list[str] = []
    if not has_input:
        missing.append("input")
    if not has_output:
        missing.append("output")
    if not has_events:
        missing.append("events")

    trace_id = record.get("trace_id", "")[:12]

    if not missing:
        print(f"  Replay:      This execution is replayable.")
        print(f"               Run: intent-os replay {trace_id}")
    else:
        print(f"  Replay:      Not replayable -- missing: {', '.join(missing)}")
        print(f"               Ensure input, output, and event data are captured.")
    print()


def _print_related_experiences(record: dict[str, Any] | None, events: list[dict[str, Any]]) -> None:
    """Query the Experience Store for related experiences."""
    if not record:
        return

    # Collect relevant identifiers to query with
    agent_id = record.get("agent_id", "")
    manifest = record.get("manifest_name", "")
    capabilities: set[str] = set()
    for evt in events:
        cap = evt.get("capability", "")
        if cap:
            capabilities.add(cap)

    try:
        exp_store = ExperienceStore()
    except Exception:
        return  # Experience DB not available -- silently skip

    experiences: list[dict[str, Any]] = []

    # Query by agent_id first
    if agent_id:
        experiences = exp_store.list(agent_id=agent_id, limit=10)

    # If nothing by agent, query by task using manifest name
    if not experiences and manifest:
        experiences = exp_store.query_by_task(goal=manifest, limit=5)

    # Also try per-capability queries
    if not experiences and capabilities:
        for cap in list(capabilities)[:3]:
            results = exp_store.query_by_task(goal=cap, limit=3)
            for r in results:
                if r not in experiences:
                    experiences.append(r)
            if len(experiences) >= 3:
                break

    if not experiences:
        return

    # Show up to 3 most relevant
    experiences = experiences[:3]
    print(f"  Related lessons from past executions:")
    for exp in experiences:
        etype = exp.get("type", "?")
        rec = exp.get("recommendation", "")
        conf = exp.get("confidence", 0)
        obs = exp.get("observation", "")[:80]
        if rec:
            print(f"    [{etype}] {rec}")
        elif obs:
            print(f"    [{etype}] {obs}")
        if conf > 0:
            print(f"              confidence: {conf:.0%}")
    print()


def _print_terminal(data: dict[str, Any], store: Any = None) -> None:
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

        # Check events for agent identity (source_agent or registered agent_id)
        proxy_agent = None
        registered_agent_id = None
        for evt in events:
            raw_payload = evt.get("payload", "{}")
            if isinstance(raw_payload, str):
                import json as _json
                try:
                    p = _json.loads(raw_payload)
                except (_json.JSONDecodeError, TypeError):
                    p = {}
            else:
                p = raw_payload
            if isinstance(p, dict):
                if not proxy_agent:
                    proxy_agent = p.get("source_agent")
                if not registered_agent_id:
                    registered_agent_id = p.get("agent_id")
            if proxy_agent and registered_agent_id:
                break

        print(f"  {icon}  Goal:        {name}")
        if registered_agent_id:
            # Look up the registered agent name
            agent_name = registered_agent_id
            try:
                from core.agent_store import AgentStore
                agent = AgentStore().get(registered_agent_id)
                if agent:
                    agent_name = agent.name
            except Exception:
                pass
            print(f"     Agent:      {agent_name}")
            print(f"     Agent ID:   {registered_agent_id}")
        elif proxy_agent:
            print(f"     Agent:      {proxy_agent}")
        print(f"     Execution:  exec_{trace_id[:12]}")
        print(f"     Runtime:    {runtime} ({adapter})")
        print(f"     Duration:   {latency:.0f}ms")
        print(f"     Cost:       ${cost:.4f}")
        print(f"     Tokens:     {tokens}")
        if error:
            print(f"     Error:      {error}")
        print(f"     Trace ID:   {trace_id}")
    print()

    # Timeline
    timeline = _format_timeline(events)
    if timeline:
        print(f"  -- Timeline ({len(events)} events) --")
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

    # ── Deep Execution Intelligence (requires >= 3 events) ──
    if events and len(events) >= 3:
        _print_intelligence(data, store)


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

    _print_terminal(data, store)
