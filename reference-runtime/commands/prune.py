"""Intent OS CLI — event prune: clean up old execution data.

Usage:
    intent-os event prune                          # dry-run (default 90 days)
    intent-os event prune --older-than 30          # target 30 days
    intent-os event prune --older-than 60 --force  # actually delete
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from commands.helpers import get_event_store


def _fmt_size(n_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} TB"


def cmd_prune(args: Any) -> None:
    """Prune old events and execution records from the Event Store."""
    store = get_event_store()
    days = getattr(args, "older_than", 90)
    force = getattr(args, "force", False)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Count
    event_count = store.count_events_before(cutoff)
    record_count = store.count_records_before(cutoff)
    store_size = store.get_store_size_bytes()

    print()
    print("  ================================================")
    print("    Intent OS — Event Store Prune")
    print("  ================================================")
    print()
    print(f"  Cutoff:          older than {days} days  ({cutoff[:10]})")
    print(f"  Events matched:  {event_count}")
    print(f"  Records matched: {record_count}")
    print(f"  Store size:      {_fmt_size(store_size)}")
    print()

    if event_count == 0 and record_count == 0:
        print("  Nothing to prune — store is clean.")
        print()
        return

    if not force:
        print("  This is a DRY RUN.  To actually delete, add --force")
        print()
        print(f"    intent-os event prune --older-than {days} --force")
        print()
        return

    # Ask for confirmation when interactive
    if sys.stdin.isatty():
        print(f"  This will permanently delete {event_count} events "
              f"and {record_count} records.")
        print()
        try:
            answer = input("  Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.")
            sys.exit(0)
        if answer not in ("y", "yes"):
            print("  Aborted.")
            sys.exit(0)
        print()

    # Delete
    deleted_events = store.delete_events_before(cutoff) if event_count > 0 else 0
    deleted_records = store.delete_records_before(cutoff) if record_count > 0 else 0

    new_size = store.get_store_size_bytes()
    reclaimed = max(0, store_size - new_size)

    print(f"  Pruned: {deleted_events} events, {deleted_records} records")
    print(f"  Reclaimed: {_fmt_size(reclaimed)}")
    print(f"  New size: {_fmt_size(new_size)}")
    print()
