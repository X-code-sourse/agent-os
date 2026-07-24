"""Intent OS CLI — audit command: compliance-ready execution reports.

Generates audit reports with full execution records showing who did
what, which models were called, costs, and security events.

    intent-os audit                   # Summary of all executions
    intent-os audit report            # Full audit report (CSV)
    intent-os audit report --html     # Full audit report (HTML)
    intent-os audit report --json     # Full audit report (JSON)
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from commands.helpers import get_event_store

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_str(val: Any, default: str = "") -> str:
    if val is None:
        return default
    return str(val)


def _parse_payload(payload_str: str) -> dict[str, Any]:
    import json
    if not payload_str:
        return {}
    try:
        payload = json.loads(payload_str)
        return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def cmd_audit(args: Any) -> None:
    """Generate compliance-ready audit reports."""
    store = get_event_store()
    output_format = getattr(args, "format", "summary")
    output_path = getattr(args, "output", None)
    days = getattr(args, "days", 90)
    action = getattr(args, "audit_action", "report")

    all_ids = store.get_all_trace_ids()

    if not all_ids and action == "report":
        print("  No execution data found.")
        print()
        print("  Run capabilities or start the proxy to collect data:")
        print("    intent-os run translate -p text=hello -p target_lang=zh")
        print("    intent-os proxy start")
        print()
        return

    if action == "report" and output_format == "html":
        _generate_html_report(store, all_ids, output_path)
    elif action == "report" and output_format == "json":
        _generate_json_report(store, all_ids, output_path)
    elif action == "report":
        _generate_csv_report(store, all_ids, output_path)
    else:
        _print_summary(store, all_ids)


def _print_summary(store: Any, trace_ids: list[str]) -> None:
    """Print an audit summary."""
    print()
    print("  ================================================")
    print("    Compliance Audit Summary")
    print("  ================================================")
    print()

    if not trace_ids:
        print("  No execution records found.")
        print()
        return

    total_cost = 0.0
    total_tokens = 0
    success_count = 0
    failure_count = 0
    models_used: set[str] = set()
    agents: set[str] = set()
    security_events = 0

    for trace_id in trace_ids:
        record = store.get_record(trace_id)
        events = store.get_events_by_trace(trace_id)

        if record:
            status = record.get("status", "")
            if status == "success":
                success_count += 1
            elif status == "failure":
                failure_count += 1
            total_cost += _safe_float(record.get("total_cost_usd", 0))
            total_tokens += _safe_int(record.get("total_tokens", 0))

        for evt in events:
            etype = evt.get("event_type", "")
            capability = evt.get("capability", "")
            payload = _parse_payload(evt.get("payload", "{}"))

            if etype in ("CapabilityInvoked", "LlmCall"):
                if capability:
                    models_used.add(capability)

            if etype in ("PolicyEvaluated", "PermissionDenied", "PermissionGranted",
                         "PolicyViolation", "ReviewRequired"):
                security_events += 1

            source_agent = payload.get("source_agent", "")
            if source_agent:
                agents.add(source_agent)

    total_runs = success_count + failure_count
    print(f"  Total executions:    {total_runs}")
    print(f"    Successful:        {success_count}")
    print(f"    Failed:            {failure_count}")
    if total_runs > 0:
        print(f"    Success rate:      {success_count/total_runs:.1%}")
    print()
    print(f"  Total cost:          ${total_cost:.4f}")
    print(f"  Total tokens:        {total_tokens:,}")
    print(f"  Models used:         {len(models_used)}")
    print(f"  Agents detected:     {len(agents)}")
    print(f"  Security events:     {security_events}")
    print()

    if agents:
        print(f"  Agents:")
        for a in sorted(agents):
            print(f"    - {a}")
        print()

    if models_used:
        print(f"  Model capabilities:")
        for m in sorted(models_used)[:10]:
            print(f"    - {m}")
        print()

    print(f"  Records available:   {len(trace_ids)}")
    print(f"  For detailed report: intent-os audit report")
    print()


def _collect_execution_rows(
    store: Any, trace_ids: list[str], limit: int = 1000
) -> list[dict[str, Any]]:
    """Collect execution records into flat dicts for export."""
    rows: list[dict[str, Any]] = []
    for trace_id in trace_ids[:limit]:
        record = store.get_record(trace_id)
        events = store.get_events_by_trace(trace_id)

        if not record:
            continue

        row = {
            "trace_id": trace_id,
            "capability": f"{record.get('manifest_name','?')}@{record.get('manifest_version','?')}",
            "status": record.get("status", "?"),
            "runtime": record.get("runtime_id", "?"),
            "adapter": record.get("adapter", "?"),
            "duration_ms": record.get("total_latency_ms", 0),
            "cost_usd": record.get("total_cost_usd", 0),
            "tokens": record.get("total_tokens", 0),
            "error": record.get("error", "") or "",
            "timestamp": record.get("created_at", ""),
        }

        # Extract agent from events
        agents_seen: set[str] = set()
        models_seen: set[str] = set()
        for evt in events:
            payload = _parse_payload(evt.get("payload", "{}"))
            sa = payload.get("source_agent", "")
            if sa:
                agents_seen.add(sa)
            cap = evt.get("capability", "")
            if cap and cap.startswith("llm."):
                model = payload.get("model", cap)
                models_seen.add(str(model))

        row["agents"] = ", ".join(sorted(agents_seen)) if agents_seen else "unknown"
        row["models"] = ", ".join(sorted(models_seen)) if models_seen else record.get("manifest_name", "?")
        rows.append(row)

    return rows


def _generate_csv_report(store: Any, trace_ids: list[str], output_path: str | None) -> None:
    """Generate a CSV audit report."""
    rows = _collect_execution_rows(store, trace_ids)

    if not rows:
        print("  No execution data to export.")
        return

    fieldnames = [
        "timestamp", "trace_id", "capability", "status", "runtime",
        "adapter", "duration_ms", "cost_usd", "tokens", "error",
        "agents", "models",
    ]

    if output_path:
        fpath = output_path
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = f"intent-os-audit-{timestamp}.csv"

    with open(fpath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Audit report exported: {fpath}")
    print(f"  Records: {len(rows)}")
    print()


def _generate_json_report(store: Any, trace_ids: list[str], output_path: str | None) -> None:
    """Generate a JSON audit report."""
    rows = _collect_execution_rows(store, trace_ids)

    if not rows:
        print("  No execution data to export.")
        return

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(rows),
        "executions": rows,
    }

    if output_path:
        fpath = output_path
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = f"intent-os-audit-{timestamp}.json"

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"  Audit report exported: {fpath}")
    print(f"  Records: {len(rows)}")
    print()


def _generate_html_report(store: Any, trace_ids: list[str], output_path: str | None) -> None:
    """Generate an HTML audit report."""
    rows = _collect_execution_rows(store, trace_ids)

    if not rows:
        print("  No execution data to export.")
        return

    total_cost = sum(r["cost_usd"] for r in rows)
    total_tokens = sum(_safe_int(r["tokens"]) for r in rows)
    success = sum(1 for r in rows if r["status"] == "success")
    failed = sum(1 for r in rows if r["status"] == "failure")

    rows_html = ""
    for r in rows:
        status_badge = "green" if r["status"] == "success" else "red"
        rows_html += f"""<tr>
  <td>{r["timestamp"][:10]}</td>
  <td class="mono">{r["trace_id"][:12]}...</td>
  <td>{r["capability"]}</td>
  <td><span class="badge" style="background:{status_badge}">{r["status"]}</span></td>
  <td>{r["runtime"]}</td>
  <td>${r["cost_usd"]:.4f}</td>
  <td>{r["tokens"]:,}</td>
  <td>{r["duration_ms"]:.0f}ms</td>
  <td>{r["agents"]}</td>
  <td>{r["models"]}</td>
</tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Intent OS — Compliance Audit Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1200px; margin: 30px auto; padding: 0 20px; background: #0d1117; color: #e6edf3; }}
  h1 {{ font-size: 1.6em; border-bottom: 1px solid #30363d; padding-bottom: 12px; }}
  .summary {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin: 20px 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; }}
  .summary-item .label {{ color: #8b949e; font-size: 0.85em; }}
  .summary-item .value {{ font-size: 1.3em; font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.85em; }}
  th {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #30363d; color: #8b949e; white-space: nowrap; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #21262d; }}
  .mono {{ font-family: monospace; font-size: 0.9em; }}
  .badge {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 0.8em; font-weight: 600; color: white; }}
  .footer {{ margin-top: 30px; padding-top: 16px; border-top: 1px solid #30363d; color: #8b949e; font-size: 0.8em; }}
  tr:hover td {{ background: rgba(255,255,255,0.03); }}
</style>
</head>
<body>
<h1>Compliance Audit Report</h1>

<div class="summary">
  <div class="summary-item"><div class="label">Total Executions</div><div class="value">{len(rows)}</div></div>
  <div class="summary-item"><div class="label">Successful</div><div class="value" style="color:#3fb950;">{success}</div></div>
  <div class="summary-item"><div class="label">Failed</div><div class="value" style="color:#f85149;">{failed}</div></div>
  <div class="summary-item"><div class="label">Total Cost</div><div class="value">${total_cost:.4f}</div></div>
  <div class="summary-item"><div class="label">Total Tokens</div><div class="value">{total_tokens:,}</div></div>
  <div class="summary-item"><div class="label">Generated</div><div class="value" style="font-size:0.9em;">{datetime.now().strftime('%Y-%m-%d %H:%M')}</div></div>
</div>

<h2>Execution Records</h2>
<table>
<thead><tr>
  <th>Date</th><th>Trace ID</th><th>Capability</th><th>Status</th><th>Runtime</th>
  <th>Cost</th><th>Tokens</th><th>Duration</th><th>Agents</th><th>Models</th>
</tr></thead>
<tbody>
{rows_html}
</tbody>
</table>

<div class="footer">
  Generated by Intent OS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
</div>
</body>
</html>"""

    if output_path:
        fpath = output_path
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = f"intent-os-audit-{timestamp}.html"

    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Audit report exported: {fpath}")
    print(f"  Records: {len(rows)}")
    print(f"  Open in browser: file://{Path(fpath).resolve()}")
    print()
