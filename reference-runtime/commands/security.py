"""
Intent OS — Security Manager CLI Commands.

Each command function follows the same pattern:
  1. Lazy imports (no top-level import of core modules).
  2. Try/except around the business logic.
  3. ``print()`` for structured output.
  4. ``sys.exit(1)`` on error.

Command tree::

    security
      policy list          — List all policies
      policy get <name>    — Get policy details
      policy apply <file>  — Apply a policy from a YAML file
      evaluate <manifest>  — Evaluate a capability against policies (dry run)
      audit                — Export compliance report
"""

from __future__ import annotations

import json
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_path_from_args(args: Any) -> str:
    """Resolve the policy-store database path.

    Prefer the value from the ``--store`` flag; fall back to the default
    ``~/.intent-os/intent.db``.
    """
    from core.security import POLICY_DB
    return getattr(args, "store", None) or POLICY_DB


def _print_json(data: Any) -> None:
    """Pretty-print *data* as JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# security policy list
# ---------------------------------------------------------------------------

def cmd_policy_list(args: Any) -> None:
    """List all policies from the PolicyStore."""
    try:
        from core.security import PolicyStore  # lazy import

        store = PolicyStore(_db_path_from_args(args))
        policies = store.list_all()
        store.close()

        if not policies:
            print("No policies found.")
            return

        rows: list[dict[str, Any]] = []
        for p in policies:
            rows.append({
                "policy_id": p.policy_id,
                "target_patterns": p.target_patterns,
                "version": p.version,
                "enabled": p.enabled,
                "description": p.description,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            })

        _print_json({"count": len(rows), "policies": rows})

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# security policy get
# ---------------------------------------------------------------------------

def cmd_policy_get(args: Any) -> None:
    """Get a single policy by ID."""
    try:
        from core.security import PolicyStore  # lazy import

        policy_id: str = args.name
        store = PolicyStore(_db_path_from_args(args))
        policy = store.get(policy_id)
        store.close()

        if policy is None:
            print(f"Policy '{policy_id}' not found.", file=sys.stderr)
            sys.exit(1)

        _print_json(policy.to_dict())

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# security policy apply
# ---------------------------------------------------------------------------

def cmd_policy_apply(args: Any) -> None:
    """Apply a policy from a YAML file.

    The YAML file is expected to contain a single policy document with keys
    matching :class:`core.security.Policy` fields.
    """
    try:
        import yaml  # lazy import (optional dependency)

        from core.security import Policy, PolicyStore  # lazy import

        filepath: str = args.file

        with open(filepath, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh)

        if not isinstance(raw, dict):
            print("Error: YAML file must contain a mapping (dict).", file=sys.stderr)
            sys.exit(1)

        policy = Policy.from_dict(raw)
        store = PolicyStore(_db_path_from_args(args))
        result = store.upsert(policy)
        store.close()

        print(f"Policy '{result.policy_id}' applied (v{result.version}).")
        _print_json(result.to_dict())

    except FileNotFoundError:
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)
    except ImportError:
        print(
            "Error: PyYAML is required. Install it with: pip install pyyaml",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# security evaluate
# ---------------------------------------------------------------------------

def cmd_evaluate(args: Any) -> None:
    """Evaluate a capability manifest against stored policies (dry run).

    The manifest is a JSON/YAML file containing a capability description
    and an optional evaluation context:

    .. code-block:: yaml

        capability:
          name: file.write
          risk: high
          permissions_required: ["file:write"]
        context:
          user_role: admin
          source_ip: 10.0.0.1
    """
    try:
        import yaml  # lazy import

        from core.security import PolicyStore, SecurityManager  # lazy import

        filepath: str = args.manifest

        with open(filepath, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh)

        if not isinstance(raw, dict):
            print("Error: Manifest must contain a mapping.", file=sys.stderr)
            sys.exit(1)

        # Try standard Capability Manifest format first
        if raw.get("kind") == "Capability":
            from core.parser import parse_manifest
            manifest, _ = parse_manifest(filepath)
            capability = {
                "name": manifest.name,
                "risk": manifest.security.risk.value if manifest.security and manifest.security.risk else "low",
            }
            context = {}
        else:
            # Custom evaluation format with capability + context
            capability: dict[str, Any] = raw.get("capability", {})
            context: dict[str, Any] = raw.get("context", {})

            if not capability or "name" not in capability:
                print(
                    "Error: Manifest must include a 'capability' dict with a 'name' key.",
                    file=sys.stderr,
                )
                sys.exit(1)

        db_path = _db_path_from_args(args)
        policy_store = PolicyStore(db_path)
        manager = SecurityManager(policy_store=policy_store, event_store=None)

        result = manager.evaluate(capability=capability, context=context)

        policy_store.close()

        _print_json({
            "capability_name": result.capability_name,
            "decision": result.decision.value,
            "rationale": result.rationale,
            "policy_id": result.policy_id,
            "risk_level": result.risk_level,
        })

    except FileNotFoundError:
        print(f"Error: Manifest not found: {args.manifest}", file=sys.stderr)
        sys.exit(1)
    except ImportError:
        print(
            "Error: PyYAML is required. Install it with: pip install pyyaml",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# security audit
# ---------------------------------------------------------------------------

def cmd_audit(args: Any) -> None:
    """Export a compliance report summarising all policies, capabilities,
    and their coverage.

    The report is printed as JSON with:
      - ``timestamp`` — when the report was generated.
      - ``policy_count`` — total number of policies.
      - ``enabled_count`` — number of active (enabled) policies.
      - ``disabled_count`` — number of inactive (disabled) policies.
      - ``policies`` — full list of policies with their target patterns and rules.
      - ``capability_coverage`` — aggregated view of which risk levels are
        covered by ``require_review_for`` rules.
    """
    try:
        from datetime import datetime, timezone

        from core.security import PolicyStore  # lazy import

        store = PolicyStore(_db_path_from_args(args))
        policies = store.list_all()
        store.close()

        enabled: list[dict[str, Any]] = []
        disabled: list[dict[str, Any]] = []
        coverage: dict[str, list[str]] = {}

        for p in policies:
            entry: dict[str, Any] = {
                "policy_id": p.policy_id,
                "target_patterns": p.target_patterns,
                "risk_overrides": p.risk_overrides,
                "permissions": p.permissions,
                "review_rules": p.review_rules,
                "version": p.version,
                "description": p.description,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }

            if p.enabled:
                enabled.append(entry)
                # Collect review coverage
                review_levels: list[str] = p.review_rules.get("require_review_for", [])
                for level in review_levels:
                    coverage.setdefault(level, []).append(p.policy_id)
            else:
                disabled.append(entry)

        report: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "policy_count": len(policies),
            "enabled_count": len(enabled),
            "disabled_count": len(disabled),
            "policies": {
                "enabled": enabled,
                "disabled": disabled,
            },
            "capability_coverage": dict(coverage),
        }

        _print_json(report)

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command map (consumed by cli.py)
# ---------------------------------------------------------------------------

#: Mapping of (subcommand_path) → handler function.
CMD_MAP: dict[str, Any] = {
    "policy list": cmd_policy_list,
    "policy get": cmd_policy_get,
    "policy apply": cmd_policy_apply,
    "evaluate": cmd_evaluate,
    "audit": cmd_audit,
}
