"""Intent OS CLI — proxy command: Agent Hook proxy server."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Any


def cmd_proxy(args: Any) -> None:
    """Start or manage the Agent Hook proxy server.

    The proxy intercepts OpenAI and Anthropic API calls from AI coding
    agents (Claude Code, Cursor, Copilot, etc.) and records every call
    to the Intent OS Event Store for later inspection.
    """
    action = args.proxy_action

    if action == "start":
        _cmd_start(args)
    elif action == "status":
        _cmd_status(args)
    elif action == "doctor":
        _cmd_doctor(args)
    else:
        print(f"Unknown proxy action: {action}", file=sys.stderr)
        sys.exit(1)


def _cmd_start(args: Any) -> None:
    """Start the proxy server."""
    from proxy.server import start_proxy

    port = getattr(args, "port", 8377)
    host = getattr(args, "host", "127.0.0.1")
    guard_enabled = getattr(args, "guard", False)
    agent_id = getattr(args, "agent", None)

    print()
    print("  ================================================")
    print("    Intent OS Agent Hook Proxy")
    print("  ================================================")
    print()
    print(f"  Proxy listening on http://{host}:{port}")
    if guard_enabled:
        print(f"  Tool Call Guard: ENABLED (inspect and classify tool call safety)")
    if agent_id:
        print(f"  Agent:         {agent_id}")
    print()
    print("  Connect your AI agent:")
    print()
    print(f"    export OPENAI_BASE_URL=http://{host}:{port}")
    print(f"    export ANTHROPIC_BASE_URL=http://{host}:{port}")
    print()
    print("  Then restart your agent. All executions will be recorded.")
    print()
    print("  Check your agent's health with:  intent-os doctor")
    print()

    try:
        server = start_proxy(port=port, host=host, use_guard=guard_enabled, agent_id=agent_id)
        server.serve_forever()
    except PermissionError:
        print(f"  Error: Permission denied for port {port}.", file=sys.stderr)
        print(f"  Try a higher port: intent-os proxy start --port 8377", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _cmd_status(args: Any) -> None:
    """Check if the proxy server is running."""
    import socket

    port = getattr(args, "port", 8377)
    host = getattr(args, "host", "127.0.0.1")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        if result == 0:
            print(f"  Agent Hook Proxy is RUNNING on http://{host}:{port}")
            print()
            print("  To view captured traces:")
            print("    intent-os inspect latest")
        else:
            print(f"  Agent Hook Proxy is NOT running on http://{host}:{port}")
            print()
            print("  To start:")
            print(f"    intent-os proxy start --port {port}")
    finally:
        sock.close()


def _cmd_doctor(args: Any) -> None:
    """Run a health check on the proxy and its captured data.

    Reports:
    - Whether the proxy is currently running
    - Recent traffic stats (last 24h calls / success / failure)
    - Event Store size and total events
    - Per-agent breakdown of captured calls
    - Top models by call count
    """
    import socket

    from commands.helpers import get_event_store

    port = getattr(args, "port", 8377)
    host = getattr(args, "host", "127.0.0.1")

    print()
    print("  ================================================")
    print("    Intent OS — Proxy Doctor")
    print("  ================================================")
    print()

    # ── Check 1: Is the proxy running? ──
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        running = result == 0
    finally:
        sock.close()

    if running:
        print(f"  [OK] Proxy is RUNNING on http://{host}:{port}")
    else:
        print(f"  [!!] Proxy is NOT running on http://{host}:{port}")
        print(f"        Start it with:  intent-os proxy start --port {port}")
    print()

    # ── Check 2: Event Store stats ──
    store = get_event_store()
    stats = store.get_store_stats()
    event_count = stats["event_count"]
    record_count = stats["record_count"]
    size_bytes = stats["size_bytes"]

    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            size_str = f"{size_bytes:.1f} {unit}"
            break
        size_bytes /= 1024
    else:
        size_str = f"{size_bytes:.1f} TB"

    print(f"  Event Store:  {event_count} events, {record_count} records, {size_str}")
    if event_count == 0:
        print("                (empty — no agent calls captured yet)")
    print()

    # ── Check 3: Recent traffic (last 24h) ──
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    traffic = store.get_recent_traffic(since)

    print(f"  Last 24 hours: {traffic['total']} proxy calls "
          f"({traffic['success']} success, {traffic['failure']} failure)")
    if traffic["total"] > 0 and traffic["failure"] > 0:
        fail_pct = traffic["failure"] / max(traffic["total"], 1) * 100
        if fail_pct > 10:
            print(f"                 [!!] Error rate {fail_pct:.0f}% — consider running intent-os doctor")
    print()

    # ── Check 4: Agent breakdown ──
    agents = store.get_agent_summary()
    if agents:
        print("  Agents detected:")
        for a in agents:
            cost_str = f"${a['total_cost']:.4f}" if a["total_cost"] else "$0.00"
            print(f"    {a['agent']:20s}  {a['calls']:>4d} calls  "
                  f"{int(a['total_tokens'] or 0):>8d} tokens  {cost_str}")
    else:
        print("  Agents detected: (none — no proxy traffic yet)")
    print()

    # ── Check 5: Quick tips ──
    if event_count == 0:
        print("  Next steps:")
        print("    1. Start the proxy:  intent-os proxy start")
        print("    2. Register an agent: intent-os agent create --name \"My Agent\"")
        print("    3. Set env vars and use your AI agent")
        print("    4. Check back:        intent-os proxy doctor")
    elif traffic["total"] == 0:
        print("  Proxy is up but no traffic in the last 24h.")
        print()
        print("  Make sure your AI agent is configured to use the proxy.")
        print("  Set these environment variables before starting your agent:")
        print()
        print(f"    export OPENAI_BASE_URL=http://{host}:{port}")
        print(f"    export ANTHROPIC_BASE_URL=http://{host}:{port}")
        print()
        print("  On Windows (PowerShell):")
        print(f"    $env:OPENAI_BASE_URL=\"http://{host}:{port}\"")
        print(f"    $env:ANTHROPIC_BASE_URL=\"http://{host}:{port}\"")
        print()
        print("  Then restart your AI agent. Traffic will appear here.")
    else:
        print("  Quick links:")
        print("    intent-os inspect latest   — view the most recent trace")
        print("    intent-os cost             — see spending breakdown")
        print("    intent-os doctor           — diagnose your last agent run")
    print()
