"""Intent OS CLI — proxy command: Agent Hook proxy server."""
from __future__ import annotations

import sys
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
    else:
        print(f"Unknown proxy action: {action}", file=sys.stderr)
        sys.exit(1)


def _cmd_start(args: Any) -> None:
    """Start the proxy server."""
    from proxy.server import start_proxy

    port = getattr(args, "port", 8377)
    host = getattr(args, "host", "127.0.0.1")

    print()
    print("  ================================================")
    print("    Intent OS Agent Hook Proxy")
    print("  ================================================")
    print()
    print(f"  Proxy listening on http://{host}:{port}")
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
        server = start_proxy(port=port, host=host)
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
