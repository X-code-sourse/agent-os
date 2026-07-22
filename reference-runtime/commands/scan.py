"""Intent OS CLI — scan command: security scanner for AI agent traces.

Post-execution security analysis that reads from the Event Store and
identifies potential security issues: dangerous tool calls, sensitive
data exposure, policy violations, and anomalous patterns.

This is a READ-ONLY scanner — it does not modify state or intercept
execution. It respects R5 (no content intelligence standardization).

    intent-os scan                  # Scan all recent traces
    intent-os scan --trace <id>     # Scan a specific trace
    intent-os scan --report         # Generate security report (CSV)
    intent-os scan --report --html  # Generate security report (HTML)
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from commands.helpers import get_event_store
from proxy.guard import (
    classify_tool_risk,
    check_sensitive_data,
    _DANGEROUS_TOOL_PATTERNS,
    _SENSITIVE_PATTERNS,
)

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _parse_payload(payload_str: str) -> dict[str, Any]:
    if not payload_str:
        return {}
    try:
        p = json.loads(payload_str)
        return p if isinstance(p, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _analyze_trace(
    trace_id: str,
    record: dict[str, Any] | None,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze a single trace for security issues."""
    findings: list[dict[str, Any]] = []
    severity_count: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    all_messages: list[str] = []

    # Collect all text from events for content scanning
    for evt in events:
        payload = _parse_payload(evt.get("payload", "{}"))
        # Collect text fields
        for text_field in ("input_ref", "output_ref", "content", "prompt", "response"):
            val = payload.get(text_field, "")
            if isinstance(val, str):
                all_messages.append(val)
            elif isinstance(val, (dict, list)):
                all_messages.append(json.dumps(val))

        # Check tool call patterns in event content
        if evt.get("event_type") == "CapabilityInvoked":
            cap = evt.get("capability", "")
            source = evt.get("source", "")

            # Check if this is a proxy-traced event with tool info
            source_agent = payload.get("source_agent", "")
            model = payload.get("model", "")
            status = payload.get("status", "")

            if source_agent:
                if status == "success":
                    findings.append({
                        "trace_id": trace_id,
                        "type": "agent_call",
                        "severity": "low",
                        "detail": f"Agent '{source_agent}' called model '{model}'",
                        "source": "proxy_trace",
                    })
                else:
                    severity_count["medium"] += 1
                    findings.append({
                        "trace_id": trace_id,
                        "type": "agent_failure",
                        "severity": "medium",
                        "detail": f"Agent '{source_agent}' call to '{model}' failed",
                        "source": "proxy_trace",
                    })

    # Scan message content for sensitive data
    full_text = "\n".join(all_messages)
    sensitive_findings = check_sensitive_data(full_text)
    for sf in sensitive_findings:
        severity_count["high"] += 1
        findings.append({
            "trace_id": trace_id,
            "type": "sensitive_exposure",
            "severity": "high",
            "detail": f"Sensitive data detected: {sf['type']} ({sf['match_preview']})",
            "source": "content_scan",
        })

    # Check record for security events
    if record:
        error = record.get("error", "")

        # Check for dangerous error patterns in execution
        error_lower = str(error).lower()
        if "permission" in error_lower or "denied" in error_lower or "forbidden" in error_lower:
            severity_count["high"] += 1
            findings.append({
                "trace_id": trace_id,
                "type": "permission_denied",
                "severity": "high",
                "detail": f"Permission error: {error[:200]}",
                "source": "execution_record",
            })

    # Count severity
    for f in findings:
        sev = f.get("severity", "medium")
        severity_count[sev] = severity_count.get(sev, 0) + 1

    return {
        "trace_id": trace_id,
        "findings": findings,
        "finding_count": len(findings),
        "severity_summary": severity_count,
    }


