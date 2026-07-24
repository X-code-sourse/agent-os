"""
Intent OS — Security Manager (SPEC-0004 Control Plane).

Stateless security policy evaluator that reads versioned policies from a
SQLite-backed PolicyStore (Metadata Plane) and emits PolicyEvaluated events
for every decision.

Design rules (SPEC-0004):
    1. Stateless — SecurityManager holds no mutable evaluation state.
    2. All decisions are recorded as Events (R3).
    3. Pure function: evaluate(policy, capability, context) -> decision.
    4. Policy store lives in Metadata Plane (separate SQLite DB).

Usage:
    from core.event_store import EventStore
    from core.security import SecurityManager, PolicyStore, SecurityDecision

    store = PolicyStore("intent_os_policies.db")
    manager = SecurityManager(policy_store=store, event_store=EventStore())

    decision, rationale, policy_id = manager.evaluate(
        capability={"name": "file.write", "risk": "high"},
        context={"user_role": "admin", "source_ip": "10.0.0.1"},
    )

    if decision == SecurityDecision.DENY:
        print(f"Blocked: {rationale}")

Integration points:
    - core.models.Event, EventType.POLICY_EVALUATED  — event emission
    - core.event_store.EventStore.save_event()        — persistence
    - core.models (SecurityRisk, SecuritySpec)        — capability typing
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from fnmatch import fnmatch
from typing import Any

from core.event_store import EventStore
from core.models import Event, EventType


# ════════════════════════════════════════════════════════════════
# Enums
# ════════════════════════════════════════════════════════════════


class SecurityDecision(Enum):
    """Outcome of a security policy evaluation.

    Ordered from most permissive to most restrictive for easy comparison.
    """

    ALLOW = "allow"
    """Capability is explicitly permitted."""

    REQUIRE_REVIEW = "require_review"
    """Capability exceeds configured risk tolerance and needs human approval."""

    DENY = "deny"
    """Capability is explicitly forbidden by policy."""


class SecurityRisk(Enum):
    """Risk level associated with a capability.

    Copied from core.models for local convenience. Also importable as
    ``from core.models import SecurityRisk`` when that module defines it.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    def __ge__(self, other: SecurityRisk) -> bool:
        """Compare by ordinal: CRITICAL >= HIGH >= MEDIUM >= LOW."""
        levels = list(SecurityRisk)
        return levels.index(self) >= levels.index(other)

    def __le__(self, other: SecurityRisk) -> bool:
        levels = list(SecurityRisk)
        return levels.index(self) <= levels.index(other)

    @classmethod
    def from_str(cls, value: str) -> SecurityRisk:
        """Parse a string into a SecurityRisk, defaulting to MEDIUM."""
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.MEDIUM


# ════════════════════════════════════════════════════════════════
# Data types
# ════════════════════════════════════════════════════════════════


