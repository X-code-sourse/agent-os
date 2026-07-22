#!/usr/bin/env python3
"""Intent OS — Reference Runtime CLI"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

import commands.validate
import commands.run
import commands.compare
import commands.list
import commands.registry
import commands.event
import commands.analytics
import commands.workflow
import commands.mcp_server
import commands.import_cmd
import commands.export
import commands.quickstart
import commands.evolution
import commands.ask
import commands.demo
import commands.trace
import commands.proxy
import commands.doctor

# All cmd_* functions are imported from command modules via the registry pattern below
CMD_MAP = {
    "validate": commands.validate.cmd_validate,
    "run": commands.run.cmd_run,
    "compare": commands.compare.cmd_compare,
    "list": commands.list.cmd_list,
    "registry": commands.registry.cmd_registry,
    "event": commands.event.cmd_event,
    "analytics": commands.analytics.cmd_analytics,
    "workflow": commands.workflow.cmd_workflow,
    "mcp-server": commands.mcp_server.cmd_mcp_server,
    "import": commands.import_cmd.cmd_import,
    "export": commands.export.cmd_export,
    "quickstart": commands.quickstart.cmd_quickstart,
    "evolution": commands.evolution.cmd_evolution,
    "ask": commands.ask.cmd_ask,
    "demo": commands.demo.cmd_demo,
    "inspect": commands.trace.cmd_inspect,
    "proxy": commands.proxy.cmd_proxy,
    "doctor": commands.doctor.cmd_doctor,
}

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="intent-os",
        description="Intent OS Reference Runtime - Open AI Capability Interoperability",
        epilog="Phase 0 - Prove that one Manifest can run on multiple runtimes.",
    )
    parser.add_argument("--version", action="version", version="intent-os 0.4.1")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate a Capability Manifest")
    validate_parser.add_argument("manifest", help="Path to Capability Manifest YAML file")
    validate_parser.set_defaults(func=CMD_MAP["validate"])

    # run
    run_parser = subparsers.add_parser("run", help="Execute a capability on a runtime")
    run_parser.add_argument("manifest", help="Path to .yaml manifest or built-in capability name (e.g. 'translate')")
    run_parser.add_argument("text", nargs="?", default=None,
                            help="Inline text input (maps to the manifest's 'text' field)")
    run_parser.add_argument("--adapter", "-a", default=None, help="Runtime adapter (openai, anthropic, ollama)")
    run_parser.add_argument("--input", "-i", default=None, help="Input JSON string")
    run_parser.add_argument("--input-file", "-f", default=None, help="Input JSON file")
    run_parser.add_argument("--param", "-p", action="append", default=None,
                            help="Input parameter as key=value (can be repeated, e.g. -p target_lang=zh)")
    run_parser.add_argument("--output", "-o", default=None, help="Save execution record to file")
    run_parser.add_argument("--save", "-s", default=None, help="Save execution record path")
    run_parser.set_defaults(func=CMD_MAP["run"])

    # compare
    compare_parser = subparsers.add_parser("compare", help="Execute on all runtimes and compare results")
    compare_parser.add_argument("manifest", help="Path to Capability Manifest YAML file")
    compare_parser.add_argument("--input", "-i", default=None, help="Input JSON string")
    compare_parser.add_argument("--save", "-s", default=None, help="Directory to save records")
    compare_parser.set_defaults(func=CMD_MAP["compare"])

    # list
    list_parser = subparsers.add_parser("list", help="List available adapters and capabilities")
    list_parser.set_defaults(func=CMD_MAP["list"])

    # registry
    registry_parser = subparsers.add_parser("registry", help="Manage the capability registry")
    registry_sub = registry_parser.add_subparsers(dest="action", help="Registry actions")
    reg_list = registry_sub.add_parser("list", help="List all registered capabilities")
    reg_list.set_defaults(action="list", func=CMD_MAP["registry"])
    reg_get = registry_sub.add_parser("get", help="Get capability details")
    reg_get.add_argument("name", help="Capability name")
    reg_get.add_argument("--version", "-v", default=None, help="Version (default: latest)")
    reg_get.set_defaults(func=CMD_MAP["registry"])
    reg_register = registry_sub.add_parser("register", help="Register a capability from a Manifest")
    reg_register.add_argument("manifest_path", help="Path to Capability Manifest YAML file")
    reg_register.set_defaults(func=CMD_MAP["registry"])
    reg_unregister = registry_sub.add_parser("unregister", help="Unregister a capability")
    reg_unregister.add_argument("name", help="Capability name")
    reg_unregister.add_argument("--version", "-v", default=None, help="Version (omit for all)")
    reg_unregister.set_defaults(func=CMD_MAP["registry"])
    reg_export = registry_sub.add_parser("export", help="Export registry snapshot to JSON")
    reg_export.add_argument("output_path", help="Output JSON file path")
    reg_export.set_defaults(func=CMD_MAP["registry"])
    reg_search = registry_sub.add_parser("search", help="Semantic search for capabilities by text query")
    reg_search.add_argument("query", help="Free-text search query")
    reg_search.add_argument("--limit", "-l", type=int, default=10, help="Max results (default: 10)")
    reg_search.set_defaults(func=CMD_MAP["registry"])

    # security
    _build_security_parser(subparsers)

    # event
    event_parser = subparsers.add_parser("event", help="Query execution events from the Event Store")
    event_sub = event_parser.add_subparsers(dest="action", help="Event actions")
    ev_list = event_sub.add_parser("list", help="List Event Store statistics")
    ev_list.set_defaults(func=CMD_MAP["event"])
    ev_trace = event_sub.add_parser("trace", help="View events for a specific trace ID")
    ev_trace.add_argument("trace_id", help="Trace ID to inspect")
    ev_trace.set_defaults(func=CMD_MAP["event"])
    ev_query = event_sub.add_parser("query", help="Query events with filters")
    ev_query.add_argument("--trace-id", dest="trace_id", default=None)
    ev_query.add_argument("--event-type", default=None)
    ev_query.add_argument("--capability", default=None)
    ev_query.add_argument("--runtime", default=None)
    ev_query.add_argument("--limit", type=int, default=20)
    ev_query.set_defaults(func=CMD_MAP["event"])

    # analytics
    analytics_parser = subparsers.add_parser("analytics", help="Analyze execution history")
    analytics_sub = analytics_parser.add_subparsers(dest="action", help="Analytics actions")
    for name, help_text in [
        ("summary", "Overall execution summary"),
        ("capabilities", "Capability performance rankings"),
        ("runtimes", "Runtime comparison"),
        ("failures", "Failure analysis report"),
        ("trends", "Cost trends over time"),
        ("suggestions", "Optimization suggestions"),
    ]:
        p = analytics_sub.add_parser(name, help=help_text)
        p.set_defaults(func=CMD_MAP["analytics"])
    an_export = analytics_sub.add_parser("export", help="Export cost model training data")
    an_export.add_argument("output_path", nargs="?", default=None)
    an_export.add_argument("--limit", type=int, default=1000)
    an_export.set_defaults(func=CMD_MAP["analytics"])

    # workflow
    workflow_parser = subparsers.add_parser("workflow", help="Plan and run workflows")
    workflow_parser.add_argument("action", choices=["run", "plan", "optimize"])
    workflow_parser.add_argument("query", nargs="?", default=None,
                                 help="Workflow YAML path (for run) or goal text (for plan)")
    workflow_parser.add_argument("--input", "-i", default=None, help="Input JSON (for run)")
    workflow_parser.add_argument("--adapter", "-a", default=None, help="Runtime adapter (for run)")
    workflow_parser.add_argument("--simulate", action="store_true",
                                 help="Force simulated execution (for run)")
    workflow_parser.set_defaults(func=CMD_MAP["workflow"])

    # mcp-server
    mcp_parser = subparsers.add_parser("mcp-server", help="Start or manage the Intent OS MCP Server")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_action", help="MCP Server actions")
    mcp_start = mcp_sub.add_parser("start", help="Start the MCP Server (SSE transport)")
    mcp_start.add_argument("--port", type=int, default=8080)
    mcp_start.add_argument("--host", default="127.0.0.1")
    mcp_start.add_argument("--adapter", default="ollama")
    mcp_start.set_defaults(func=CMD_MAP["mcp-server"])
    mcp_status = mcp_sub.add_parser("status", help="Show MCP Server status")
    mcp_status.add_argument("--port", type=int, default=8080)
    mcp_status.add_argument("--adapter", default="ollama")
    mcp_status.set_defaults(func=CMD_MAP["mcp-server"])

    # import
    import_parser = subparsers.add_parser("import", help="Import a capability from an external format")
    import_parser.add_argument("format", choices=["openai-function", "mcp-server"])
    import_parser.add_argument("source", help="Source file path or URL")
    import_parser.add_argument("--output-dir", "-o", default="./manifests")
    import_parser.add_argument("--publisher", default=None)
    import_parser.add_argument("--tags", default=None, help="Comma-separated tags")
    import_parser.add_argument("--timeout", type=int, default=30)
    import_parser.set_defaults(func=CMD_MAP["import"])

    # export
    export_parser = subparsers.add_parser("export", help="Export a capability to an external format")
    export_parser.add_argument("format", choices=["openai", "mcp"])
    export_parser.add_argument("source", help="Manifest YAML file path or capability name")
    export_parser.add_argument("--output", "-o", default=None, help="Output file path")
    export_parser.add_argument("--as-tool", action="store_true", help="Wrap in OpenAI tool format")
    export_parser.set_defaults(func=CMD_MAP["export"])

    # quickstart
    qs_parser = subparsers.add_parser("quickstart", help="Display a getting-started guide")
    qs_parser.set_defaults(func=CMD_MAP["quickstart"])

    # evolution
    evolution_parser = subparsers.add_parser("evolution", help="Run the Evolution Loop for continuous optimization")
    evolution_sub = evolution_parser.add_subparsers(dest="action", help="Evolution actions")

    ev_run = evolution_sub.add_parser("run", help="Run one iteration of the Evolution Loop")
    ev_run.set_defaults(func=CMD_MAP["evolution"])

    ev_status = evolution_sub.add_parser("status", help="Show the number of pending suggestions")
    ev_status.set_defaults(func=CMD_MAP["evolution"])

    ev_queue = evolution_sub.add_parser("queue", help="List suggestions awaiting review")
    ev_queue.set_defaults(func=CMD_MAP["evolution"])

    ev_approve = evolution_sub.add_parser("approve", help="Approve a pending suggestion by ID")
    ev_approve.add_argument("suggestion_id", type=int, help="Database ID of the suggestion to approve")
    ev_approve.set_defaults(func=CMD_MAP["evolution"])

    ev_reject = evolution_sub.add_parser("reject", help="Reject a pending suggestion by ID")
    ev_reject.add_argument("suggestion_id", type=int, help="Database ID of the suggestion to reject")
    ev_reject.set_defaults(func=CMD_MAP["evolution"])

    # ask
    ask_parser = subparsers.add_parser("ask", help="Execute capabilities using natural language")
    ask_parser.add_argument("query", nargs="?", default=None, help="Natural language query")
    ask_parser.add_argument("--provider", default="auto", help="LLM provider (auto, ollama, openai, anthropic)")
    ask_parser.set_defaults(func=CMD_MAP["ask"])

    # demo
    demo_parser = subparsers.add_parser("demo",
        help="Run an interactive terminal demo of the Agent Flight Recorder")
    demo_parser.add_argument("--auto", action="store_true",
                             help="Run non-interactively (skip all pauses)")
    demo_parser.set_defaults(func=CMD_MAP["demo"])

    # inspect
    inspect_parser = subparsers.add_parser("inspect",
        help="Show an agent execution trace — see what your agent did, why it failed, and how much it cost")
    inspect_parser.add_argument("trace_id", nargs="?", default="latest",
                                help="Trace ID to inspect (default: latest)")
    inspect_parser.add_argument("--html", action="store_true",
                                help="Export trace as a standalone HTML file for sharing")
    inspect_parser.set_defaults(func=CMD_MAP["inspect"])

    # proxy
    proxy_parser = subparsers.add_parser("proxy",
        help="Start the Agent Hook proxy to record AI agent API calls")
    proxy_sub = proxy_parser.add_subparsers(dest="proxy_action", help="Proxy actions")
    ps = proxy_sub.add_parser("start", help="Start the proxy server")
    ps.add_argument("--port", type=int, default=8377, help="Port (default: 8377)")
    ps.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    ps.set_defaults(func=CMD_MAP["proxy"])
    pst = proxy_sub.add_parser("status", help="Check if the proxy is running")
    pst.add_argument("--port", type=int, default=8377, help="Port (default: 8377)")
    pst.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    pst.set_defaults(func=CMD_MAP["proxy"])

    # doctor
    doctor_parser = subparsers.add_parser("doctor",
        help="Check your AI agent's health — see what happened, what went wrong, and how to fix it")
    doctor_parser.set_defaults(func=CMD_MAP["doctor"])

    return parser


def _build_security_parser(subparsers: Any) -> None:
    """Register security subcommands with our existing dispatch pattern."""
    import commands.security

    sec_parser = subparsers.add_parser("security", help="Manage security policies and evaluation")
    sec_sub = sec_parser.add_subparsers(dest="security_action", help="Security actions")

    # policy list / get / apply
    pl = sec_sub.add_parser("policy", help="Manage policies")
    pl_sub = pl.add_subparsers(dest="policy_action")
    pl_list = pl_sub.add_parser("list", help="List all policies")
    pl_list.set_defaults(func=commands.security.cmd_policy_list)
    pl_get = pl_sub.add_parser("get", help="Get policy details")
    pl_get.add_argument("name", help="Policy name")
    pl_get.set_defaults(func=commands.security.cmd_policy_get)
    pl_apply = pl_sub.add_parser("apply", help="Apply a policy from YAML file")
    pl_apply.add_argument("file", help="Path to policy YAML file")
    pl_apply.set_defaults(func=commands.security.cmd_policy_apply)

    # evaluate / audit
    ev = sec_sub.add_parser("evaluate", help="Evaluate a capability against policies (dry run)")
    ev.add_argument("manifest", help="Path to Capability Manifest YAML file")
    ev.set_defaults(func=commands.security.cmd_evaluate)

    au = sec_sub.add_parser("audit", help="Export compliance report")
    au.set_defaults(func=commands.security.cmd_audit)


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        args.func(args)
    except Exception as exc:
        logging.debug("Command '%s' failed", args.command, exc_info=True)
        print(f"\nError: {exc}", file=sys.stderr)
        if args.command != "compare":
            sys.exit(1)


if __name__ == "__main__":
    main()
