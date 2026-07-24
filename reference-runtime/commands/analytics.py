"""
Intent OS — CLI Command: analytics

Analyzes execution history from the Event Store.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from commands.helpers import get_event_store

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def cmd_analytics(args: Any) -> None:
    """Analyze execution history from the Event Store."""
    from core.analytics import AnalyticsEngine
    store = get_event_store()
    analytics = AnalyticsEngine(store)

    if args.action == "summary":
        summary = analytics.get_trend_summary(days=30)
        total = summary['total_executions']
        print(f"Execution Summary (last 30 days)")
        print(f"  Total executions: {total}")
        if total == 0:
            print()
            print("  [i] No execution data yet. Generate your first record:")
            print("    1. Install Ollama:  ollama pull llama3.2:1b && ollama serve")
            print("    2. Run a capability: intent-os run examples/text_summarize.yaml")
            print("    3. View analytics:  intent-os analytics capabilities")
            print()
            return
        print(f"  Top capabilities:")
        for cap in summary['top_capabilities'][:5]:
            print(f"    {cap['capability']}: score={cap['performance_score']}, success={cap['success_rate']:.0%}")
        print(f"  Failure patterns:")
        for pat in summary['failure_patterns'][:5]:
            print(f"    {pat.get('manifest_name','?')} on {pat.get('runtime_id','?')}: {pat.get('failure_count',0)} failures")

    elif args.action == "capabilities":
        rankings = analytics.get_capability_rankings()
        if not rankings:
            print("No execution data available.")
            print()
            print("  [i] Run a capability first to generate execution data:")
            print("    intent-os run examples/text_summarize.yaml --adapter ollama \\")
            print("      --input '{\"text\": \"Hello world\"}'")
            print()
            return
        print(f"Capability Rankings ({len(rankings)}):")
        print(f"  {'Name':<30} {'Score':<8} {'Success':<10} {'Latency':<12} {'Cost':<10}")
        print(f"  {'-'*70}")
        for cap in rankings:
            print(f"  {cap['capability']:<30} {cap['performance_score']:<8.1f} {cap['success_rate']:<10.0%} {cap['avg_latency_ms']:<12.0f}ms ${cap['avg_cost_usd']:<8.4f}")

    elif args.action == "runtimes":
        comparison = analytics.get_runtime_comparison()
        if not comparison:
            print("No execution data available.")
            print()
            print("  [i] Execute the same capability on different adapters to compare:")
            print("    intent-os run examples/text_summarize.yaml --adapter openai     \\")
            print("      --input '{\"text\": \"Hello\"}'")
            print("    intent-os run examples/text_summarize.yaml --adapter ollama     \\")
            print("      --input '{\"text\": \"Hello\"}'")
            print()
            return
        print(f"Runtime Comparison:")
        print(f"  {'Runtime':<20} {'Runs':<8} {'Success':<10} {'Latency':<12} {'Cost':<10}")
        print(f"  {'-'*60}")
        for r in comparison:
            sr = r.get('success_rate', 0) or 0
            print(f"  {r['runtime_id']:<20} {r['total_runs']:<8} {sr:<10.0%} {r.get('avg_latency_ms',0):<12.0f}ms ${r.get('avg_cost_usd',0):<8.4f}")

    elif args.action == "failures":
        report = analytics.get_failure_report()
        print(f"Failure Analysis")
        print(f"  Total records: {report['total_records']}")
        print(f"  Total failures: {report['total_failures']}")
        if report['total_records'] == 0:
            print()
            print("  [i] No execution data to analyze. Run some capabilities first:")
            print("    intent-os run examples/text_summarize.yaml --adapter ollama")
            print()
            return
        print(f"  Overall failure rate: {report['overall_failure_rate']:.2%}")
        print(f"\n  Most error-prone capabilities:")
        for cap in report['most_error_prone'][:10]:
            print(f"    {cap['capability']}: {cap['failure_count']}/{cap['total_runs']} ({cap['failure_rate']:.1%})")

    elif args.action == "trends":
        trend = analytics.get_cost_trend(days=30)
        print(f"Cost Trends (last 30 days)")
        print(f"  Total executions: {trend['total_executions']}")
        if trend['total_executions'] == 0:
            print()
            print("  [i] No cost data yet. Run capabilities across different adapters")
            print("     to see cost comparisons:")
            print("    intent-os compare examples/text_summarize.yaml \\")
            print("      --input '{\"text\": \"Hello world\"}'")
            print()
            return
        print(f"  Total cost: ${trend['total_cost_usd']:.4f}")
        print(f"  Avg cost/execution: ${trend['avg_cost_per_execution']:.4f}")
        print(f"\n  Cost by runtime:")
        for r in trend['cost_by_runtime']:
            print(f"    {r['runtime']:<20} {r['total_runs']:<8} runs avg ${r['avg_cost']:<8.4f}")

    elif args.action == "suggestions":
        suggestions = analytics.get_optimization_suggestions()
        if not suggestions:
            print("No optimization suggestions at this time.")
            print()
            print("  [i] Suggestions appear after you've run capabilities across")
            print("     multiple adapters. Try comparing runtimes:")
            print("    intent-os compare examples/text_summarize.yaml \\")
            print("      --input '{\"text\": \"Hello world\"}'")
            print()
            return
        print(f"Optimization Suggestions ({len(suggestions)}):")
        for s in suggestions:
            print(f"\n  [{s['type']}]")
            print(f"  Suggestion: {s['suggestion']}")
            print(f"  Expected: {s['expected_impact']}")

    elif args.action == "export":
        data = analytics.export_cost_model_data(
            limit=args.limit or 1000,
            output_path=args.output_path,
        )
        print(f"[OK] Exported {len(data)} records")
        if len(data) == 0:
            print()
            print("  [i] No execution data to export. Run capabilities first:")
            print("    intent-os run examples/text_summarize.yaml --adapter ollama")
            print()
        if args.output_path:
            print(f"  Saved to: {args.output_path}")

    elif args.action == "agent":
        _cmd_analytics_agent(store, args)
    elif args.action == "compare":
        _cmd_analytics_compare(store, args)
    elif args.action == "anomaly":
        _cmd_analytics_anomaly(store, args)
    else:
        print(f"Unknown analytics action: {args.action}", file=sys.stderr)
        sys.exit(1)


def _cmd_analytics_agent(store: Any, args: Any) -> None:
    """Per-agent execution analytics (Blueprint Phase 2.2)."""
    from core.execution_analytics import AgentAnalytics
    aa = AgentAnalytics(store)
    agent_id = args.agent_id
    report = aa.agent_summary(agent_id)

    print()
    print("  ================================================")
    print("    Agent Analytics")
    print("  ================================================")
    print()
    print(f"  Agent:          {agent_id}")
    print(f"  Total runs:     {report['total_executions']}")
    print(f"  Success rate:   {report['success_rate']:.1%}")
    print(f"  Avg latency:    {report['avg_latency_ms']:.0f}ms")
    print(f"  Total cost:     ${report['total_cost_usd']:.4f}")
    print(f"  Total tokens:   {report['total_tokens']}")
    if report.get('first_seen'):
        print(f"  First seen:     {report['first_seen'][:19]}")
    if report.get('last_seen'):
        print(f"  Last seen:      {report['last_seen'][:19]}")
    print()
    if report.get('models_used'):
        print("  Models used:")
        for m in report['models_used']:
            print(f"    {m}")
        print()
    if report.get('top_failure_reasons'):
        print("  Top failure reasons:")
        for f in report['top_failure_reasons'][:5]:
            print(f"    {f['error']}: {f['count']} times")
        print()


def _cmd_analytics_compare(store: Any, args: Any) -> None:
    """Side-by-side agent comparison."""
    from core.execution_analytics import AgentAnalytics
    aa = AgentAnalytics(store)
    result = aa.agent_compare(args.agent_a, args.agent_b)

    print()
    print("  ================================================")
    print("    Agent Comparison")
    print("  ================================================")
    print()
    a = result.get('agent_a', {})
    b = result.get('agent_b', {})
    d = result.get('delta', {})

    header = f"  {'Metric':<22} {'Agent A':<18} {'Agent B':<18} {'Delta'}"
    print(header)
    print(f"  {'-'*70}")

    rows = [
        ("Success rate", f"{a.get('success_rate',0):.1%}", f"{b.get('success_rate',0):.1%}",
         f"{d.get('success_rate_diff',0):+.1%}"),
        ("Total executions", str(a.get('total_executions',0)), str(b.get('total_executions',0)),
         f"{int(b.get('total_executions',0)) - int(a.get('total_executions',0)):+d}"),
        ("Avg latency", f"{a.get('avg_latency_ms',0):.0f}ms", f"{b.get('avg_latency_ms',0):.0f}ms",
         f"{d.get('avg_latency_ratio',1):.2f}x"),
        ("Total cost", f"${a.get('total_cost_usd',0):.4f}", f"${b.get('total_cost_usd',0):.4f}",
         f"${d.get('cost_diff_usd',0):+.4f}"),
    ]
    for metric, va, vb, vd in rows:
        print(f"  {metric:<22} {va:<18} {vb:<18} {vd}")
    print()
    if d.get('winner'):
        print(f"  Winner: {d['winner']}")
        print(f"  Score A: {d.get('score_a',0):.1f} / Score B: {d.get('score_b',0):.1f}")
    print()


def _cmd_analytics_anomaly(store: Any, args: Any) -> None:
    """Detect execution anomalies."""
    from core.execution_analytics import AgentAnalytics
    aa = AgentAnalytics(store)
    anomalies = aa.detect_anomalies(since_days=_parse_since_days(args.since))

    print()
    print("  ================================================")
    print("    Anomaly Detection")
    print("  ================================================")
    print()
    if not anomalies:
        print("  No anomalies detected.")
        print()
        return

    print(f"  Found {len(anomalies)} anomalies:")
    print()
    for a in anomalies[:20]:
        ratio = a.get('ratio', 0)
        if ratio > 10:
            severity = "critical"
        elif ratio > 5:
            severity = "high"
        elif ratio > 3:
            severity = "medium"
        else:
            severity = "low"
        sev = {"critical": "!!", "high": "! ", "medium": "~ ", "low": "  "}.get(severity, '  ')
        label = a.get('anomaly_type', '?')
        print(f"  {sev} {label}: {a.get('detail','')}")
        print(f"     Agent: {a.get('agent_name','?')}  Value: {a.get('value',0):.2f}  Baseline: {a.get('baseline_avg',0):.2f}  Ratio: {ratio:.1f}x")
        print(f"     Trace: {a.get('trace_id','?')[:24]}  Time: {a.get('timestamp','?')[:19]}")
        print()
    if len(anomalies) > 20:
        print(f"  ... and {len(anomalies) - 20} more.")


def _parse_since_days(s: str) -> int:
    """Parse a duration string like '7d', '24h', '90d' into days."""
    s = s.strip().lower()
    if s.endswith('d'):
        return int(s[:-1])
    if s.endswith('h'):
        return max(1, int(s[:-1]) // 24)
    return 7
