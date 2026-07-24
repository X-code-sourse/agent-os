"""
Intent OS — CLI Command: mcp-server

Starts or manages the Intent OS MCP Server.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def cmd_mcp_server(args: Any) -> None:
    """Start or manage the Intent OS MCP Server."""
    from mcp_server import MCPServer

    if args.mcp_action == "start":
        agent_id = getattr(args, "agent", None)
        server = MCPServer(
            host=args.host,
            port=args.port,
            adapter=args.adapter,
            agent_id=agent_id,
        )
        print(f"[OK] Starting Intent OS MCP Server on {args.host}:{args.port}")
        print(f"  SSE: http://{args.host}:{args.port}/sse")
        print(f"  Messages: POST http://{args.host}:{args.port}/messages")
        print(f"  Adapter: {args.adapter}")
        if agent_id:
            print(f"  Agent:     {agent_id}")
        print("  Press Ctrl+C to stop.")
        try:
            server.run()
        except KeyboardInterrupt:
            print("\nStopped.")
    elif args.mcp_action == "status":
        server = MCPServer(
            host=getattr(args, 'host', '127.0.0.1'),
            port=args.port,
            adapter=args.adapter,
        )
        info = server.status()
        print(f"Intent OS MCP Server")
        print(f"  Host: {info['host']}")
        print(f"  Port: {info['port']}")
        print(f"  Transport: {info['transport']}")
        print(f"  SSE endpoint: http://{info['host']}:{info['port']}{info['sse_path']}")
        print(f"  Default adapter: {info['default_adapter']}")
        print(f"  Capabilities registered: {info['capability_count']}")
        for cap in info['capabilities']:
            print(f"    - {cap['name']}: {cap['description']}")