@dataclass
class SecuritySpec:
    """Security specification attached to a capability.

    This mirrors the type referenced in ``core.models`` and is used by the
    SecurityManager to evaluate whether a capability invocation should be
    allowed, denied, or queued for review.
    """

    name: str
    """Canonical capability name, e.g. ``"file.write"``."""

    risk: SecurityRisk = SecurityRisk.MEDIUM
    """Baseline risk level assigned to this capability."""

    permissions_required: list[str] = field(default_factory=list)
    """Permissions the caller must hold, e.g. ``["file:write"]``."""

    review_required: bool = False
    """If True, the capability always requires human review regardless of risk."""

    allowed_contexts: list[str] = field(default_factory=list)
    """List of allowed context keys (glob patterns against context keys like
    ``"source_ip"``, ``"user_role"``). Empty means no context restriction."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "risk": self.risk.value,
            "permissions_required": list(self.permissions_required),
            "review_required": self.review_required,
            "allowed_contexts": list(self.allowed_contexts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecuritySpec:
        return cls(
            name=data["name"],
            risk=SecurityRisk.from_str(data.get("risk", "medium")),
            permissions_required=list(data.get("permissions_required", [])),
            review_required=bool(data.get("review_required", False)),
            allowed_contexts=list(data.get("allowed_contexts", [])),
        )


# ════════════════════════════════════════════════════════════════
# Policy
# ════════════════════════════════════════════════════════════════


@dataclass
class Policy:
    """A versioned security policy.

    Policies are stored in the Metadata Plane (separate SQLite DB) and are
    loaded by :class:`PolicyStore` during evaluation. Each policy declares
    which capabilities it targets (via glob patterns), risk overrides,
    explicit permissions, and review rules.

    Attributes:
        policy_id:
            Unique identifier for the policy.
        target_patterns:
            Glob patterns matching capability names this policy applies to,
            e.g. ``["file.*", "network.connect"]``.
        risk_overrides:
            Mapping from target pattern to a risk-level override,
            e.g. ``{"file.delete": "critical"}``.
        permissions:
            Permissions granted by this policy, e.g. ``["file:read"]``.
        review_rules:
            Additional review conditions as a free-form dict.
            Known keys:

            - ``require_review_for`` (list[str]): risk levels that trigger
              ``REQUIRE_REVIEW``, e.g. ``["high", "critical"]``.
        version:
            Monotonically increasing version number. Bumped on every update.
        description:
            Human-readable description of this policy.
        enabled:
            Whether the policy is active. Disabled policies are skipped during
            evaluation.
        created_at:
            ISO-8601 timestamp of creation.
        updated_at:
            ISO-8601 timestamp of last update.
    """

    policy_id: str
    target_patterns: list[str] = field(default_factory=list)
    risk_overrides: dict[str, str] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    review_rules: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    description: str = ""
    enabled: bool = True
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def matches(self, capability_name: str) -> bool:
        """Check if this policy applies to *capability_name*.

        Checks against every pattern in ``target_patterns`` using
        :func:`fnmatch.fnmatch`. Short-circuits on the first match.
        """
        for pattern in self.target_patterns:
            if fnmatch(capability_name, pattern):
                return True
        return False

    def effective_risk(self, capability_name: str, baseline: SecurityRisk) -> SecurityRisk:
        """Return the effective risk level for *capability_name*.

        Uses ``risk_overrides`` if the capability matches a key pattern;
        otherwise returns *baseline*.
        """
        for pattern, override in self.risk_overrides.items():
            if fnmatch(capability_name, pattern):
                return SecurityRisk.from_str(override)
        return baseline

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "target_patterns": list(self.target_patterns),
            "risk_overrides": dict(self.risk_overrides),
            "permissions": list(self.permissions),
            "review_rules": dict(self.review_rules),
            "version": self.version,
            "description": self.description,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Policy:
        return cls(
            policy_id=data["policy_id"],
            target_patterns=list(data.get("target_patterns", [])),
            risk_overrides=dict(data.get("risk_overrides", {})),
            permissions=list(data.get("permissions", [])),
            review_rules=dict(data.get("review_rules", {})),
            version=int(data.get("version", 1)),
            description=str(data.get("description", "")),
            enabled=bool(data.get("enabled", True)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


# ════════════════════════════════════════════════════════════════
# PolicyStore — SQLite-backed (Metadata Plane)
# ════════════════════════════════════════════════════════════════


class PolicyStore:
    """Versioned policy store backed by a separate SQLite database.

    Lives in the Metadata Plane — distinct from the execution EventStore.
    Supports CRUD operations and version tracking. Every mutation bumps
    the policy's ``version`` field.

    Usage:
        store = PolicyStore("intent_os_policies.db")
        store.upsert(Policy(policy_id="pol-001", target_patterns=["file.*"]))

        policy = store.get("pol-001")
        policies = store.get_for_capability("file.write", context={})
    """

    def __init__(self, db_path: str) -> None:
        """Initialise the PolicyStore.

        Args:
            db_path: Filesystem path to the SQLite database file. Created
                automatically if it does not exist.
        """
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._create_table()

    # ── Connection management ──

    @property
    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        """Explicitly close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> PolicyStore:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── Schema ──

    def _create_table(self) -> None:
        """Ensure the policies table exists.

        Columns use TEXT for JSON-encoded fields so queries remain
        readable without pulling in a JSON1 extension dependency.
        """
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS policies (
                policy_id      TEXT PRIMARY KEY,
                target_patterns TEXT NOT NULL DEFAULT '[]',
                risk_overrides  TEXT NOT NULL DEFAULT '{}',
                permissions     TEXT NOT NULL DEFAULT '[]',
                review_rules    TEXT NOT NULL DEFAULT '{}',
                version         INTEGER NOT NULL DEFAULT 1,
                description     TEXT NOT NULL DEFAULT '',
                enabled         INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        self._connection.commit()

    # ── CRUD ──

    def upsert(self, policy: Policy) -> Policy:
        """Insert or update *policy*.

        If the policy already exists, its ``version`` is incremented by 1
        and ``updated_at`` is refreshed.
        """
        existing = self.get(policy.policy_id)
        now = datetime.now(timezone.utc).isoformat()
        now_str: str = now

        if existing:
            policy.version = existing.version + 1
            policy.created_at = existing.created_at
            policy.updated_at = now_str
        else:
            policy.version = 1
            policy.created_at = now_str
            policy.updated_at = now_str

        self._connection.execute(
            """
            INSERT INTO policies (
                policy_id, target_patterns, risk_overrides, permissions,
                review_rules, version, description, enabled,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(policy_id) DO UPDATE SET
                target_patterns = excluded.target_patterns,
                risk_overrides  = excluded.risk_overrides,
                permissions     = excluded.permissions,
                review_rules    = excluded.review_rules,
                version         = excluded.version,
                description     = excluded.description,
                enabled         = excluded.enabled,
                updated_at      = excluded.updated_at
            """,
            (
                policy.policy_id,
                json.dumps(policy.target_patterns),
                json.dumps(policy.risk_overrides),
                json.dumps(policy.permissions),
                json.dumps(policy.review_rules),
                policy.version,
                policy.description,
                1 if policy.enabled else 0,
                policy.created_at,
                policy.updated_at,
            ),
        )
        self._connection.commit()
        return policy

    def get(self, policy_id: str) -> Policy | None:
        """Retrieve a single policy by ID, or ``None`` if it does not exist."""
        row = self._connection.execute(
            "SELECT * FROM policies WHERE policy_id = ?",
            (policy_id,),
        ).fetchone()

        if row is None:
            return None
        return self._row_to_policy(row)

    def get_for_capability(
        self,
        capability_name: str,
        context: dict[str, Any] | None = None,
    ) -> list[Policy]:
        """Return all enabled policies that match *capability_name*.

        Policies are returned in insertion order. Only enabled policies
        whose ``target_patterns`` include a pattern matching
        *capability_name* (via :func:`fnmatch.fnmatch`) are returned.

        Args:
            capability_name:
                The canonical capability name to match, e.g.
                ``"file.write"``.
            context:
                Optional evaluation context (currently unused at the query
                level; passed through for future context-aware filtering).

        Returns:
            List of matching :class:`Policy` objects (may be empty).
        """
        rows = self._connection.execute(
            "SELECT * FROM policies WHERE enabled = 1"
        ).fetchall()

        matching: list[Policy] = []
        for row in rows:
            policy = self._row_to_policy(row)
            if policy.matches(capability_name):
                matching.append(policy)
        return matching

    def delete(self, policy_id: str) -> bool:
        """Delete a policy by ID.

        Returns:
            ``True`` if a row was deleted, ``False`` if the policy did not
            exist.
        """
        cursor = self._connection.execute(
            "DELETE FROM policies WHERE policy_id = ?",
            (policy_id,),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def list_all(self) -> list[Policy]:
        """Return every policy in the store, enabled or not."""
        rows = self._connection.execute(
            "SELECT * FROM policies ORDER BY created_at ASC"
        ).fetchall()
        return [self._row_to_policy(row) for row in rows]

    def count(self) -> int:
        """Return the total number of policies stored."""
        row = self._connection.execute(
            "SELECT COUNT(*) AS cnt FROM policies"
        ).fetchone()
        return row["cnt"] if row else 0

    # ── Internal ──

    @staticmethod
    def _row_to_policy(row: sqlite3.Row) -> Policy:
        return Policy(
            policy_id=row["policy_id"],
            target_patterns=json.loads(row["target_patterns"]),
            risk_overrides=json.loads(row["risk_overrides"]),
            permissions=json.loads(row["permissions"]),
            review_rules=json.loads(row["review_rules"]),
            version=row["version"],
            description=row["description"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ════════════════════════════════════════════════════════════════
# SecurityManager — Stateless Evaluator
# ════════════════════════════════════════════════════════════════


class SecurityError(Exception):
    """Raised when the security manager encounters an operational failure."""
    pass


@dataclass
class EvaluationResult:
    """Result of a single capability evaluation.

    Returned by :meth:`SecurityManager.evaluate` as a structured object
    rather than a bare tuple, making the contract explicit and
    self-documenting.
    """

    decision: SecurityDecision
    """The final security decision."""

    rationale: str
    """Human-readable explanation of *decision*."""

    policy_id: str | None
    """The ID of the policy that drove the decision, or ``None`` if no
    applicable policy was found."""

    risk_level: str
    """Effective risk level used during evaluation (may be overridden by
    policy)."""

    capability_name: str
    """The name of the capability that was evaluated."""

    def to_tuple(self) -> tuple[SecurityDecision, str, str | None]:
        """Convenience accessor for callers that want a 3-tuple.

        Returns:
            ``(decision, rationale, policy_id)``
        """
        return (self.decision, self.rationale, self.policy_id)


class SecurityManager:
    """Stateless security policy evaluator (SPEC-0004 Control Plane).

    This class **holds no mutable evaluation state** — all decision logic
    is driven from the current snapshot of the :class:`PolicyStore` and the
    capability + context passed to :meth:`evaluate`.  Every evaluation is
    recorded as a ``PolicyEvaluated`` event in the :class:`EventStore`.

    The manager follows a simple decision tree:

    1. Load all matching policies from the ``PolicyStore``.
    2. If no policy matches and the capability has no explicit spec, deny.
    3. If the capability's effective risk exceeds the policy's review
       threshold, return ``REQUIRE_REVIEW``.
    4. If any matching policy contains an explicit deny rule, return ``DENY``.
    5. If any matching policy contains an explicit allow rule, return ``ALLOW``.
    6. If the capability requires review (``SecuritySpec.review_required``),
       return ``REQUIRE_REVIEW``.
    7. Default behaviour: ``ALLOW`` when at least one policy matches,
       ``DENY`` otherwise.

    Usage:
        store = PolicyStore("intent_os_policies.db")
        manager = SecurityManager(
            policy_store=store,
            event_store=EventStore(),
        )

        result = manager.evaluate(
            capability=SecuritySpec(name="file.write", risk=SecurityRisk.HIGH),
            context={"user_role": "admin"},
        )

        if result.decision == SecurityDecision.ALLOW:
            capability.execute()
    """

    def __init__(
        self,
        policy_store: PolicyStore,
        event_store: EventStore | None = None,
    ) -> None:
        """Initialise the SecurityManager.

        Args:
            policy_store:
                The SQLite-backed PolicyStore to load policies from.
                Required.
            event_store:
                Optional EventStore for emitting ``PolicyEvaluated`` events.
                When ``None``, no events are persisted (the evaluator still
                returns decisions).
        """
        self._policy_store = policy_store
        self._event_store = event_store

    # ────────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────────

    def evaluate(
        self,
        capability: SecuritySpec | dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        *,
        capability_name: str | None = None,
        risk_level: str | None = None,
    ) -> EvaluationResult:
        """Evaluate a capability against the configured policies.

        The *capability* argument can be provided as a
        :class:`SecuritySpec` instance, a dict with ``name`` and ``risk``
        keys, or omitted entirely if ``capability_name`` and ``risk_level``
        are supplied as keyword arguments.

        Args:
            capability:
                A :class:`SecuritySpec` or dict describing the capability.
                Dict form expects at least ``{"name": str}`` and optionally
                ``{"risk": str}``. If ``None``, use *capability_name* +
                *risk_level* kwargs.
            context:
                Optional evaluation context dict (e.g. ``{"user_role":
                "admin", "source_ip": "10.0.0.1"}``). May be used by future
                context-aware rules.
            capability_name:
                Bare capability name (used when *capability* is ``None``).
            risk_level:
                Bare risk level string (used when *capability* is ``None``).
                Defaults to ``"medium"``.

        Returns:
            :class:`EvaluationResult` with decision, rationale, policy_id,
            risk_level, and capability_name.

        Raises:
            SecurityError: If neither *capability* nor *capability_name* is
                provided.

        Example:
            >>> manager = SecurityManager(policy_store, event_store)
            >>> result = manager.evaluate(
            ...     {"name": "file.write", "risk": "high"},
            ...     {"user_role": "editor"},
            ... )
            >>> result.decision
            <SecurityDecision.ALLOW: 'allow'>
        """
        # ── Normalise inputs ──
        spec = self._resolve_capability(capability, capability_name, risk_level)
        ctx: dict[str, Any] = context or {}
        cap_name: str = spec.name
        baseline_risk: SecurityRisk = spec.risk

        # Every evaluation gets a fresh trace_id — SecurityManager owns
        # no session state (R1 compliance).
        trace_id: str = str(uuid.uuid4())

        # ── Step 1: Load matching policies ──
        policies = self._policy_store.get_for_capability(cap_name, ctx)

        # ── Step 2: Determine effective risk ──
        effective_risk: SecurityRisk = baseline_risk
        matched_policy: Policy | None = None

        for policy in policies:
            policy_risk = policy.effective_risk(cap_name, baseline_risk)
            if policy_risk != baseline_risk:
                effective_risk = policy_risk
                matched_policy = policy
                break

        # If no policy overrode the risk, use the first matching policy (if any)
        if matched_policy is None and policies:
            matched_policy = policies[0]

        # ── Step 3: Decision tree ──
        # Priority (highest to lowest):
        #   1. Explicit DENY rule in any policy — final, cannot be overridden.
        #   2. Explicit ALLOW rule in any policy — overrides REVIEW.
        #   3. Review threshold exceeded in any policy.
        #   4. spec.review_required flag (no policy required).
        #   5. Context restrictions (spec.allowed_contexts).
        #   6. Default: ALLOW if at least one policy matched, else DENY.
        #
        # Spec-level checks (review_required, context restrictions) apply
        # regardless of whether any policy was found.

        decision: SecurityDecision = SecurityDecision.ALLOW
        rationale: str = ""
        deciding_policy: Policy | None = None

        # ── Phase A: Policy-driven checks ──

        # A1: Explicit DENY — final, checked first across ALL policies.
        for policy in policies:
            if "deny" in policy.review_rules and self._matches_rules(
                cap_name, policy.review_rules["deny"], ctx
            ):
                decision = SecurityDecision.DENY
                deciding_policy = policy
                rationale = (
                    f"Capability '{cap_name}' matches an explicit deny rule "
                    f"in policy '{policy.policy_id}'."
                )
                break  # DENY is final

        # A2: If not denied, check for explicit ALLOW (overrides REVIEW).
        # Track whether an explicit allow was found so A3 doesn't override it.
        _explicit_allowed: bool = False
        if decision != SecurityDecision.DENY:
            for policy in policies:
                has_allow = "allow" in policy.review_rules
                if has_allow:
                    matches = self._matches_rules(
                        cap_name, policy.review_rules["allow"], ctx
                    )
                if has_allow and matches:
                    decision = SecurityDecision.ALLOW
                    _explicit_allowed = True
                    deciding_policy = policy
                    rationale = (
                        f"Capability '{cap_name}' matches an explicit allow "
                        f"rule in policy '{policy.policy_id}'."
                    )
                    break  # First explicit allow wins

        # A3: If still undecided and no explicit allow was found,
        #     check review thresholds.
        if decision == SecurityDecision.ALLOW and not _explicit_allowed:
            for policy in policies:
                if "require_review_for" in policy.review_rules:
                    policy_risk = policy.effective_risk(cap_name, baseline_risk)
                    review_levels = policy.review_rules["require_review_for"]
                    if policy_risk.value in review_levels:
                        decision = SecurityDecision.REQUIRE_REVIEW
                        deciding_policy = policy
                        rationale = (
                            f"Capability '{cap_name}' has risk level "
                            f"'{policy_risk.value}' which requires review "
                            f"per policy '{policy.policy_id}'."
                        )
                        break  # First threshold hit wins

        # A4: Still ALLOW and policies matched — attribute to first policy.
        if decision == SecurityDecision.ALLOW and not deciding_policy and policies:
            deciding_policy = policies[0]
            rationale = (
                f"Capability '{cap_name}' is permitted by policy "
                f"'{policies[0].policy_id}'."
            )

        # ── Phase B: Spec-level and default checks ──

        # B1: spec.review_required (checked if not already denied).
        if decision != SecurityDecision.DENY and spec.review_required:
            decision = SecurityDecision.REQUIRE_REVIEW
            rationale = (
                f"Capability '{cap_name}' is flagged for mandatory review "
                f"per its security spec."
            )

        # B2: No policies matched at all — deny by default.
        if decision == SecurityDecision.ALLOW and not policies:
            decision = SecurityDecision.DENY
            rationale = (
                f"No matching policy for capability '{cap_name}'. "
                f"Denied by default."
            )

        # B3: Context restrictions — fail closed.
        if decision != SecurityDecision.DENY and spec.allowed_contexts:
            if not self._context_allowed(ctx, spec.allowed_contexts):
                decision = SecurityDecision.DENY
                rationale = (
                    f"Capability '{cap_name}' is not allowed in the current "
                    f"context per its security spec."
                )

        # Use the deciding policy (if any) as the matched_policy for the result
        if deciding_policy is not None:
            matched_policy = deciding_policy

        # ── Step 4: Build result ──
        result = EvaluationResult(
            decision=decision,
            rationale=rationale,
            policy_id=matched_policy.policy_id if matched_policy else None,
            risk_level=effective_risk.value,
            capability_name=cap_name,
        )

        # ── Step 5: Emit event ──
        self._emit_event(result, trace_id)

        return result

    # ────────────────────────────────────────────────────────────
    # Event emission
    # ────────────────────────────────────────────────────────────

    def _emit_event(
        self,
        result: EvaluationResult,
        trace_id: str | None = None,
    ) -> None:
        """Record the evaluation result as a ``PolicyEvaluated`` event.

        The event payload follows the standard schema:

        .. code-block:: json

            {
                "policy_id": "pol-001",
                "capability": "file.write",
                "decision": "allow",
                "rationale": "...",
                "risk_level": "low"
            }
        """
        if self._event_store is None:
            return

        event = Event.create(
            event_type=EventType.POLICY_EVALUATED,
            trace_id=trace_id or str(uuid.uuid4()),
            source="security_manager",
            sequence=1,
            payload={
                "policy_id": result.policy_id,
                "capability": result.capability_name,
                "decision": result.decision.value,
                "rationale": result.rationale,
                "risk_level": result.risk_level,
            },
        )
        self._event_store.save_event(event)

    # ────────────────────────────────────────────────────────────
    # Internal helpers
    # ────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_capability(
        capability: SecuritySpec | dict[str, Any] | None,
        capability_name: str | None,
        risk_level: str | None,
    ) -> SecuritySpec:
        """Normalise *capability* into a ``SecuritySpec``.

        Accepts a ``SecuritySpec``, a dict, or builds one from
        *capability_name* + *risk_level* kwargs.
        """
        if capability is None:
            if not capability_name:
                raise SecurityError(
                    "evaluate() requires either a capability (SecuritySpec/dict) "
                    "or capability_name."
                )
            return SecuritySpec(
                name=capability_name,
                risk=SecurityRisk.from_str(risk_level or "medium"),
            )

        if isinstance(capability, SecuritySpec):
            return capability

        if isinstance(capability, dict):
            name: str = capability.get("name", capability_name or "")
            if not name:
                raise SecurityError(
                    "Capability dict must contain a 'name' key."
                )
            return SecuritySpec(
                name=name,
                risk=SecurityRisk.from_str(
                    capability.get("risk", risk_level or "medium")
                ),
                permissions_required=list(capability.get("permissions_required", [])),
                review_required=bool(capability.get("review_required", False)),
                allowed_contexts=list(capability.get("allowed_contexts", [])),
            )

        raise SecurityError(
            f"Unsupported capability type: {type(capability).__name__}. "
            "Expected SecuritySpec, dict, or None."
        )

    @staticmethod
    def _matches_rules(
        capability_name: str,
        rules: Any,
        context: dict[str, Any],
    ) -> bool:
        """Check if *capability_name* matches a list of rule patterns.

        *rules* can be:
        - A list of glob patterns (match capability name).
        - A dict with ``"capabilities"`` (list of globs) and optional
          ``"context"`` constraints.

        Context matching uses simple key-value equality checks against
        the *context* dict.
        """
        if isinstance(rules, list):
            for pattern in rules:
                if fnmatch(capability_name, pattern):
                    return True
            return False

        if isinstance(rules, dict):
            caps: list[str] = rules.get("capabilities", [])
            cap_match = any(
                fnmatch(capability_name, p) for p in caps
            ) if caps else True

            if not cap_match:
                return False

            ctx_rules: dict[str, Any] = rules.get("context", {})
            if ctx_rules:
                for key, expected in ctx_rules.items():
                    actual = context.get(key)
                    if isinstance(expected, list):
                        if actual not in expected:
                            return False
                    else:
                        if actual != expected:
                            return False
            return True

        return False

    @staticmethod
    def _context_allowed(
        context: dict[str, Any],
        allowed_contexts: list[str],
    ) -> bool:
        """Check if the context keys in *context* match *allowed_contexts*.

        *allowed_contexts* is a list of glob patterns matched against each
        context key. If *allowed_contexts* is empty, all contexts are
        allowed.
        """
        if not allowed_contexts:
            return True

        # If no context is provided but the spec restricts it, fail closed
        if not context:
            return False

        for key in context:
            for pattern in allowed_contexts:
                if fnmatch(key, pattern):
                    return True
        return False
