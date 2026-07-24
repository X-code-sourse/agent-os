"""
Intent OS CLI — evidence command: execution evidence management.

Add, list, verify, and inspect evidence records attached to executions.
Evidence backs agent claims with auditable source information.

    intent-os evidence add --execution exec_abc --claim "market data loaded"
    intent-os evidence list exec_abc
    intent-os evidence verify evi_def456 --by "human-reviewer"
    intent-os evidence chain exec_abc
    intent-os evidence unverified
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from commands.helpers import get_event_store

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _get_evidence_store() -> Any:
    """Get or create the default persistent Evidence Store."""
    store_dir = Path.home() / ".intent-os"
    store_dir.mkdir(parents=True, exist_ok=True)
    db_path = store_dir / "evidence.db"
    from core.evidence_store import EvidenceStore
    return EvidenceStore(db_path=str(db_path))


# ── Helpers ──


def _confidence_bar(confidence: float, width: int = 20) -> str:
    """Render a visual confidence bar."""
    filled = int(max(0.0, min(1.0, confidence)) * width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    pct = f"{confidence:.0%}"
    return f"[{bar}] {pct:>6}"


def _format_evidence_row(ev: dict[str, Any]) -> str:
    """Format a single evidence record for display."""
    verified = "[V]" if ev.get("verified") else "[ ]"
    claim = ev.get("claim", "(no claim)").strip()
    if len(claim) > 60:
        claim = claim[:57] + "..."
    evidence_id = ev.get("evidence_id", "?")
    source_type = ev.get("source_type", "") or "-"
    confidence = ev.get("confidence", 0.0)

    parts = [
        f"  {verified} {evidence_id}",
        f"    Claim:      {claim}",
        f"    Source:     {source_type}",
        f"    Confidence: {_confidence_bar(confidence)}",
    ]
    if ev.get("verified_by"):
        parts.append(f"    Verified by: {ev['verified_by']} at {ev.get('verified_at', '?')}")
    if ev.get("source_ref"):
        parts.append(f"    Source ref: {ev['source_ref']}")
    if ev.get("raw_data_ref"):
        parts.append(f"    Data ref:   {ev['raw_data_ref']}")
    return "\n".join(parts)


def _resolve_execution_id(store: Any, execution_id: str) -> str:
    """Resolve 'latest' to the most recent execution ID."""
    if execution_id == "latest":
        all_ids = store.get_all_trace_ids()
        if not all_ids:
            print("No executions found. Run a capability first:")
            print()
            print("    intent-os run translate -p text=hello -p target_lang=zh")
            print()
            sys.exit(0)
        return all_ids[0]
    return execution_id


# ── Subcommand handlers ──


def _cmd_evidence_add(args: Any) -> None:
    """Add an evidence record to an execution."""
    event_store = get_event_store()
    evidence_store = _get_evidence_store()

    execution_id = getattr(args, "execution", None)
    claim = getattr(args, "claim", None)

    if not execution_id:
        print("Error: --execution <execution_id> is required", file=sys.stderr)
        sys.exit(1)
    if not claim:
        print("Error: --claim <claim_text> is required", file=sys.stderr)
        sys.exit(1)

    # Verify the execution exists
    record = event_store.get_record(execution_id)
    if not record:
        print(f"Error: Execution '{execution_id}' not found.", file=sys.stderr)
        print()
        print("  Available executions:")
        all_ids = event_store.get_all_trace_ids()
        for tid in all_ids[:10]:
            print(f"    {tid}")
        if len(all_ids) > 10:
            print(f"    ... and {len(all_ids) - 10} more")
        sys.exit(1)

    confidence = getattr(args, "confidence", None)
    if confidence is None:
        confidence = 0.5
    else:
        confidence = float(confidence)

    evidence = {
        "evidence_id": "evi_" + uuid.uuid4().hex[:12],
        "execution_id": execution_id,
        "claim": claim,
        "source_type": getattr(args, "source_type", None) or "",
        "source_ref": getattr(args, "source_ref", None) or "",
        "raw_data_ref": getattr(args, "data_ref", None) or "",
        "confidence": confidence,
        "verified": False,
        "verified_by": None,
        "verified_at": None,
    }

    evidence_store.save_evidence(evidence)
    print(f"[OK] Evidence '{evidence['evidence_id']}' added to execution '{execution_id}'")
    print()
    print(_format_evidence_row(evidence))


def _cmd_evidence_list(args: Any) -> None:
    """List evidence for an execution."""
    event_store = get_event_store()
    evidence_store = _get_evidence_store()

    execution_id = _resolve_execution_id(event_store, args.execution_id)

    records = evidence_store.get_evidence_by_execution(execution_id)
    if not records:
        print(f"No evidence found for execution '{execution_id}'.")
        print()
        print("  Add evidence with:")
        print(f"    intent-os evidence add --execution {execution_id} --claim \"your claim\"")
        print()
        return

    verified_count = sum(1 for r in records if r.get("verified"))
    print()
    print(f"  Evidence for execution '{execution_id}'")
    print(f"  Total: {len(records)}  |  Verified: {verified_count}  |  Unverified: {len(records) - verified_count}")
    print()
    for ev in records:
        print(_format_evidence_row(ev))
        print()


def _cmd_evidence_verify(args: Any) -> None:
    """Manually verify an evidence record."""
    evidence_store = _get_evidence_store()

    evidence_id = args.evidence_id
    verified_by = getattr(args, "by", None) or "manual-verification"

    existing = evidence_store.get_evidence_by_id(evidence_id)
    if existing is None:
        print(f"Error: Evidence '{evidence_id}' not found.", file=sys.stderr)
        sys.exit(1)

    if existing.get("verified"):
        print(f"Evidence '{evidence_id}' is already verified by '{existing.get('verified_by', '?')}'.")
        return

    updated = evidence_store.verify_evidence(evidence_id, verified_by)
    if updated:
        print(f"[OK] Evidence '{evidence_id}' verified by '{verified_by}'")
    else:
        print(f"Error: Could not verify evidence '{evidence_id}'.", file=sys.stderr)
        sys.exit(1)


def _cmd_evidence_chain(args: Any) -> None:
    """Show the full evidence chain for an execution."""
    event_store = get_event_store()
    evidence_store = _get_evidence_store()

    execution_id = _resolve_execution_id(event_store, args.execution_id)

    chain = evidence_store.get_evidence_chain(execution_id)
    if not chain:
        print(f"No evidence found for execution '{execution_id}'.")
        print()
        print("  Add evidence with:")
        print(f"    intent-os evidence add --execution {execution_id} --claim \"your claim\"")
        print()
        return

    verified_count = sum(1 for r in chain if r.get("verified"))
    print()
    print(f"  Evidence Chain for execution '{execution_id}'")
    print(f"  Total: {len(chain)}  |  Verified: {verified_count}  |  Unverified: {len(chain) - verified_count}")
    print()

    for i, ev in enumerate(chain, 1):
        deps = []
        src = ev.get("source_ref", "")
        if src and src.startswith("evi_"):
            deps.append(f"depends on: {src}")
        dep_str = f"  ({'; '.join(deps)})" if deps else ""

        print(f"  [{i}/{len(chain)}]{dep_str}")
        print(_format_evidence_row(ev))
        print()


def _cmd_evidence_unverified(args: Any) -> None:
    """List all unverified evidence across all executions."""
    evidence_store = _get_evidence_store()

    val = getattr(args, "limit", None)
    limit = int(val) if val is not None else 50

    records = evidence_store.get_unverified_evidence(limit=limit)
    if not records:
        print("No unverified evidence found.")
        print()
        print("  All evidence records are verified.")
        return

    print()
    print(f"  Unverified Evidence ({min(len(records), limit)} shown)")
    print()
    for ev in records:
        print(_format_evidence_row(ev))
        print(f"    Execution:  {ev.get('execution_id', '?')}")
        print()


# ── Main entry point ──


def cmd_evidence(args: Any) -> None:
    """Manage execution evidence records."""
    action = getattr(args, "evidence_action", "list")

    if action == "add":
        _cmd_evidence_add(args)
    elif action == "list":
        _cmd_evidence_list(args)
    elif action == "verify":
        _cmd_evidence_verify(args)
    elif action == "chain":
        _cmd_evidence_chain(args)
    elif action == "unverified":
        _cmd_evidence_unverified(args)
    else:
        print(f"Error: Unknown evidence action '{action}'", file=sys.stderr)
        print("  Available actions: add, list, verify, chain, unverified", file=sys.stderr)
        sys.exit(1)
