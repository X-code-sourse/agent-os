"""
Intent OS — CLI Command: evolution

Evolution Loop (SPEC-0003, Algorithm 5): analyze, suggest, auto-apply,
and manage optimizations via the EvolutionLoop engine.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from commands.helpers import get_event_store

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def cmd_evolution(args: Any) -> None:
    """Manage the Evolution Loop: run, status, queue, approve, reject."""
    from core.analytics import AnalyticsEngine
    from core.evolution import EvolutionLoop

    store = get_event_store()
    analytics = AnalyticsEngine(store)
    loop = EvolutionLoop(store, analytics)

    if args.action == "run":
        _cmd_run(loop)

    elif args.action == "status":
        _cmd_status(loop)

    elif args.action == "queue":
        _cmd_queue(loop)

    elif args.action == "approve":
        _cmd_approve(loop, args.suggestion_id)

    elif args.action == "reject":
        _cmd_reject(loop, args.suggestion_id)


def _cmd_run(loop: EvolutionLoop) -> None:
    """Run one iteration of the Evolution Loop."""
    print("Evolution Loop — iterate")
    print("  Loading EventStore and AnalyticsEngine ...")
    print("  Generating optimization suggestions ...")

    result = loop.iterate()

    applied = result["applied_count"]
    queued = result["queued_count"]
    total = result["total"]

    print()
    if total == 0:
        print("  [i] No optimization suggestions generated.")
        print("      Run more capabilities across different adapters to")
        print("      generate data the Evolution Loop can analyze.")
        print()
        print("      Example:")
        print("        intent-os run examples/text_summarize.yaml --adapter ollama")
        print("        intent-os run examples/text_summarize.yaml --adapter openai")
        print()
        return

    print(f"  Suggestions generated: {total}")
    print(f"  Auto-applied:          {applied}")
    print(f"  Queued for review:     {queued}")
    print()

    if applied:
        print("  Auto-applied suggestions:")
        for s in result["applied"]:
            print(f"    [{s.get('type','?')}] {s.get('suggestion','')[:80]}")

    if queued:
        print()
        print(f"  {queued} suggestion(s) queued for review.")
        print("  Review with: intent-os evolution queue")
        print("  Approve:     intent-os evolution approve <id>")
        print("  Reject:      intent-os evolution reject <id>")


def _cmd_status(loop: EvolutionLoop) -> None:
    """Show the number of pending suggestions."""
    count = loop.get_pending_count()
    if count == 0:
        print("No pending evolution suggestions.")
        print()
        print("  [i] Generate suggestions by running the Evolution Loop:")
        print("      intent-os evolution run")
        print()
        return

    print(f"Pending suggestions: {count}")
    print()
    print("  Review with: intent-os evolution queue")


def _cmd_queue(loop: EvolutionLoop) -> None:
    """List all suggestions awaiting human review."""
    suggestions = loop.get_pending_suggestions()

    if not suggestions:
        print("No pending evolution suggestions.")
        print()
        print("  [i] Generate suggestions by running the Evolution Loop:")
        print("      intent-os evolution run")
        print()
        return

    print(f"Pending Suggestions ({len(suggestions)}):")
    print()
    for s in suggestions:
        sid = s.get("id", "")
        stype = s.get("type", "?")
        summary = s.get("suggestion", "")
        impact = s.get("expected_impact", "")
        confidence = s.get("confidence", "?")
        created = s.get("created_at", "")
        print(f"  [{sid}] {stype} ({confidence})")
        print(f"         {summary[:90]}")
        print(f"         Impact: {impact[:80]}")
        print(f"         Created: {created}")
        print()

    print("  Approve:  intent-os evolution approve <id>")
    print("  Reject:   intent-os evolution reject <id>")


def _cmd_approve(loop: EvolutionLoop, suggestion_id: int) -> None:
    """Approve a pending suggestion by its database ID."""
    ok = loop.approve_suggestion(suggestion_id)
    if ok:
        print(f"[OK] Suggestion #{suggestion_id} approved.")
    else:
        print(
            f"Error: Suggestion #{suggestion_id} not found or already resolved.",
            file=sys.stderr,
        )
        sys.exit(1)


def _cmd_reject(loop: EvolutionLoop, suggestion_id: int) -> None:
    """Reject a pending suggestion by its database ID."""
    ok = loop.reject_suggestion(suggestion_id)
    if ok:
        print(f"[OK] Suggestion #{suggestion_id} rejected.")
    else:
        print(
            f"Error: Suggestion #{suggestion_id} not found or already resolved.",
            file=sys.stderr,
        )
        sys.exit(1)
