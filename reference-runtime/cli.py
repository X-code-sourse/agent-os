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
import commands.cost
import commands.audit
import commands.scan
import commands.agent
import commands.context
import commands.evidence
import commands.experience
import commands.prune
import commands.db

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
    "cost": commands.cost.cmd_cost,
    "audit": commands.audit.cmd_audit,
    "scan": commands.scan.cmd_scan,
    "agent": commands.agent.cmd_agent,
    "context": commands.context.cmd_context,
    "evidence": commands.evidence.cmd_evidence,
    "experience": commands.experience.cmd_experience,
    "prune": commands.prune.cmd_prune,
    "db": commands.db.cmd_db,
}

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="intent-os",
        description="Intent OS Reference Runtime - Open AI Capability Interoperability",
        epilog="Phase 0 - Prove that one Manifest can run on multiple runtimes.",
    )
    parser.add_argument("--version", action="version", version="intent-os 0.6.0")

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
    run_parser.add_argument("--context", default=None,
                            help="Execution context ID for this run (use: intent-os context create)")
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

    # registry — defined below with extended marketplace subcommands

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
    ev_prune = event_sub.add_parser("prune", help="Prune events older than N days")
    ev_prune.add_argument("--older-than", type=int, default=90,
                          help="Prune events older than N days (default: 90)")
    ev_prune.add_argument("--force", action="store_true",
                          help="Actually delete (default: dry-run)")
    ev_prune.set_defaults(func=CMD_MAP["prune"])

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
    # Blueprint Phase 2.2: Agent-centric analytics
    an_agent = analytics_sub.add_parser("agent", help="Per-agent execution analytics")
    an_agent.add_argument("agent_id", help="Agent ID to analyze")
    an_agent.set_defaults(func=CMD_MAP["analytics"])
    an_compare = analytics_sub.add_parser("compare", help="Side-by-side agent comparison")
    an_compare.add_argument("--agent-a", required=True, help="First agent ID")
    an_compare.add_argument("--agent-b", required=True, help="Second agent ID")
    an_compare.set_defaults(func=CMD_MAP["analytics"])
    an_anomaly = analytics_sub.add_parser("anomaly", help="Detect execution anomalies")
    an_anomaly.add_argument("--since", default="7d", help="Time window (default: 7d)")
    an_anomaly.set_defaults(func=CMD_MAP["analytics"])

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
        help="Show an agent execution trace — see what your agent did, why it failed, and how much it cost",
        description="Displays a complete execution trace with execution ID, agent identity, "
                    "runtime, cost, tokens, and a full event timeline.")
    inspect_parser.add_argument("trace_id", nargs="?", default="latest",
                                help="Execution ID or trace ID to inspect (default: latest)")
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
    ps.add_argument("--guard", action="store_true",
                    help="Enable Tool Call Guard (inspect and classify tool call safety)")
    ps.add_argument("--agent", default=None,
                    help="Agent ID to associate with captured traces (use: intent-os agent create)")
    ps.add_argument("--context", default=None,
                    help="Execution context ID to associate with captured traces (use: intent-os context create)")
    ps.set_defaults(func=CMD_MAP["proxy"])
    pst = proxy_sub.add_parser("status", help="Check if the proxy is running")
    pst.add_argument("--port", type=int, default=8377, help="Port (default: 8377)")
    pst.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    pst.set_defaults(func=CMD_MAP["proxy"])
    pdoc = proxy_sub.add_parser("doctor", help="Run a full proxy health check")
    pdoc.add_argument("--port", type=int, default=8377, help="Port (default: 8377)")
    pdoc.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    pdoc.set_defaults(func=CMD_MAP["proxy"])

    # doctor
    doctor_parser = subparsers.add_parser("doctor",
        help="Check your AI agent's health — see what happened, what went wrong, and how to fix it",
        description="Checks the most recent agent execution and reports:\n"
                    "- Whether it succeeded or failed\n"
                    "- What went wrong (with error details)\n"
                    "- How to fix it\n"
                    "- How much it cost and how long it took")
    doctor_parser.set_defaults(func=CMD_MAP["doctor"])

    # cost
    cost_parser = subparsers.add_parser("cost",
        help="Show API cost breakdown by agent, model, and time period")
    cost_sub = cost_parser.add_subparsers(dest="action", help="Cost actions")

    # cost (no subcommand) — show spending breakdown
    cost_show = cost_sub.add_parser("show", help="Show API cost breakdown")
    cost_show.add_argument("--by", choices=["agent", "model"], default=None,
                           help="Group costs by agent or model (default: both)")
    cost_show.add_argument("--days", type=int, default=30,
                           help="Number of days to analyze (default: 30)")
    cost_show.set_defaults(func=CMD_MAP["cost"])

    # cost prices — manage pricing table
    cost_prices = cost_sub.add_parser("prices", help="List or update model pricing")
    cp_sub = cost_prices.add_subparsers(dest="prices_action", help="Pricing actions")
    cp_list = cp_sub.add_parser("list", help="Show current pricing table")
    cp_list.set_defaults(func=CMD_MAP["cost"])
    cp_update = cp_sub.add_parser("update", help="Update pricing for a model")
    cp_update.add_argument("--model", "-m", required=True, help="Model name")
    cp_update.add_argument("--input", type=float, default=None,
                           help="Input price per 1M tokens")
    cp_update.add_argument("--output", type=float, default=None,
                           help="Output price per 1M tokens")
    cp_update.set_defaults(func=CMD_MAP["cost"])

    # Default cost behavior (backward compat: just "cost" without subcommand)
    cost_parser.add_argument("--by", choices=["agent", "model"], default=None,
                             help="Group costs by agent or model (default: both)")
    cost_parser.add_argument("--days", type=int, default=30,
                             help="Number of days to analyze (default: 30)")
    cost_parser.set_defaults(func=CMD_MAP["cost"])

    # audit
    audit_parser = subparsers.add_parser("audit",
        help="Generate compliance-ready audit reports")
    audit_sub = audit_parser.add_subparsers(dest="audit_action", help="Audit actions")
    ar = audit_sub.add_parser("report", help="Generate an audit report")
    ar.add_argument("--format", choices=["csv", "html", "json"], default="csv",
                    help="Output format (default: csv)")
    ar.add_argument("--output", "-o", default=None,
                    help="Output file path")
    ar.add_argument("--days", type=int, default=90,
                    help="Number of days to analyze (default: 90)")
    ar.set_defaults(func=CMD_MAP["audit"])
    # Default: just show summary
    audit_parser.set_defaults(audit_action="summary", func=CMD_MAP["audit"])

    # scan
    scan_parser = subparsers.add_parser("scan",
        help="Scan agent traces for security issues")
    scan_parser.add_argument("--trace", "-t", default=None,
                             help="Scan a specific trace ID (default: all recent)")
    scan_parser.add_argument("--report", "-r", action="store_true",
                             help="Generate a security report file")
    scan_parser.add_argument("--format", choices=["csv", "html"], default="csv",
                             help="Report format (default: csv)")
    scan_parser.add_argument("--output", "-o", default=None,
                             help="Output file path")
    scan_parser.set_defaults(func=CMD_MAP["scan"])

    # agent
    agent_parser = subparsers.add_parser("agent",
        help="Manage AI agent identities for execution tracking and governance")
    agent_sub = agent_parser.add_subparsers(dest="agent_action", help="Agent actions")
    ac = agent_sub.add_parser("create", help="Register a new agent")
    ac.add_argument("--name", "-n", default="", help="Human-readable name for the agent")
    ac.add_argument("--description", "-d", default="", help="Description of what the agent does")
    ac.add_argument("--owner", default="", help="Who owns this agent (user ID)")
    ac.add_argument("--team", default=None, help="Team ID this agent belongs to")
    ac.add_argument("--persona", default="", help="Role description — who this agent is (e.g. 'Financial analyst')")
    ac.add_argument("--traits", default=None, help="Comma-separated personality traits (e.g. 'cautious,analytical')")
    ac.add_argument("--avatar", default="", help="Emoji or icon for this agent")
    ac.set_defaults(func=CMD_MAP["agent"])
    al = agent_sub.add_parser("list", help="List all registered agents")
    al.add_argument("--team", default=None, help="Filter by team ID")
    al.set_defaults(func=CMD_MAP["agent"])
    ag = agent_sub.add_parser("get", help="Get agent details")
    ag.add_argument("agent_id", help="Agent ID to look up")
    ag.set_defaults(func=CMD_MAP["agent"])
    au = agent_sub.add_parser("update", help="Update agent fields")
    au.add_argument("agent_id", help="Agent ID to update")
    au.add_argument("--name", default=None, help="New name")
    au.add_argument("--description", default=None, help="New description")
    au.add_argument("--owner", default=None, help="New owner")
    au.add_argument("--team", default=None, help="New team ID")
    au.add_argument("--status", default=None, help="New status (active/paused/revoked)")
    au.add_argument("--capability", action="append", default=None, help="Grant capability (repeatable)")
    au.add_argument("--policy", action="append", default=None, help="Assign policy (repeatable)")
    au.add_argument("--persona", default=None, help="Role description (e.g. 'Financial analyst')")
    au.add_argument("--traits", default=None, help="Comma-separated traits. Prefix + to add, - to remove (e.g. '+cautious,-aggressive')")
    au.add_argument("--avatar", default=None, help="Emoji or icon")
    au.set_defaults(func=CMD_MAP["agent"])
    ad = agent_sub.add_parser("delete", help="Delete an agent")
    ad.add_argument("agent_id", help="Agent ID to delete")
    ad.set_defaults(func=CMD_MAP["agent"])
    # Blueprint Phase 2: agent status + capability management
    ast = agent_sub.add_parser("status", help="Show agent execution statistics")
    ast.add_argument("agent_id", help="Agent ID")
    ast.set_defaults(func=CMD_MAP["agent"])
    acap = agent_sub.add_parser("capability", help="Manage agent capabilities")
    acap_sub = acap.add_subparsers(dest="capability_action")
    acap_grant = acap_sub.add_parser("grant", help="Grant a capability to an agent")
    acap_grant.add_argument("--agent", required=True, help="Agent ID")
    acap_grant.add_argument("--capability", required=True, help="Capability name")
    acap_grant.set_defaults(func=CMD_MAP["agent"])
    acap_revoke = acap_sub.add_parser("revoke", help="Revoke a capability")
    acap_revoke.add_argument("--agent", required=True, help="Agent ID")
    acap_revoke.add_argument("--capability", required=True, help="Capability name")
    acap_revoke.set_defaults(func=CMD_MAP["agent"])
    acap_list = acap_sub.add_parser("list", help="List agent capabilities")
    acap_list.add_argument("agent_id", help="Agent ID")
    acap_list.set_defaults(func=CMD_MAP["agent"])
    # Team subcommands
    atc = agent_sub.add_parser("team", help="Team management")
    atc_sub = atc.add_subparsers(dest="team_action")
    atc_create = atc_sub.add_parser("create", help="Create a new team")
    atc_create.add_argument("--name", "-n", required=True, help="Team name")
    atc_create.add_argument("--description", "-d", default="", help="Team description")
    atc_create.add_argument("--owner", default="", help="Team owner")
    atc_create.set_defaults(func=CMD_MAP["agent"])
    atc_list = atc_sub.add_parser("list", help="List all teams")
    atc_list.set_defaults(func=CMD_MAP["agent"])
    atc_get = atc_sub.add_parser("get", help="Get team details")
    atc_get.add_argument("team_id", help="Team ID")
    atc_get.set_defaults(func=CMD_MAP["agent"])
    atc_add = atc_sub.add_parser("add", help="Add agent to team")
    atc_add.add_argument("--team", required=True, help="Team ID")
    atc_add.add_argument("--agent", required=True, help="Agent ID")
    atc_add.set_defaults(func=CMD_MAP["agent"])

    # context
    ctx_parser = subparsers.add_parser("context",
        help="Manage execution contexts — the environment an Agent runs in")
    ctx_sub = ctx_parser.add_subparsers(dest="context_action", help="Context actions")
    ctx_create = ctx_sub.add_parser("create", help="Create a new execution context")
    ctx_create.add_argument("--name", required=True, help="Context name")
    ctx_create.add_argument("--goal", default="", help="Goal description")
    ctx_create.add_argument("--constraint", action="append", default=None,
                            help="Constraint (repeatable, e.g. 'SEC sources only')")
    ctx_create.add_argument("--scope", default="", help="Task scope (research, trading, etc.)")
    ctx_create.add_argument("--parent", default=None, help="Parent context ID")
    ctx_create.add_argument("--created-by", default="", help="Who created this context")
    ctx_create.set_defaults(func=CMD_MAP["context"])
    ctx_list = ctx_sub.add_parser("list", help="List contexts")
    ctx_list.add_argument("--created-by", default=None, help="Filter by creator")
    ctx_list.add_argument("--agent", default=None, help="Filter by assigned agent")
    ctx_list.set_defaults(func=CMD_MAP["context"])
    ctx_get = ctx_sub.add_parser("get", help="Get context details")
    ctx_get.add_argument("context_id", help="Context ID")
    ctx_get.set_defaults(func=CMD_MAP["context"])
    ctx_inspect = ctx_sub.add_parser("inspect", help="Inspect a context and its assignments")
    ctx_inspect.add_argument("context_id", help="Context ID")
    ctx_inspect.set_defaults(func=CMD_MAP["context"])
    ctx_history = ctx_sub.add_parser("history", help="Show version history for a context")
    ctx_history.add_argument("context_id", help="Context ID")
    ctx_history.set_defaults(func=CMD_MAP["context"])
    ctx_assign = ctx_sub.add_parser("assign", help="Assign an agent to a context")
    ctx_assign.add_argument("context_id", help="Context ID")
    ctx_assign.add_argument("--agent", required=True, help="Agent ID to assign")
    ctx_assign.set_defaults(func=CMD_MAP["context"])
    ctx_agents = ctx_sub.add_parser("agents", help="List agents assigned to a context")
    ctx_agents.add_argument("context_id", help="Context ID")
    ctx_agents.set_defaults(func=CMD_MAP["context"])
    ctx_delete = ctx_sub.add_parser("delete", help="Delete a context")
    ctx_delete.add_argument("context_id", help="Context ID")
    ctx_delete.set_defaults(func=CMD_MAP["context"])
    ctx_diff = ctx_sub.add_parser("diff", help="Diff two contexts or two versions of the same context")
    ctx_diff.add_argument("context_id", help="Primary context ID")
    ctx_diff.add_argument("context_id_b", nargs="?", default=None,
                          help="Secondary context ID (omit to compare current vs previous version)")
    ctx_diff.set_defaults(func=CMD_MAP["context"])

    # evidence
    evi_parser = subparsers.add_parser("evidence",
        help="Manage verification evidence for Agent outputs")
    evi_sub = evi_parser.add_subparsers(dest="evidence_action", help="Evidence actions")
    evi_add = evi_sub.add_parser("add", help="Add evidence to an execution")
    evi_add.add_argument("--execution", required=True, help="Execution ID (trace_id)")
    evi_add.add_argument("--claim", required=True, help="The claim being made")
    evi_add.add_argument("--source-type", default="model_inference",
                         help="Source type: data/calculation/model_inference/external_api")
    evi_add.add_argument("--source-ref", default="", help="Source reference (URL, doc, etc.)")
    evi_add.add_argument("--data-ref", default="", help="Raw data reference")
    evi_add.add_argument("--confidence", type=float, default=0.0, help="Confidence 0.0-1.0")
    evi_add.set_defaults(func=CMD_MAP["evidence"])
    evi_list = evi_sub.add_parser("list", help="List evidence for an execution")
    evi_list.add_argument("execution_id", help="Execution ID")
    evi_list.set_defaults(func=CMD_MAP["evidence"])
    evi_verify = evi_sub.add_parser("verify", help="Manually verify an evidence record")
    evi_verify.add_argument("evidence_id", help="Evidence ID")
    evi_verify.add_argument("--by", default="user", help="Who verified this")
    evi_verify.set_defaults(func=CMD_MAP["evidence"])
    evi_chain = evi_sub.add_parser("chain", help="Show evidence chain for an execution")
    evi_chain.add_argument("execution_id", help="Execution ID")
    evi_chain.set_defaults(func=CMD_MAP["evidence"])
    evi_unverified = evi_sub.add_parser("unverified", help="List unverified evidence")
    evi_unverified.add_argument("--limit", type=int, default=50, help="Max results")
    evi_unverified.set_defaults(func=CMD_MAP["evidence"])

    # experience
    exp_parser = subparsers.add_parser("experience",
        help="Manage agent learned experiences — patterns, strategies, and feedback")
    exp_sub = exp_parser.add_subparsers(dest="experience_action", help="Experience actions")

    # experience record
    exp_record = exp_sub.add_parser("record", help="Record a new experience entry")
    exp_record.add_argument("--agent", required=True, help="Agent ID")
    exp_record.add_argument("--type", required=True, dest="type",
                            choices=["failure_pattern", "success_strategy", "tool_preference",
                                     "model_performance", "data_source_reliability",
                                     "environment_constraint", "user_feedback"],
                            help="Experience type")
    exp_record.add_argument("--observation", required=True, help="What was observed")
    exp_record.add_argument("--recommendation", default=None, help="What should be done differently")
    exp_record.add_argument("--execution", action="append", default=None,
                            help="Related execution/trace IDs (repeatable)")
    exp_record.add_argument("--confidence", type=float, default=None, help="Confidence 0.0-1.0")
    exp_record.add_argument("--domain", default=None, help="Domain (e.g. trading, research)")
    exp_record.add_argument("--tag", action="append", default=None,
                            help="Tags (repeatable)")
    exp_record.set_defaults(func=CMD_MAP["experience"])

    # experience list
    exp_list = exp_sub.add_parser("list", help="List experiences with optional filters")
    exp_list.add_argument("--agent", default=None, help="Filter by agent ID")
    exp_list.add_argument("--type", default=None, dest="type",
                          choices=["failure_pattern", "success_strategy", "tool_preference",
                                   "model_performance", "data_source_reliability",
                                   "environment_constraint", "user_feedback"],
                          help="Filter by experience type")
    exp_list.add_argument("--domain", default=None, help="Filter by domain")
    exp_list.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    exp_list.set_defaults(func=CMD_MAP["experience"])

    # experience get
    exp_get = exp_sub.add_parser("get", help="Show full detail for a single experience entry")
    exp_get.add_argument("experience_id", help="Experience ID")
    exp_get.set_defaults(func=CMD_MAP["experience"])

    # experience extract
    exp_extract = exp_sub.add_parser("extract", help="Extract experiences for an agent (or all)")
    exp_extract.add_argument("--agent", default=None, help="Agent ID (omit to extract all)")
    exp_extract.set_defaults(func=CMD_MAP["experience"])

    # experience query
    exp_query = exp_sub.add_parser("query", help="Keyword-match query across experiences")
    exp_query.add_argument("goal", help="Goal text or keywords to search for")
    exp_query.add_argument("--agent", default=None, help="Filter by agent ID")
    exp_query.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    exp_query.set_defaults(func=CMD_MAP["experience"])

    # experience validate
    exp_validate = exp_sub.add_parser("validate", help="Mark an experience as validated and/or successful")
    exp_validate.add_argument("experience_id", help="Experience ID")
    exp_validate.add_argument("--valid", action="store_true",
                              help="Mark experience as validated")
    exp_validate.add_argument("--success", action="store_true",
                              help="Mark experience as successful")
    exp_validate.set_defaults(func=CMD_MAP["experience"])

    # registry — extended
    reg_parser_2 = subparsers.add_parser("registry",
        help="Manage the capability registry and marketplace")
    reg_sub_2 = reg_parser_2.add_subparsers(dest="action", help="Registry actions")
    reg_list_2 = reg_sub_2.add_parser("list", help="List all registered capabilities")
    reg_list_2.set_defaults(action="list", func=CMD_MAP["registry"])
    reg_get_2 = reg_sub_2.add_parser("get", help="Get capability details")
    reg_get_2.add_argument("name", help="Capability name")
    reg_get_2.add_argument("--version", "-v", default=None, help="Version (default: latest)")
    reg_get_2.set_defaults(func=CMD_MAP["registry"])
    reg_register_2 = reg_sub_2.add_parser("register", help="Register a capability from a Manifest")
    reg_register_2.add_argument("manifest_path", help="Path to Capability Manifest YAML file")
    reg_register_2.set_defaults(func=CMD_MAP["registry"])
    reg_unregister_2 = reg_sub_2.add_parser("unregister", help="Unregister a capability")
    reg_unregister_2.add_argument("name", help="Capability name")
    reg_unregister_2.add_argument("--version", "-v", default=None, help="Version (omit for all)")
    reg_unregister_2.set_defaults(func=CMD_MAP["registry"])
    reg_export_2 = reg_sub_2.add_parser("export", help="Export registry snapshot to JSON")
    reg_export_2.add_argument("output_path", help="Output JSON file path")
    reg_export_2.set_defaults(func=CMD_MAP["registry"])
    reg_search_2 = reg_sub_2.add_parser("search", help="Semantic search for capabilities by text query")
    reg_search_2.add_argument("query", help="Free-text search query")
    reg_search_2.add_argument("--limit", "-l", type=int, default=10, help="Max results (default: 10)")
    reg_search_2.set_defaults(func=CMD_MAP["registry"])
    reg_publish = reg_sub_2.add_parser("publish", help="Publish a capability to the marketplace")
    reg_publish.add_argument("manifest_path", help="Path to Capability Manifest YAML file")
    reg_publish.add_argument("--visibility", default="public",
                             help="Visibility: public/team/private (default: public)")
    reg_publish.add_argument("--publisher", default="", help="Who is publishing")
    reg_publish.set_defaults(func=CMD_MAP["registry"])
    reg_discover = reg_sub_2.add_parser("discover", help="Discover published capabilities")
    reg_discover.add_argument("query", nargs="?", default="", help="Search query (empty = all)")
    reg_discover.add_argument("--limit", type=int, default=10, help="Max results")
    reg_discover.add_argument("--visibility", default=None, help="Filter by visibility")
    reg_discover.set_defaults(func=CMD_MAP["registry"])
    reg_show = reg_sub_2.add_parser("show", help="Show capability marketplace details")
    reg_show.add_argument("capability_id", help="Capability ID (name@version)")
    reg_show.set_defaults(func=CMD_MAP["registry"])
    reg_install = reg_sub_2.add_parser("install", help="Install a capability from the marketplace")
    reg_install.add_argument("capability_id", help="Capability ID (name@version)")
    reg_install.set_defaults(func=CMD_MAP["registry"])
    reg_rate = reg_sub_2.add_parser("rate", help="Rate a capability in the marketplace")
    reg_rate.add_argument("capability_id", help="Capability ID (name@version)")
    reg_rate.add_argument("--score", type=float, required=True, help="Rating score (0.0 - 5.0)")
    reg_rate.set_defaults(func=CMD_MAP["registry"])

    # db
    db_parser = subparsers.add_parser("db",
        help="Manage the unified intent.db database")
    db_sub = db_parser.add_subparsers(dest="action", help="Database actions")
    db_migrate = db_sub.add_parser("migrate",
        help="Migrate data from old per-store DBs into the unified intent.db")
    db_migrate.set_defaults(func=CMD_MAP["db"])

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
