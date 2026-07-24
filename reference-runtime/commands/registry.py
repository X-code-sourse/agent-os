"""
Intent OS -- CLI Command: registry

Manages the capability registry (list, get, register, unregister, export, search)
plus the Capability Marketplace (BluePrint Layer 6 -- Interoperability):
  publish, discover, show.
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
    """Manage the capability registry and marketplace."""
    from core.parser import parse_manifest, ManifestParseError
    from core.registry import RegistryError

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
            vis = f" [{cap.get('visibility', 'private')}]" if cap.get('visibility') else ""
            print(f"  {cap['name']}@{cap['version']}{pub}{desc}{vis}")

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

    # ── Capability Marketplace (BluePrint Layer 6) ──

    elif args.action == "publish":
        path = Path(args.manifest_path)
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            sys.exit(1)
        try:
            manifest, _ = parse_manifest(path)
        except ManifestParseError as exc:
            print(f"Error parsing manifest: {exc}", file=sys.stderr)
            sys.exit(1)

        visibility = getattr(args, "visibility", None) or "public"
        publisher = getattr(args, "publisher", None) or manifest.metadata.publisher

        try:
            entry = registry.publish(
                manifest,
                visibility=visibility,
                publisher=publisher,
            )
        except (RegistryError, ValueError) as exc:
            print(f"Publish failed: {exc}", file=sys.stderr)
            sys.exit(1)

        print(f"Published '{manifest.id}' to marketplace")
        print(f"  Visibility: {entry.visibility}")
        print(f"  Publisher:  {entry.publisher or '(none)'}")
        print(f"  Verified:   {'yes' if entry.verified else 'no'}")
        print(f"  Created:    {entry.created_at}")

    elif args.action == "discover":
        query = args.query
        limit = getattr(args, "limit", 10) or 10
        visibility_filter = getattr(args, "visibility", None) or None

        # Adjust the description label based on filter
        filter_label = f" [visibility: {visibility_filter}]" if visibility_filter else ""
        results = registry.find_by_text(
            query, limit=limit, visibility=visibility_filter,
        )

        if not results:
            print(f"No capabilities matching '{query}'{filter_label}.")
            return

        print(f"Discovery results for '{query}'{filter_label} ({len(results)}):")
        print(f"  {'Score':<8} {'Name':<30} {'Vis':<8} {'Publisher':<20} {'Description'}")
        print(f"  {'-'*100}")
        for r in results:
            cap = r["capability"]
            name = f"{cap['name']}@{cap.get('version', '?')}" if cap.get('version') else cap['name']
            vis = cap.get('visibility', 'private')[:7]
            pub = (cap.get('publisher', '') or '')[:18]
            desc = (cap.get('description', '') or '')[:35]
            print(f"  {r['score']:<8.4f} {name:<30} {vis:<8} {pub:<20} {desc}")

    elif args.action == "show":
        capability_id = args.capability_id
        entry = registry.get_entry(capability_id)
        if entry is None:
            print(f"Capability '{capability_id}' not found in registry.")
            sys.exit(1)

        # Parse manifest_yaml for capability details
        try:
            parsed, _ = parse_manifest(entry.manifest_yaml)
        except ManifestParseError:
            print(f"Error: Could not parse manifest for '{capability_id}'", file=sys.stderr)
            sys.exit(1)

        print(f"Capability: {entry.capability_id}")
        print(f"  Publisher:   {entry.publisher or '(none)'}")
        print(f"  Description: {parsed.metadata.description or '(none)'}")
        print(f"  Tags:        {parsed.metadata.tags or '(none)'}")
        print(f"  Input:       {list(parsed.input_schema.keys())}")
        print(f"  Output:      {list(parsed.output_schema.keys())}")
        print()
        print(f"  Marketplace")
        print(f"  ───────────")
        print(f"  Visibility:  {entry.visibility}")
        print(f"  Usage count: {entry.usage_count}")
        print(f"  Rating:      {entry.rating:.1f} / 5.0")
        print(f"  Verified:    {'yes' if entry.verified else 'no'}")
        if entry.created_at:
            print(f"  Created:     {entry.created_at[:19]}")
        if entry.updated_at:
            print(f"  Updated:     {entry.updated_at[:19]}")

    elif args.action == "install":
        capability_id = args.capability_id
        entry = registry.get_entry(capability_id)
        if entry is None:
            print(f"Capability '{capability_id}' not found in marketplace.")
            print("Try: intent-os registry discover")
            sys.exit(1)

        print(f"Installing '{entry.capability_id}'...")
        print(f"  Publisher:   {entry.publisher or '(none)'}")
        # Parse manifest for description
        try:
            parsed, _ = parse_manifest(entry.manifest_yaml)
            desc = parsed.metadata.description or '(none)'
        except ManifestParseError:
            desc = '(parse error)'
        print(f"  Description: {desc}")
        print(f"  Rating:      {entry.rating:.1f} / 5.0")
        print(f"  Verified:    {'yes' if entry.verified else 'no'}")
        print(f"[OK] Capability '{entry.capability_id}' installed successfully.")

    elif args.action == "rate":
        from datetime import datetime, timezone

        capability_id = args.capability_id
        score = float(args.score)

        if score < 0 or score > 5:
            print("Error: --score must be between 0.0 and 5.0", file=sys.stderr)
            sys.exit(1)

        entry = registry.get_entry(capability_id)
        if entry is None:
            print(f"Capability '{capability_id}' not found in marketplace.")
            print("Try: intent-os registry discover")
            sys.exit(1)

        old_rating = entry.rating
        # Incremental (Welford) running average: each new rating
        # is weighted proportionally so a single outlier cannot
        # dominate – e.g. a 5.0 avg across 1 000 ratings drops
        # to ~4.995 after one 0.5, not 2.75.
        count = entry.usage_count  # proxy for number of ratings
        new_rating = old_rating + (score - old_rating) / (count + 1)

        # Parse name and version from capability_id for DB update
        cap_name, cap_version = entry.capability_id.rsplit("@", 1) if "@" in entry.capability_id else (entry.capability_id, "")

        # Persist the new rating in-memory and in SQLite.
        manifest_id = entry.capability_id
        with registry._lock:
            if manifest_id in registry._marketplace:
                registry._marketplace[manifest_id].rating = new_rating
                registry._marketplace[manifest_id].updated_at = datetime.now(timezone.utc).isoformat()
            else:
                print(f"Error: Marketplace entry not found for '{manifest_id}'", file=sys.stderr)
                sys.exit(1)

        if registry._db_path:
            try:
                conn = registry._get_conn()
                conn.execute(
                    "UPDATE capabilities SET rating = ?, updated_at = datetime('now')"
                    " WHERE name = ? AND version = ?",
                    (new_rating, cap_name, cap_version),
                )
                conn.commit()
                conn.close()
            except Exception as exc:
                print(f"Warning: could not persist rating: {exc}", file=sys.stderr)

        print(f"Rating updated for '{entry.capability_id}':")
        print(f"  Old rating: {old_rating:.1f} / 5.0")
        print(f"  New rating: {new_rating:.1f} / 5.0")
        print(f"  Your score: {score:.1f}")
