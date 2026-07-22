"""
Intent OS — CLI Command: registry

Manages the capability registry (list, get, register, unregister, export).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from commands.helpers import get_registry_store

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def cmd_registry(args: Any) -> None:
    """Manage the capability registry."""
    from core.parser import parse_manifest, ManifestParseError
    _, registry = get_registry_store()

    if args.action == "list":
        caps = registry.list_capabilities()
        if not caps:
            print("No capabilities registered.")
            return
        print(f"Registered capabilities ({len(caps)}):")
        for cap in caps:
            pub = f" ({cap['publisher'] or 'unknown'})" if cap.get('publisher') else ""
            desc = f" - {cap['description'][:60]}" if cap.get('description') else ""
            print(f"  {cap['name']}@{cap['version']}{pub}{desc}")

    elif args.action == "get":
        cap = registry.get(args.name, args.version)
        if cap is None:
            print(f"Capability '{args.name}' not found.")
            sys.exit(1)
        print(f"Name: {cap.name}@{cap.version}")
        print(f"Publisher: {cap.metadata.publisher or '(none)'}")
        print(f"Description: {cap.metadata.description or '(none)'}")
        print(f"Tags: {cap.metadata.tags or '(none)'}")
        print(f"Input fields: {list(cap.input_schema.keys())}")
        print(f"Output fields: {list(cap.output_schema.keys())}")

    elif args.action == "register":
        path = Path(args.manifest_path)
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            sys.exit(1)
        try:
            manifest, _ = parse_manifest(path)
        except ManifestParseError as exc:
            print(f"Error parsing manifest: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            registry.register(manifest)
            print(f"[OK] Registered '{manifest.id}'")
        except Exception as exc:
            print(f"Registration failed: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.action == "unregister":
        try:
            registry.unregister(args.name, args.version)
            ver_str = f"@{args.version}" if args.version else " (all versions)"
            print(f"[OK] Unregistered '{args.name}{ver_str}'")
        except Exception as exc:
            print(f"Unregister failed: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.action == "export":
        output = Path(args.output_path)
        try:
            result = registry.save_snapshot(str(output))
            print(f"[OK] Snapshot exported to {result}")
        except Exception as exc:
            print(f"Export failed: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.action == "search":
        query = args.query
        results = registry.find_by_text(query, limit=args.limit or 10)

        if not results:
            print(f"No capabilities matching '{query}'.")
            return

        print(f"Search results for '{query}' ({len(results)}):")
        print(f"  {'Score':<8} {'Name':<35} {'Description':<50}")
        print(f"  {'-'*93}")
        for r in results:
            cap = r["capability"]
            name = f"{cap['name']}@{cap.get('version', '?')}" if cap.get('version') else cap['name']
            desc = (cap.get('description', '') or '')[:48]
            print(f"  {r['score']:<8.4f} {name:<35} {desc:<50}")
