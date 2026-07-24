"""Intent OS CLI — experience command: manage agent learned experiences.

Record, list, query, and validate agent experiences — patterns, strategies,
preferences, and feedback that agents accumulate across executions.

    intent-os experience record --agent <id> --type failure_pattern --observation "..."
    intent-os experience list --agent <id> --type success_strategy
    intent-os experience get <experience_id>
    intent-os experience extract --agent <id>
    intent-os experience query "goal text"
    intent-os experience validate <experience_id> --valid
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Experience type icons for display
# ---------------------------------------------------------------------------
_TYPE_ICONS: dict[str, str] = {
    "failure_pattern": "[-]",
    "success_strategy": "[+]",
    "tool_preference": "[=]",
    "model_performance": "[M]",
    "data_source_reliability": "[D]",
    "environment_constraint": "[E]",
    "user_feedback": "[U]",
}

_VALID_TYPES = frozenset(_TYPE_ICONS.keys())


# ---------------------------------------------------------------------------
# Lightweight JSON-file store (shared state lives in ~/.intent-os/experiences.json)
# ---------------------------------------------------------------------------
def _store_path() -> Path:
    base = Path(os.environ.get("INTENT_OS_HOME", Path.home() / ".intent-os"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "experiences.json"


def _load() -> list[dict[str, Any]]:
    sp = _store_path()
    if not sp.exists():
        return []
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(experiences: list[dict[str, Any]]) -> None:
    _store_path().write_text(
        json.dumps(experiences, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------
def cmd_experience(args: Any) -> None:
    """Dispatch on args.experience_action."""
    action = args.experience_action

    if action == "record":
        _cmd_record(args)
    elif action == "list":
        _cmd_list(args)
    elif action == "get":
        _cmd_get(args)
    elif action == "extract":
        _cmd_extract(args)
    elif action == "query":
        _cmd_query(args)
    elif action == "validate":
        _cmd_validate(args)
    else:
        print(f"Unknown experience action: {action}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------
def _cmd_record(args: Any) -> None:
    """Record a new experience entry."""
    agent = getattr(args, "agent", None)
    if not agent:
        print("Error: --agent is required", file=sys.stderr)
        sys.exit(1)

    exp_type = getattr(args, "type", None)
    if not exp_type or exp_type not in _VALID_TYPES:
        valid = ", ".join(sorted(_VALID_TYPES))
        print(f"Error: --type is required and must be one of: {valid}", file=sys.stderr)
        sys.exit(1)

    observation = getattr(args, "observation", None)
    if not observation:
        print("Error: --observation is required", file=sys.stderr)
        sys.exit(1)

    recommendation = getattr(args, "recommendation", "") or ""
    executions = getattr(args, "execution", None) or []
    # Handle single string (argparse might give a string)
    if isinstance(executions, str):
        executions = [executions]
    confidence = getattr(args, "confidence", None)
    domain = getattr(args, "domain", "") or ""
    tags = getattr(args, "tag", None) or []
    if isinstance(tags, str):
        tags = [tags]

    entry: dict[str, Any] = {
        "experience_id": f"exp_{uuid.uuid4().hex[:10]}",
        "agent_id": agent,
        "type": exp_type,
        "observation": observation,
        "recommendation": recommendation,
        "execution_ids": executions,
        "confidence": confidence,
        "domain": domain,
        "tags": tags,
        "validated": False,
        "successful": False,
        "recorded_at": _now(),
    }

    experiences = _load()
    experiences.append(entry)
    _save(experiences)

    icon = _TYPE_ICONS.get(exp_type, "?")
    print()
    print(f"  {icon} Experience recorded: {entry['experience_id']}")
    print(f"     Type:         {exp_type}")
    print(f"     Agent:        {agent}")
    print(f"     Observation:  {observation[:80]}{'...' if len(observation) > 80 else ''}")
    if recommendation:
        print(f"     Recommendation: {recommendation[:80]}{'...' if len(recommendation) > 80 else ''}")
    if executions:
        print(f"     Executions:   {', '.join(executions)}")
    if confidence is not None:
        print(f"     Confidence:   {confidence}")
    if domain:
        print(f"     Domain:       {domain}")
    if tags:
        print(f"     Tags:         {', '.join(tags)}")
    print()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
def _cmd_list(args: Any) -> None:
    """List experiences with optional filters."""
    agent = getattr(args, "agent", None)
    exp_type = getattr(args, "type", None)
    domain = getattr(args, "domain", None)
    limit = getattr(args, "limit", 50) or 50

    experiences = _load()

    if agent:
        experiences = [e for e in experiences if e.get("agent_id") == agent]
    if exp_type:
        experiences = [e for e in experiences if e.get("type") == exp_type]
    if domain:
        experiences = [e for e in experiences if e.get("domain") == domain]

    experiences = experiences[-limit:]

    if not experiences:
        print("  No experiences found.")
        print()
        print("  Record your first experience:")
        print('    intent-os experience record --agent <id> --type failure_pattern --observation "..."')
        print()
        return

    print()
    filters = []
    if agent:
        filters.append(f"agent: {agent}")
    if exp_type:
        filters.append(f"type: {exp_type}")
    if domain:
        filters.append(f"domain: {domain}")
    label = f" ({', '.join(filters)})" if filters else ""
    print(f"  Experiences{label} (showing up to {limit}):")
    print()
    print(f"  {'ID':<16} {'Type':<28} {'Agent':<14} {'Valid':<6} {'Recorded'}")
    print(f"  {'-'*84}")

    for e in reversed(experiences):
        eid = e["experience_id"]
        icon = _TYPE_ICONS.get(e.get("type", ""), "?")
        type_str = f"{icon} {e.get('type', '?')}"
        agent_str = (e.get("agent_id") or "")[:13]
        valid_mark = "Yes" if e.get("validated") else "No"
        recorded = (e.get("recorded_at") or "")[:19]
        print(f"  {eid:<16} {type_str:<28} {agent_str:<14} {valid_mark:<6} {recorded}")
    print()


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------
def _cmd_get(args: Any) -> None:
    """Show full detail for a single experience entry."""
    experience_id = args.experience_id
    experiences = _load()
    entry = next((e for e in experiences if e["experience_id"] == experience_id), None)

    if entry is None:
        print(f"  Experience not found: {experience_id}")
        print()
        print("  List all experiences:")
        print("    intent-os experience list")
        print()
        return

    icon = _TYPE_ICONS.get(entry.get("type", ""), "?")
    print()
    print(f"  {icon} Experience: {entry['experience_id']}")
    print()
    print(f"  Type:           {entry.get('type', '-')}")
    print(f"  Agent:          {entry.get('agent_id', '-')}")
    print(f"  Observation:    {entry.get('observation', '-')}")
    if entry.get("recommendation"):
        print(f"  Recommendation: {entry['recommendation']}")
    if entry.get("execution_ids"):
        print(f"  Executions:     {', '.join(entry['execution_ids'])}")
    if entry.get("confidence") is not None:
        print(f"  Confidence:     {entry['confidence']}")
    if entry.get("domain"):
        print(f"  Domain:         {entry['domain']}")
    if entry.get("tags"):
        print(f"  Tags:           {', '.join(entry['tags'])}")
    print(f"  Validated:      {'Yes' if entry.get('validated') else 'No'}")
    print(f"  Successful:     {'Yes' if entry.get('successful') else 'No'}")
    print(f"  Recorded:       {(entry.get('recorded_at') or '-')[:19]}")
    print()


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------
def _cmd_extract(args: Any) -> None:
    """Extract experiences for an agent, or auto-extract for all agents if omitted.

    When ``--agent`` is provided, runs the full ExperienceExtractor pipeline
    against the Event Store and persists new Experiences to the Experience
    Store.  The results include context linkage information — which execution
    context(s) the new experiences are associated with.
    """
    agent = getattr(args, "agent", None)

    # ── Run the real extractor when --agent is specified ──
    extractor_result: dict[str, Any] | None = None
    if agent:
        try:
            from pathlib import Path as _Path
            from core.event_store import EventStore
            from core.experience_extractor import (
                ExperienceExtractor, ExperienceStore as ExtractorExperienceStore,
            )

            event_store = EventStore(
                str(_Path.home() / ".intent-os" / "intent_os_store.db")
            )
            exp_store = ExtractorExperienceStore()
            extractor = ExperienceExtractor(event_store, exp_store)
            extractor_result = extractor.extract_all(agent)
        except Exception:
            extractor_result = None  # Gracefully fall back to JSON-only report

    # ── JSON-file based summary (always shown) ──
    experiences = _load()
    if agent:
        experiences = [e for e in experiences if e.get("agent_id") == agent]

    if not experiences and extractor_result is None:
        print("  No experiences to extract.")
        print()
        print("  Record experiences first:")
        print('    intent-os experience record --agent <id> --type failure_pattern --observation "..."')
        print()
        return

    # Collect per-type summaries from the JSON store
    by_type: dict[str, list[dict[str, Any]]] = {}
    for e in experiences:
        t = e.get("type", "unknown")
        by_type.setdefault(t, []).append(e)

    agent_label = f"agent '{agent}'" if agent else "all agents"

    # ── Show extractor results if available ──
    if extractor_result:
        total_new = sum(
            extractor_result.get(k, 0)
            for k in (
                "failure_patterns", "success_strategies",
                "tool_preferences", "data_source_reliability",
            )
        )
        print()
        print(f"  Experience Extraction Report ({agent_label})")
        print(f"  {'─'*52}")
        print(f"  New experiences extracted: {total_new}")
        for key, label in [
            ("failure_patterns", "Failure patterns"),
            ("success_strategies", "Success strategies"),
            ("tool_preferences", "Tool preferences"),
            ("data_source_reliability", "Data source reliability"),
        ]:
            count = extractor_result.get(key, 0)
            icon = _TYPE_ICONS.get(key.rstrip("s"), "?")
            print(f"    {icon} {label:<28} {count:>4}")
        print()

        # ── Context linkage ──
        context_ids = extractor_result.get("context_ids") or []
        context_linked = extractor_result.get("context_linked", 0)
        if context_ids:
            print(f"  Linked to context(s):")
            for cid in context_ids:
                print(f"    - {cid}")
            print(f"  ({context_linked} experience(s) tagged with context IDs)")
        else:
            print(f"  Linked to context(s): (none — no context_id found in execution records)")
        print()

    # ── JSON-file summary ──
    if experiences:
        total = len(experiences)
        validated = sum(1 for e in experiences if e.get("validated"))
        successful = sum(1 for e in experiences if e.get("successful"))

        if not extractor_result:
            print()
            print(f"  Experience Extraction Report ({agent_label})")
            print(f"  {'─'*52}")

        print(f"  Stored entries:      {total}")
        print(f"  Validated:           {validated}/{total}")
        print(f"  Marked successful:   {successful}/{total}")
        print()

        if by_type:
            print(f"  Breakdown by type:")
            for t, entries in sorted(by_type.items()):
                icon = _TYPE_ICONS.get(t, "?")
                print(f"    {icon} {t:<28} {len(entries):>4} entries")
            print()

        # Print top observations
        print(f"  Recent observations:")
        for e in reversed(experiences[-10:]):
            icon = _TYPE_ICONS.get(e.get("type", ""), "?")
            obs = (e.get("observation") or "")[:100]
            print(f"    {icon} [{e['experience_id']}] {obs}")
        print()


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------
def _cmd_query(args: Any) -> None:
    """Keyword-match query across observations."""
    goal = args.goal
    agent = getattr(args, "agent", None)
    limit = getattr(args, "limit", 10) or 10

    experiences = _load()

    if agent:
        experiences = [e for e in experiences if e.get("agent_id") == agent]

    # Keyword match against observation, recommendation, domain, and tags
    keywords = goal.lower().split()
    scored: list[tuple[int, dict[str, Any]]] = []
    for e in experiences:
        text = " ".join([
            e.get("observation", ""),
            e.get("recommendation", ""),
            e.get("domain", ""),
            " ".join(e.get("tags", [])),
        ]).lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((score, e))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    if not top:
        print(f"  No experiences matching: \"{goal}\"")
        print()
        return

    agent_label = f"agent '{agent}'" if agent else "all agents"
    print()
    print(f"  Query results for \"{goal}\" ({agent_label}, limit {limit}):")
    print()

    for score, e in top:
        icon = _TYPE_ICONS.get(e.get("type", ""), "?")
        eid = e["experience_id"]
        obs = (e.get("observation") or "")[:100]
        rec = (e.get("recommendation") or "")[:60]
        print(f"  {icon} {eid}  (score: {score})")
        print(f"     [{e.get('type', '?')}] {obs}")
        if rec:
            print(f"     Recommendation: {rec}")
        print()
    print()


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
def _cmd_validate(args: Any) -> None:
    """Mark an experience as validated and/or successful."""
    experience_id = args.experience_id
    valid_flag = getattr(args, "valid", False)
    success_flag = getattr(args, "success", False)

    if not valid_flag and not success_flag:
        print("Error: at least one of --valid or --success is required", file=sys.stderr)
        sys.exit(1)

    experiences = _load()
    updated = False
    for e in experiences:
        if e["experience_id"] == experience_id:
            if valid_flag:
                e["validated"] = True
            if success_flag:
                e["successful"] = True
            updated = True
            break

    if not updated:
        print(f"  Experience not found: {experience_id}")
        sys.exit(1)

    _save(experiences)

    icon = _TYPE_ICONS.get(next(
        (e["type"] for e in experiences if e["experience_id"] == experience_id), ""
    ), "?")
    print()
    print(f"  {icon} Experience '{experience_id}' updated:")
    print(f"     Validated:  {'Yes' if valid_flag else 'No change'}")
    print(f"     Successful: {'Yes' if success_flag else 'No change'}")
    print()