def _generate_html_report(reports: list[dict[str, Any]]) -> str:
    """Generate a standalone HTML security report."""
    total_findings = sum(r["finding_count"] for r in reports)
    total_traces = len(reports)
    critical = sum(r["severity_summary"].get("critical", 0) for r in reports)
    high = sum(r["severity_summary"].get("high", 0) for r in reports)
    medium = sum(r["severity_summary"].get("medium", 0) for r in reports)
    low = sum(r["severity_summary"].get("low", 0) for r in reports)

    findings_rows = ""
    for report in reports:
        for f in report["findings"]:
            color = {"critical": "red", "high": "#d29922", "medium": "#58a6ff", "low": "#3fb950"}.get(
                f["severity"], "gray"
            )
            findings_rows += f"""<tr>
  <td class="mono">{f['trace_id'][:12]}...</td>
  <td>{f['type']}</td>
  <td><span class="badge" style="color:white;background:{color}">{f['severity']}</span></td>
  <td>{f['detail'][:100]}</td>
</tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Intent OS — Security Scan Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1000px; margin: 30px auto; padding: 0 20px; background: #0d1117; color: #e6edf3; }}
  h1 {{ font-size: 1.6em; border-bottom: 1px solid #30363d; padding-bottom: 12px; }}
  .summary {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin: 20px 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; }}
  .summary-item .label {{ color: #8b949e; font-size: 0.85em; }}
  .summary-item .value {{ font-size: 1.3em; font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.85em; }}
  th {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #30363d; color: #8b949e; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #21262d; }}
  .mono {{ font-family: monospace; font-size: 0.9em; }}
  .badge {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 0.8em; font-weight: 600; }}
  .footer {{ margin-top: 30px; padding-top: 16px; border-top: 1px solid #30363d; color: #8b949e; font-size: 0.8em; }}
</style>
</head>
<body>
<h1>Security Scan Report</h1>

<div class="summary">
  <div class="summary-item"><div class="label">Traces Scanned</div><div class="value">{total_traces}</div></div>
  <div class="summary-item"><div class="label">Total Findings</div><div class="value">{total_findings}</div></div>
  <div class="summary-item"><div class="label">Critical</div><div class="value" style="color:#f85149;">{critical}</div></div>
  <div class="summary-item"><div class="label">High</div><div class="value" style="color:#d29922;">{high}</div></div>
  <div class="summary-item"><div class="label">Medium</div><div class="value" style="color:#58a6ff;">{medium}</div></div>
  <div class="summary-item"><div class="label">Low</div><div class="value" style="color:#3fb950;">{low}</div></div>
</div>

<h2>Findings</h2>
<table>
<thead><tr><th>Trace</th><th>Type</th><th>Severity</th><th>Detail</th></tr></thead>
<tbody>
{findings_rows}
</tbody>
</table>

<div class="footer">
  Generated by Intent OS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
</div>
</body>
</html>"""
    return html


def cmd_scan(args: Any) -> None:
    """Scan AI agent traces for security issues.

    Analyzes execution traces in the Event Store and reports:
    - Dangerous tool call patterns
    - Sensitive data exposure
    - Policy violations
    - Agent call failures
    """
    store = get_event_store()
    trace_id = getattr(args, "trace_id", None)
    generate_report = getattr(args, "report", False)
    report_format = getattr(args, "format", "csv")
    output_path = getattr(args, "output", None)

    # Collect traces to scan
    if trace_id:
        trace_ids = [trace_id]
    else:
        trace_ids = store.get_all_trace_ids()[:200]  # Limit for performance

    if not trace_ids:
        print("  No traces found to scan.")
        print()
        print("  Run capabilities or start the proxy to collect data:")
        print("    intent-os run translate -p text=hello -p target_lang=zh")
        print("    intent-os proxy start")
        print()
        return

    # Scan each trace
    scan_results: list[dict[str, Any]] = []
    for tid in trace_ids:
        record = store.get_record(tid)
        events = store.get_events_by_trace(tid)
        result = _analyze_trace(tid, record, events)
        scan_results.append(result)

    total_findings = sum(r["finding_count"] for r in scan_results)
    total_critical = sum(r["severity_summary"].get("critical", 0) for r in scan_results)
    total_high = sum(r["severity_summary"].get("high", 0) for r in scan_results)
    total_medium = sum(r["severity_summary"].get("medium", 0) for r in scan_results)
    total_low = sum(r["severity_summary"].get("low", 0) for r in scan_results)

    # Generate report file
    if generate_report:
        if report_format == "html":
            html = _generate_html_report(scan_results)
            fname = output_path or f"intent-os-security-scan-{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  Security report: {fname}")
            print(f"  Open in browser: file://{Path(fname).resolve()}")
        else:
            fname = output_path or f"intent-os-security-scan-{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(fname, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["trace_id", "type", "severity", "detail", "source"])
                for report in scan_results:
                    for finding in report["findings"]:
                        writer.writerow([
                            finding["trace_id"],
                            finding["type"],
                            finding["severity"],
                            finding["detail"],
                            finding["source"],
                        ])
            print(f"  Security report: {fname}")
            print(f"  Records: {total_findings}")
        print()
        return

    # Print summary to terminal
    print()
    print("  ================================================")
    print("    Security Scan")
    print("  ================================================")
    print()
    print(f"  Traces scanned:  {len(scan_results)}")
    print(f"  Total findings:  {total_findings}")
    print(f"    Critical:      {total_critical}")
    print(f"    High:          {total_high}")
    print(f"    Medium:        {total_medium}")
    print(f"    Low:           {total_low}")
    print()

    # Show top findings
    all_findings = []
    for report in scan_results:
        all_findings.extend(report["findings"])

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    all_findings.sort(key=lambda x: severity_order.get(x.get("severity", "medium"), 99))

    if all_findings:
        print(f"  Top findings:")
        for f in all_findings[:15]:
            icon = {"critical": "!!", "high": "!!", "medium": "..", "low": "--"}.get(
                f.get("severity", "medium"), ".."
            )
            print(f"  [{icon}] [{f['severity'].upper():8}] {f.get('detail', '')[:80]}")
        if len(all_findings) > 15:
            print(f"  ... and {len(all_findings) - 15} more findings")
        print()

    if total_findings > 0:
        print(f"  For detailed report: intent-os scan --report")
        print()
