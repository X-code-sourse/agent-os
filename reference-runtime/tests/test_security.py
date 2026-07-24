"""
Intent OS — Security Manager Tests (SPEC-0004 Control Plane)

Comprehensive test suite covering:
  1. Policy data model construction and serialization
  2. PolicyStore: create, get, list, delete policies
  3. PolicyStore: pattern matching (glob to capability names)
  4. SecurityManager: evaluate with ALLOW outcome
  5. SecurityManager: evaluate with DENY outcome
  6. SecurityManager: evaluate with REQUIRE_REVIEW
  7. SecurityManager: evaluate with no matching policy (defaults)
  8. SecurityManager: event emission on evaluation
  9. Policy versioning and updates
  10. Edge cases: empty policies, malformed patterns, missing capabilities
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.models import EventType
from core.security import (
    SecurityDecision,
    SecurityError,
    SecurityManager,
    SecurityRisk,
    SecuritySpec,
    Policy,
    PolicyStore,
    EvaluationResult,
)


# ====================================================================
# Helpers
# ====================================================================

def make_policy(
    *,
    policy_id: str = "pol-test",
    target_patterns: list[str] | None = None,
    risk_overrides: dict[str, str] | None = None,
    permissions: list[str] | None = None,
    review_rules: dict[str, Any] | None = None,
    description: str = "",
    enabled: bool = True,
    version: int = 1,
) -> Policy:
    """Build a Policy with sensible defaults for testing."""
    return Policy(
        policy_id=policy_id,
        target_patterns=target_patterns or ["*"],
        risk_overrides=risk_overrides or {},
        permissions=permissions or [],
        review_rules=review_rules or {},
        description=description,
        enabled=enabled,
        version=version,
    )


def make_spec(
    name: str = "test.cap",
    risk: str | SecurityRisk = "medium",
    permissions_required: list[str] | None = None,
    review_required: bool = False,
    allowed_contexts: list[str] | None = None,
) -> SecuritySpec:
    """Build a SecuritySpec with sensible defaults."""
    return SecuritySpec(
        name=name,
        risk=SecurityRisk.from_str(risk) if isinstance(risk, str) else risk,
        permissions_required=permissions_required or [],
        review_required=review_required,
        allowed_contexts=allowed_contexts or [],
    )


@pytest.fixture
def db_path() -> str:
    """Provide a temporary SQLite database path, cleaned up after the test."""
    path = tempfile.mktemp(suffix=".db")
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def store(db_path: str) -> PolicyStore:
    """Provide a clean PolicyStore backed by a temp DB."""
    return PolicyStore(db_path)


@pytest.fixture
def manager(store: PolicyStore) -> SecurityManager:
    """Provide a SecurityManager with no event store."""
    return SecurityManager(policy_store=store, event_store=None)


@pytest.fixture
def manager_with_events(store: PolicyStore) -> tuple[SecurityManager, MagicMock]:
    """Provide a SecurityManager wired to a mock EventStore.

    Returns (manager, mock_event_store) so callers can assert on events.
    """
    event_store = MagicMock()
    manager = SecurityManager(policy_store=store, event_store=event_store)
    return manager, event_store


# ====================================================================
# 1. Policy data model construction and serialization
# ====================================================================

class TestPolicyModel:
    """Policy dataclass — construction, matching, risk overrides, dict I/O."""

    # ── Construction and defaults ──

    def test_default_values(self):
        """Policy constructed with minimal args gets sensible defaults."""
        p = Policy(policy_id="pol-empty")
        assert p.policy_id == "pol-empty"
        assert p.target_patterns == []
        assert p.risk_overrides == {}
        assert p.permissions == []
        assert p.review_rules == {}
        assert p.version == 1
        assert p.description == ""
        assert p.enabled is True
        assert p.created_at
        assert p.updated_at

    def test_construction_with_all_fields(self):
        """All fields set at construction time are preserved."""
        p = Policy(
            policy_id="pol-full",
            target_patterns=["file.*", "network.*"],
            risk_overrides={"file.delete": "critical"},
            permissions=["file:write"],
            review_rules={"require_review_for": ["high"]},
            version=5,
            description="Full policy",
            enabled=False,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-06-01T00:00:00",
        )
        assert p.policy_id == "pol-full"
        assert p.target_patterns == ["file.*", "network.*"]
        assert p.risk_overrides == {"file.delete": "critical"}
        assert p.permissions == ["file:write"]
        assert p.review_rules == {"require_review_for": ["high"]}
        assert p.version == 5
        assert p.description == "Full policy"
        assert p.enabled is False
        assert p.created_at == "2024-01-01T00:00:00"
        assert p.updated_at == "2024-06-01T00:00:00"

    # ── Pattern / name matching ──

    def test_matches_simple_pattern(self):
        p = make_policy(target_patterns=["file.*"])
        assert p.matches("file.read")
        assert p.matches("file.write")
        assert not p.matches("network.connect")

    def test_matches_multiple_patterns(self):
        p = make_policy(target_patterns=["file.*", "network.*"])
        assert p.matches("file.read")
        assert p.matches("network.connect")
        assert not p.matches("system.shutdown")

    def test_matches_empty_patterns(self):
        """A policy with no target patterns matches nothing."""
        p = Policy(policy_id="empty-patterns", target_patterns=[])
        assert not p.matches("anything")

    def test_matches_wildcard_pattern(self):
        p = make_policy(target_patterns=["*"])
        assert p.matches("anything.at.all")

    def test_matches_case_sensitive(self):
        """fnmatch is case-sensitive on most platforms — verify."""
        p = make_policy(target_patterns=["File.*"])
        assert p.matches("File.read")
        # Case difference: depends on platform, but fnmatch is filesystem-like
        # so we just verify it matches what it should

    def test_matches_dot_pattern(self):
        p = make_policy(target_patterns=["data.*.write"])
        assert p.matches("data.file.write")
        assert p.matches("data.db.write")
        assert not p.matches("data.file.read")
        assert not p.matches("datafile.write")

    # ── Effective risk ──

    def test_effective_risk_no_override(self):
        p = make_policy(risk_overrides={})
        assert p.effective_risk("file.read", SecurityRisk.LOW) == SecurityRisk.LOW
        assert p.effective_risk("file.read", SecurityRisk.CRITICAL) == SecurityRisk.CRITICAL

    def test_effective_risk_with_override(self):
        p = make_policy(risk_overrides={"file.delete": "critical"})
        assert p.effective_risk("file.read", SecurityRisk.LOW) == SecurityRisk.LOW
        assert p.effective_risk("file.delete", SecurityRisk.MEDIUM) == SecurityRisk.CRITICAL

    def test_effective_risk_override_pattern_matching(self):
        """Override patterns support glob matching."""
        p = make_policy(risk_overrides={"file.*": "high"})
        assert p.effective_risk("file.read", SecurityRisk.LOW) == SecurityRisk.HIGH
        assert p.effective_risk("file.write", SecurityRisk.MEDIUM) == SecurityRisk.HIGH
        assert p.effective_risk("network.connect", SecurityRisk.LOW) == SecurityRisk.LOW

    def test_effective_risk_first_override_wins(self):
        """When multiple overrides match, the first in dict order is used."""
        p = make_policy(risk_overrides={
            "file.*": "high",
            "file.delete": "critical",
        })
        # "file.*" is checked first (insertion order), so file.delete gets "high"
        assert p.effective_risk("file.delete", SecurityRisk.LOW) == SecurityRisk.HIGH

    # ── Dict serialization round-trip ──

    def test_to_dict_round_trip(self):
        p = Policy(
            policy_id="pol-rt",
            target_patterns=["a.*", "b.*"],
            risk_overrides={"a.delete": "high"},
            permissions=["perm1"],
            review_rules={"require_review_for": ["high"]},
            version=3,
            description="Test round-trip",
            enabled=False,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-06-01T00:00:00",
        )
        d = p.to_dict()
        p2 = Policy.from_dict(d)
        assert p2.policy_id == p.policy_id
        assert p2.target_patterns == p.target_patterns
        assert p2.risk_overrides == p.risk_overrides
        assert p2.permissions == p.permissions
        assert p2.review_rules == p.review_rules
        assert p2.version == p.version
        assert p2.description == p.description
        assert p2.enabled == p.enabled
        assert p2.created_at == p.created_at
        assert p2.updated_at == p.updated_at

    def test_to_dict_auto_timestamps(self):
        p = make_policy()
        d = p.to_dict()
        assert "created_at" in d
        assert "updated_at" in d
        assert d["policy_id"] == "pol-test"

    def test_from_dict_minimal(self):
        """from_dict works with just a policy_id."""
        p = Policy.from_dict({"policy_id": "pol-min"})
        assert p.policy_id == "pol-min"
        assert p.target_patterns == []
        assert p.version == 1
        assert p.enabled is True

    def test_from_dict_missing_keys_uses_defaults(self):
        """from_dict supplies sensible defaults for missing optional keys."""
        p = Policy.from_dict({"policy_id": "pol-def"})
        assert p.risk_overrides == {}
        assert p.permissions == []
        assert p.review_rules == {}
        assert p.description == ""
        assert p.target_patterns == []

    def test_to_dict_serializable(self):
        """to_dict produces JSON-serializable output."""
        p = make_policy(
            policy_id="pol-json",
            target_patterns=["a.*"],
            risk_overrides={"a.b": "high"},
            review_rules={"allow": ["a.c"]},
            permissions=["p1"],
        )
        d = p.to_dict()
        # Should not raise
        json.dumps(d)

    # ── SecuritySpec serialization ──

    def test_security_spec_to_dict(self):
        spec = SecuritySpec(
            name="file.write",
            risk=SecurityRisk.HIGH,
            permissions_required=["file:write"],
            review_required=True,
            allowed_contexts=["source_ip"],
        )
        d = spec.to_dict()
        assert d["name"] == "file.write"
        assert d["risk"] == "high"
        assert d["permissions_required"] == ["file:write"]
        assert d["review_required"] is True
        assert d["allowed_contexts"] == ["source_ip"]

    def test_security_spec_from_dict(self):
        spec = SecuritySpec.from_dict({
            "name": "file.write",
            "risk": "high",
            "permissions_required": ["file:write"],
            "review_required": True,
            "allowed_contexts": ["source_ip"],
        })
        assert spec.name == "file.write"
        assert spec.risk == SecurityRisk.HIGH
        assert spec.permissions_required == ["file:write"]
        assert spec.review_required is True
        assert spec.allowed_contexts == ["source_ip"]

    def test_security_spec_from_dict_minimal(self):
        spec = SecuritySpec.from_dict({"name": "test"})
        assert spec.name == "test"
        assert spec.risk == SecurityRisk.MEDIUM  # default
        assert spec.permissions_required == []
        assert spec.review_required is False
        assert spec.allowed_contexts == []

    def test_security_spec_to_dict_round_trip(self):
        spec = SecuritySpec(
            name="net.connect",
            risk=SecurityRisk.LOW,
            permissions_required=["net:connect"],
            review_required=True,
            allowed_contexts=["source_ip", "user_role"],
        )
        d = spec.to_dict()
        spec2 = SecuritySpec.from_dict(d)
        assert spec2.name == spec.name
        assert spec2.risk == spec.risk
        assert spec2.permissions_required == spec.permissions_required
        assert spec2.review_required == spec.review_required
        assert spec2.allowed_contexts == spec.allowed_contexts


# ====================================================================
# 2. PolicyStore: create, get, list, delete policies (CRUD)
# ====================================================================

class TestPolicyStoreCrud:
    """SQLite-backed PolicyStore — create, read, list, delete operations."""

    # ── Empty store / negative lookups ──

    def test_count_empty(self, store: PolicyStore):
        assert store.count() == 0

    def test_list_empty(self, store: PolicyStore):
        assert store.list_all() == []

    def test_get_nonexistent(self, store: PolicyStore):
        assert store.get("no-such-policy") is None

    def test_delete_nonexistent(self, store: PolicyStore):
        assert store.delete("no-such") is False

    # ── Insert (create) ──

    def test_insert_and_retrieve(self, store: PolicyStore):
        p = make_policy(policy_id="pol-a", target_patterns=["test.*"])
        store.upsert(p)
        retrieved = store.get("pol-a")
        assert retrieved is not None
        assert retrieved.policy_id == "pol-a"
        assert retrieved.target_patterns == ["test.*"]
        assert retrieved.version == 1

    def test_insert_multiple_and_count(self, store: PolicyStore):
        store.upsert(make_policy(policy_id="p1", target_patterns=["a.*"]))
        store.upsert(make_policy(policy_id="p2", target_patterns=["b.*"]))
        store.upsert(make_policy(policy_id="p3", target_patterns=["c.*"]))
        assert store.count() == 3

    def test_insert_preserves_all_fields(self, store: PolicyStore):
        p = Policy(
            policy_id="pol-full",
            target_patterns=["x.*", "y.*"],
            risk_overrides={"x.delete": "critical"},
            permissions=["x:write"],
            review_rules={"require_review_for": ["critical"]},
            description="Full insert test",
            enabled=False,
        )
        store.upsert(p)
        retrieved = store.get("pol-full")
        assert retrieved is not None
        assert retrieved.target_patterns == ["x.*", "y.*"]
        assert retrieved.risk_overrides == {"x.delete": "critical"}
        assert retrieved.permissions == ["x:write"]
        assert retrieved.review_rules == {"require_review_for": ["critical"]}
        assert retrieved.description == "Full insert test"
        assert retrieved.enabled is False
        assert retrieved.version == 1

    # ── List ──

    def test_list_all_returns_all(self, store: PolicyStore):
        store.upsert(make_policy(policy_id="a", target_patterns=["a.*"], enabled=True))
        store.upsert(make_policy(policy_id="b", target_patterns=["b.*"], enabled=False))
        all_p = store.list_all()
        ids = [p.policy_id for p in all_p]
        assert "a" in ids
        assert "b" in ids  # disabled policies included in list_all
        assert len(all_p) == 2

    def test_list_all_insertion_order(self, store: PolicyStore):
        """list_all returns policies in insertion order."""
        store.upsert(make_policy(policy_id="z", target_patterns=["z.*"]))
        store.upsert(make_policy(policy_id="a", target_patterns=["a.*"]))
        store.upsert(make_policy(policy_id="m", target_patterns=["m.*"]))
        ids = [p.policy_id for p in store.list_all()]
        assert ids == ["z", "a", "m"]

    # ── Delete ──

    def test_delete_existing(self, store: PolicyStore):
        store.upsert(make_policy(policy_id="pol-del", target_patterns=["del.*"]))
        assert store.count() == 1
        assert store.delete("pol-del") is True
        assert store.count() == 0
        assert store.get("pol-del") is None

    def test_delete_idempotent(self, store: PolicyStore):
        """Deleting an already-deleted policy returns False."""
        store.upsert(make_policy(policy_id="d", target_patterns=["d.*"]))
        assert store.delete("d") is True
        assert store.delete("d") is False

    def test_delete_does_not_affect_others(self, store: PolicyStore):
        store.upsert(make_policy(policy_id="keep", target_patterns=["keep.*"]))
        store.upsert(make_policy(policy_id="remove", target_patterns=["rm.*"]))
        store.delete("remove")
        assert store.count() == 1
        assert store.get("keep") is not None

    # ── Connection management ──

    def test_close_and_reopen(self, db_path: str):
        store = PolicyStore(db_path)
        store.upsert(make_policy(policy_id="persist", target_patterns=["p.*"]))
        store.close()

        store2 = PolicyStore(db_path)
        p = store2.get("persist")
        assert p is not None
        assert p.policy_id == "persist"
        store2.close()

    def test_context_manager(self, db_path: str):
        with PolicyStore(db_path) as s:
            s.upsert(make_policy(policy_id="cm", target_patterns=["cm.*"]))
            assert s.count() == 1
        # Connection closed after exit — no explicit assertion, just no hang

    def test_multiple_instances_same_db(self, db_path: str):
        """Two PolicyStore instances pointing at the same DB see each other's writes."""
        s1 = PolicyStore(db_path)
        s2 = PolicyStore(db_path)

        s1.upsert(make_policy(policy_id="shared", target_patterns=["shared.*"]))
        p = s2.get("shared")
        assert p is not None
        assert p.policy_id == "shared"

        s1.close()
        s2.close()


# ====================================================================
# 3. PolicyStore: pattern matching (glob to capability names)
# ====================================================================

class TestPolicyStorePatternMatching:
    """PolicyStore.get_for_capability glob matching."""

    def test_exact_match(self, store: PolicyStore):
        store.upsert(make_policy(policy_id="exact", target_patterns=["file.read"]))
        matches = store.get_for_capability("file.read")
        assert len(matches) == 1
        assert matches[0].policy_id == "exact"

    def test_wildcard_match(self, store: PolicyStore):
        store.upsert(make_policy(policy_id="wild", target_patterns=["file.*"]))
        matches = store.get_for_capability("file.write")
        assert len(matches) == 1
        assert matches[0].policy_id == "wild"

    def test_universal_wildcard(self, store: PolicyStore):
        store.upsert(make_policy(policy_id="all", target_patterns=["*"]))
        assert len(store.get_for_capability("anything")) == 1
        assert len(store.get_for_capability("file.read")) == 1
        assert len(store.get_for_capability("network.connect")) == 1

    def test_no_match_returns_empty(self, store: PolicyStore):
        store.upsert(make_policy(policy_id="file-pol", target_patterns=["file.*"]))
        matches = store.get_for_capability("network.connect")
        assert matches == []

    def test_multiple_matching_policies(self, store: PolicyStore):
        """Multiple policies can match the same capability."""
        store.upsert(make_policy(policy_id="broad", target_patterns=["data.*"]))
        store.upsert(make_policy(policy_id="specific", target_patterns=["data.write"]))
        matches = store.get_for_capability("data.write")
        assert len(matches) == 2
        assert {m.policy_id for m in matches} == {"broad", "specific"}

    def test_disabled_policy_excluded(self, store: PolicyStore):
        """Disabled policies are not returned by get_for_capability."""
        store.upsert(make_policy(
            policy_id="disabled", target_patterns=["*"], enabled=False,
        ))
        matches = store.get_for_capability("anything")
        assert matches == []

    def test_mixed_enabled_disabled(self, store: PolicyStore):
        """Only enabled policies are returned when both enabled and disabled match."""
        store.upsert(make_policy(
            policy_id="enabled", target_patterns=["data.*"], enabled=True,
        ))
        store.upsert(make_policy(
            policy_id="disabled", target_patterns=["data.*"], enabled=False,
        ))
        matches = store.get_for_capability("data.read")
        assert len(matches) == 1
        assert matches[0].policy_id == "enabled"

    def test_context_parameter_accepted(self, store: PolicyStore):
        """The context parameter is accepted but currently not used for filtering."""
        store.upsert(make_policy(policy_id="ctx-pol", target_patterns=["ctx.*"]))
        matches = store.get_for_capability("ctx.test", {"user": "admin", "ip": "10.0.0.1"})
        assert len(matches) == 1

    def test_partial_wildcard_in_middle(self, store: PolicyStore):
        """Patterns with wildcards in non-standard positions work."""
        store.upsert(make_policy(policy_id="mid", target_patterns=["data.*.write"]))
        assert len(store.get_for_capability("data.file.write")) == 1
        assert len(store.get_for_capability("data.db.write")) == 1
        assert len(store.get_for_capability("data.file.read")) == 0

    def test_char_class_pattern(self, store: PolicyStore):
        """fnmatch supports character classes like [abc]."""
        store.upsert(make_policy(policy_id="cc", target_patterns=["file.[rw]*"]))
        assert len(store.get_for_capability("file.read")) == 1
        assert len(store.get_for_capability("file.write")) == 1
        assert len(store.get_for_capability("file.delete")) == 0


# ====================================================================
# 4. SecurityManager: evaluate with ALLOW outcome
# ====================================================================

class TestEvaluateAllow:
    """SecurityManager.evaluate() producing ALLOW decisions."""

    def test_allow_matching_policy(self, manager: SecurityManager, store: PolicyStore):
        """A capability covered by a policy with no restrictions is allowed."""
        store.upsert(make_policy(policy_id="p1", target_patterns=["safe.*"]))
        result = manager.evaluate({"name": "safe.read", "risk": "low"})
        assert result.decision == SecurityDecision.ALLOW
        assert result.policy_id == "p1"
        assert result.capability_name == "safe.read"

    def test_allow_no_review_rules(self, manager: SecurityManager, store: PolicyStore):
        """Policy with empty review_rules allows matching capabilities."""
        store.upsert(make_policy(
            policy_id="p-open", target_patterns=["open.*"], review_rules={},
        ))
        result = manager.evaluate({"name": "open.api", "risk": "high"})
        assert result.decision == SecurityDecision.ALLOW

    def test_allow_explicit_allow_rule(self, manager: SecurityManager, store: PolicyStore):
        """Explicit 'allow' in review_rules permits the capability."""
        store.upsert(make_policy(
            policy_id="p-allow", target_patterns=["api.*"],
            review_rules={"allow": ["api.public"]},
        ))
        result = manager.evaluate({"name": "api.public", "risk": "medium"})
        assert result.decision == SecurityDecision.ALLOW
        assert "explicit allow" in result.rationale

    def test_allow_low_risk_below_threshold(self, manager: SecurityManager, store: PolicyStore):
        """Risk below the review threshold passes through to ALLOW."""
        store.upsert(make_policy(
            policy_id="p-thresh", target_patterns=["thresh.*"],
            review_rules={"require_review_for": ["critical"]},
        ))
        result = manager.evaluate({"name": "thresh.normal", "risk": "medium"})
        assert result.decision == SecurityDecision.ALLOW

    def test_allow_no_policy_default_allowed_by_policy(self, manager: SecurityManager, store: PolicyStore):
        """When a matching policy exists, default is ALLOW (not DENY)."""
        store.upsert(make_policy(policy_id="catchall", target_patterns=["*"]))
        result = manager.evaluate({"name": "anything", "risk": "low"})
        assert result.decision == SecurityDecision.ALLOW

    def test_allow_context_pass(self, manager: SecurityManager, store: PolicyStore):
        """When context matches allowed_contexts, the capability is allowed."""
        store.upsert(make_policy(policy_id="ctx-p", target_patterns=["ctx.*"]))
        result = manager.evaluate(
            {"name": "ctx.test", "risk": "low", "allowed_contexts": ["source_ip"]},
            {"source_ip": "10.0.0.1"},
        )
        assert result.decision == SecurityDecision.ALLOW

    def test_allow_empty_allowed_contexts(self, manager: SecurityManager, store: PolicyStore):
        """Empty allowed_contexts means no context restriction — allow."""
        store.upsert(make_policy(policy_id="any-p", target_patterns=["*"]))
        result = manager.evaluate(
            {"name": "x", "risk": "low", "allowed_contexts": []},
            {"anything": "goes"},
        )
        assert result.decision == SecurityDecision.ALLOW

    def test_allow_with_security_spec_object(self, manager: SecurityManager, store: PolicyStore):
        """SecuritySpec object as input works correctly."""
        store.upsert(make_policy(policy_id="spec-p", target_patterns=["spec.*"]))
        spec = SecuritySpec(name="spec.action", risk=SecurityRisk.LOW)
        result = manager.evaluate(spec)
        assert result.decision == SecurityDecision.ALLOW
        assert result.capability_name == "spec.action"

    def test_allow_capability_name_kwargs(self, manager: SecurityManager, store: PolicyStore):
        """evaluate() with capability_name kwarg and no matching policy still denies,
        but with a matching policy it allows."""
        store.upsert(make_policy(policy_id="kw-p", target_patterns=["test.*"]))
        result = manager.evaluate(capability_name="test.api", risk_level="low")
        assert result.decision == SecurityDecision.ALLOW
        assert result.policy_id == "kw-p"

    def test_allow_dict_without_risk_key(self, manager: SecurityManager, store: PolicyStore):
        """A dict without a 'risk' key defaults to medium risk and can be allowed."""
        store.upsert(make_policy(
            policy_id="norisk", target_patterns=["safe.*"],
            review_rules={"require_review_for": ["high", "critical"]},
        ))
        result = manager.evaluate({"name": "safe.action"})
        assert result.decision == SecurityDecision.ALLOW
        assert result.risk_level == "medium"


# ====================================================================
# 5. SecurityManager: evaluate with DENY outcome
# ====================================================================

class TestEvaluateDeny:
    """SecurityManager.evaluate() producing DENY decisions.

    DENY occurs when:
    - An explicit deny rule matches the capability.
    - No matching policy exists (default deny).
    - Context restrictions are not met.
    - A deny rule wins over an allow rule for the same capability.
    """

    def test_deny_no_matching_policy(self, manager: SecurityManager):
        """No matching policy in an empty store results in DENY."""
        result = manager.evaluate({"name": "unknown.cap", "risk": "low"})
        assert result.decision == SecurityDecision.DENY
        assert result.policy_id is None
        assert "No matching policy" in result.rationale

    def test_deny_explicit_deny_rule(self, manager: SecurityManager, store: PolicyStore):
        """An explicit deny rule in a matching policy returns DENY."""
        store.upsert(make_policy(
            policy_id="p-deny", target_patterns=["blocked.*"],
            review_rules={"deny": ["blocked.*"]},
        ))
        result = manager.evaluate({"name": "blocked.all", "risk": "low"})
        assert result.decision == SecurityDecision.DENY
        assert "explicit deny" in result.rationale
        assert result.policy_id == "p-deny"

    def test_deny_wins_over_allow(self, manager: SecurityManager, store: PolicyStore):
        """When two policies match, DENY beats ALLOW."""
        store.upsert(make_policy(
            policy_id="allow-all", target_patterns=["data.*"],
            review_rules={"allow": ["data.*"]},
        ))
        store.upsert(make_policy(
            policy_id="deny-specific", target_patterns=["data.delete"],
            review_rules={"deny": ["data.delete"]},
        ))
        result = manager.evaluate({"name": "data.delete", "risk": "low"})
        assert result.decision == SecurityDecision.DENY
        assert result.policy_id == "deny-specific"

    def test_deny_wins_over_review_required(self, manager: SecurityManager, store: PolicyStore):
        """Explicit DENY in policy overrides spec.review_required."""
        store.upsert(make_policy(
            policy_id="p-deny2", target_patterns=["blocked.*"],
            review_rules={"deny": ["blocked.*"]},
        ))
        result = manager.evaluate(
            SecuritySpec(name="blocked.all", risk=SecurityRisk.LOW, review_required=True)
        )
        assert result.decision == SecurityDecision.DENY
        assert result.policy_id == "p-deny2"

    def test_deny_default_after_policy_deleted(self, manager: SecurityManager, store: PolicyStore):
        """Deleting the only matching policy causes default deny."""
        store.upsert(make_policy(policy_id="tmp", target_patterns=["tmp.*"]))
        store.delete("tmp")
        result = manager.evaluate({"name": "tmp.test", "risk": "low"})
        assert result.decision == SecurityDecision.DENY
        assert result.policy_id is None

    def test_deny_context_restriction(self, manager: SecurityManager, store: PolicyStore):
        """A context restriction that does not match returns DENY."""
        store.upsert(make_policy(policy_id="p-ctx", target_patterns=["ctx.*"]))
        result = manager.evaluate(
            {"name": "ctx.test", "risk": "low", "allowed_contexts": ["internal_ip"]},
            {"source_ip": "external"},
        )
        assert result.decision == SecurityDecision.DENY
        assert "context" in result.rationale

    def test_deny_context_restriction_no_context(self, manager: SecurityManager, store: PolicyStore):
        """When spec restricts context but no context is passed, deny (fail closed)."""
        store.upsert(make_policy(policy_id="ctx-p2", target_patterns=["x.*"]))
        result = manager.evaluate(
            {"name": "x.test", "risk": "low", "allowed_contexts": ["internal_ip"]},
        )
        assert result.decision == SecurityDecision.DENY

    def test_deny_disabled_policy(self, manager: SecurityManager, store: PolicyStore):
        """A disabled policy is treated as non-existent, resulting in DENY."""
        store.upsert(make_policy(
            policy_id="p-disabled", target_patterns=["*"], enabled=False,
        ))
        result = manager.evaluate({"name": "anything", "risk": "low"})
        assert result.decision == SecurityDecision.DENY
        assert result.policy_id is None

    def test_deny_with_context_aware_deny_rule(self, manager: SecurityManager, store: PolicyStore):
        """DENY rule with context constraints denies only when context matches."""
        store.upsert(make_policy(
            policy_id="ctx-deny", target_patterns=["api.*"],
            review_rules={
                "deny": {
                    "capabilities": ["api.admin"],
                    "context": {"user_role": "guest"},
                },
            },
        ))
        # Guest role matches the context deny rule → DENY
        result = manager.evaluate(
            {"name": "api.admin", "risk": "medium"},
            {"user_role": "guest"},
        )
        assert result.decision == SecurityDecision.DENY

        # Admin role does not match the context deny rule → falls through
        result2 = manager.evaluate(
            {"name": "api.admin", "risk": "medium"},
            {"user_role": "admin"},
        )
        assert result2.decision == SecurityDecision.ALLOW


# ====================================================================
# 6. SecurityManager: evaluate with REQUIRE_REVIEW
# ====================================================================

class TestEvaluateRequireReview:
    """SecurityManager.evaluate() producing REQUIRE_REVIEW decisions.

    REQUIRE_REVIEW occurs when:
    - The effective risk level is in the policy's require_review_for list.
    - The capability's spec has review_required=True.
    """

    def test_require_review_risk_threshold(self, manager: SecurityManager, store: PolicyStore):
        """Risk at or above the review threshold triggers REQUIRE_REVIEW."""
        store.upsert(make_policy(
            policy_id="p-review", target_patterns=["risky.*"],
            review_rules={"require_review_for": ["high", "critical"]},
        ))
        result = manager.evaluate({"name": "risky.action", "risk": "high"})
        assert result.decision == SecurityDecision.REQUIRE_REVIEW
        assert "requires review" in result.rationale
        assert result.risk_level == "high"
        assert result.policy_id == "p-review"

    def test_require_review_critical_risk(self, manager: SecurityManager, store: PolicyStore):
        """Critical risk triggers REQUIRE_REVIEW when in the review list."""
        store.upsert(make_policy(
            policy_id="p-crit", target_patterns=["critical.*"],
            review_rules={"require_review_for": ["critical"]},
        ))
        result = manager.evaluate({"name": "critical.action", "risk": "critical"})
        assert result.decision == SecurityDecision.REQUIRE_REVIEW
        assert result.risk_level == "critical"

    def test_require_review_risk_override_triggers(self, manager: SecurityManager, store: PolicyStore):
        """Risk override can elevate a medium-risk capability into review territory."""
        store.upsert(make_policy(
            policy_id="p-ovr", target_patterns=["file.*"],
            risk_overrides={"file.delete": "critical"},
            review_rules={"require_review_for": ["critical"]},
        ))
        result = manager.evaluate({"name": "file.delete", "risk": "medium"})
        assert result.decision == SecurityDecision.REQUIRE_REVIEW
        assert result.risk_level == "critical"

    def test_require_review_spec_flag_no_policy(self, manager: SecurityManager):
        """A capability with review_required=True requires review even without policies."""
        result = manager.evaluate(
            SecuritySpec(name="sensitive.view", risk=SecurityRisk.LOW, review_required=True)
        )
        assert result.decision == SecurityDecision.REQUIRE_REVIEW
        assert "mandatory review" in result.rationale
        assert result.policy_id is None

    def test_require_review_spec_flag_with_policy(self, manager: SecurityManager, store: PolicyStore):
        """review_required on the spec also triggers when a policy matches."""
        store.upsert(make_policy(policy_id="p-safe", target_patterns=["sensitive.*"]))
        result = manager.evaluate(
            SecuritySpec(name="sensitive.read", risk=SecurityRisk.LOW, review_required=True)
        )
        assert result.decision == SecurityDecision.REQUIRE_REVIEW
        assert "mandatory review" in result.rationale

    def test_require_review_spec_via_dict(self, manager: SecurityManager, store: PolicyStore):
        """review_required=True passed via dict triggers REQUIRE_REVIEW."""
        store.upsert(make_policy(policy_id="p-all", target_patterns=["*"]))
        result = manager.evaluate(
            {"name": "my.cap", "risk": "low", "review_required": True},
        )
        assert result.decision == SecurityDecision.REQUIRE_REVIEW

    def test_require_review_takes_precedence_over_default_allow(self, manager: SecurityManager, store: PolicyStore):
        """REQUIRE_REVIEW from risk threshold beats the default ALLOW."""
        store.upsert(make_policy(
            policy_id="p-thresh", target_patterns=["risky.*"],
            review_rules={"require_review_for": ["high"]},
        ))
        result = manager.evaluate({"name": "risky.op", "risk": "high"})
        assert result.decision == SecurityDecision.REQUIRE_REVIEW

    def test_require_review_multiple_policies_first_match(self, manager: SecurityManager, store: PolicyStore):
        """When multiple policies match, each policy's thresholds are checked."""
        store.upsert(make_policy(
            policy_id="no-review", target_patterns=["data.*"],
            review_rules={},
        ))
        store.upsert(make_policy(
            policy_id="with-review", target_patterns=["data.*"],
            review_rules={"require_review_for": ["high"]},
        ))
        # Both policies match. "no-review" has no threshold so the loop continues.
        # "with-review" has require_review_for: ["high"] and risk is "high" → REVIEW.
        result = manager.evaluate({"name": "data.write", "risk": "high"})
        assert result.decision == SecurityDecision.REQUIRE_REVIEW
        assert result.policy_id == "with-review"

    def test_require_review_not_exceeded_passes(self, manager: SecurityManager, store: PolicyStore):
        """Risk below the threshold is not flagged for review."""
        store.upsert(make_policy(
            policy_id="p-low", target_patterns=["low.*"],
            review_rules={"require_review_for": ["critical"]},
        ))
        result = manager.evaluate({"name": "low.risk", "risk": "medium"})
        assert result.decision == SecurityDecision.ALLOW
        assert result.risk_level == "medium"


# ====================================================================
# 7. SecurityManager: evaluate with no matching policy (use defaults)
# ====================================================================

class TestEvaluateDefaults:
    """SecurityManager default behaviour when no policy matches.

    The default security posture is deny-by-default: if no enabled policy
    matches a capability, the decision is DENY with no policy_id.
    """

    def test_no_policies_in_store(self, manager: SecurityManager):
        """Empty store → DENY with no policy_id."""
        result = manager.evaluate({"name": "anything", "risk": "low"})
        assert result.decision == SecurityDecision.DENY
        assert result.policy_id is None
        assert "No matching policy" in result.rationale

    def test_no_matching_policy_in_populated_store(self, manager: SecurityManager, store: PolicyStore):
        """Store has policies but none match → DENY."""
        store.upsert(make_policy(policy_id="net", target_patterns=["network.*"]))
        store.upsert(make_policy(policy_id="file", target_patterns=["file.*"]))
        result = manager.evaluate({"name": "system.shutdown", "risk": "critical"})
        assert result.decision == SecurityDecision.DENY
        assert result.policy_id is None

    def test_default_with_capability_name_kwarg(self, manager: SecurityManager):
        """No policies, evaluate via capability_name kwarg → DENY."""
        result = manager.evaluate(capability_name="test.api", risk_level="high")
        assert result.decision == SecurityDecision.DENY
        assert result.policy_id is None

    def test_default_with_security_spec(self, manager: SecurityManager):
        """No policies, evaluate via SecuritySpec → DENY."""
        spec = SecuritySpec(name="my.cap", risk=SecurityRisk.CRITICAL)
        result = manager.evaluate(spec)
        assert result.decision == SecurityDecision.DENY
        assert result.policy_id is None

    def test_default_deny_still_records_risk_level(self, manager: SecurityManager):
        """Even when no policy matches, the risk level is reported correctly."""
        result = manager.evaluate({"name": "test", "risk": "critical"})
        assert result.decision == SecurityDecision.DENY
        assert result.risk_level == "critical"
        assert result.capability_name == "test"

    def test_default_deny_after_all_policies_disabled(self, manager: SecurityManager, store: PolicyStore):
        """All policies exist but are disabled → effectively no matching policy → DENY."""
        store.upsert(make_policy(policy_id="a", target_patterns=["*"], enabled=False))
        store.upsert(make_policy(policy_id="b", target_patterns=["*"], enabled=False))
        result = manager.evaluate({"name": "anything", "risk": "low"})
        assert result.decision == SecurityDecision.DENY
        assert result.policy_id is None


# ====================================================================
# 8. SecurityManager: event emission on evaluation
# ====================================================================

class TestEventEmission:
    """SecurityManager emits PolicyEvaluated events for every evaluation."""

    def test_no_event_store_is_safe(self, store: PolicyStore):
        """When event_store is None, evaluate still works without error."""
        manager = SecurityManager(policy_store=store)
        result = manager.evaluate({"name": "test.cap", "risk": "low"})
        assert result is not None
        assert result.decision == SecurityDecision.DENY

    def test_emits_event_on_evaluation(self, store: PolicyStore):
        """An event is saved for every evaluate() call."""
        event_store = MagicMock()
        manager = SecurityManager(policy_store=store, event_store=event_store)
        store.upsert(make_policy(policy_id="p1", target_patterns=["test.*"]))

        manager.evaluate({"name": "test.cap", "risk": "low"}, {"key": "val"})

        assert event_store.save_event.called
        event = event_store.save_event.call_args[0][0]
        assert event.event_type == EventType.POLICY_EVALUATED
        assert event.source == "security_manager"

    def test_event_payload_allow(self, store: PolicyStore):
        """ALLOW decision produces correct event payload."""
        event_store = MagicMock()
        manager = SecurityManager(policy_store=store, event_store=event_store)
        store.upsert(make_policy(policy_id="pol-ok", target_patterns=["safe.*"]))

        manager.evaluate({"name": "safe.op", "risk": "low"})

        event = event_store.save_event.call_args[0][0]
        payload = event.payload
        assert payload is not None
        assert payload["policy_id"] == "pol-ok"
        assert payload["capability"] == "safe.op"
        assert payload["decision"] == "allow"
        assert payload["risk_level"] == "low"

    def test_event_payload_deny(self, store: PolicyStore):
        """DENY decision produces correct event payload."""
        event_store = MagicMock()
        manager = SecurityManager(policy_store=store, event_store=event_store)
        store.upsert(make_policy(
            policy_id="pol-block", target_patterns=["blocked.*"],
            review_rules={"deny": ["blocked.*"]},
        ))

        manager.evaluate({"name": "blocked.all", "risk": "medium"})

        event = event_store.save_event.call_args[0][0]
        payload = event.payload
        assert payload is not None
        assert payload["policy_id"] == "pol-block"
        assert payload["capability"] == "blocked.all"
        assert payload["decision"] == "deny"

    def test_event_payload_review(self, store: PolicyStore):
        """REQUIRE_REVIEW decision produces correct event payload."""
        event_store = MagicMock()
        manager = SecurityManager(policy_store=store, event_store=event_store)
        store.upsert(make_policy(
            policy_id="pol-review", target_patterns=["risky.*"],
            review_rules={"require_review_for": ["high"]},
        ))

        manager.evaluate({"name": "risky.op", "risk": "high"})

        event = event_store.save_event.call_args[0][0]
        payload = event.payload
        assert payload is not None
        assert payload["policy_id"] == "pol-review"
        assert payload["capability"] == "risky.op"
        assert payload["decision"] == "require_review"
        assert "requires review" in payload["rationale"]
        assert payload["risk_level"] == "high"

    def test_event_payload_deny_no_policy(self, store: PolicyStore):
        """DENY from no matching policy has policy_id=None in payload."""
        event_store = MagicMock()
        manager = SecurityManager(policy_store=store, event_store=event_store)

        manager.evaluate({"name": "unknown.x", "risk": "low"})

        event = event_store.save_event.call_args[0][0]
        payload = event.payload
        assert payload is not None
        assert payload["policy_id"] is None
        assert payload["decision"] == "deny"
        assert payload["capability"] == "unknown.x"

    def test_sequence_increments_across_calls(self, store: PolicyStore):
        """Each evaluate() call is independent — no shared sequence counter.

        Since SPEC-0004 R1 requires the SecurityManager to be stateless,
        every evaluation gets its own fresh trace_id and event with
        sequence=1 (a standalone event, not part of a larger trace).
        """
        event_store = MagicMock()
        manager = SecurityManager(policy_store=store, event_store=event_store)

        manager.evaluate({"name": "a", "risk": "low"})
        manager.evaluate({"name": "b", "risk": "low"})
        manager.evaluate({"name": "c", "risk": "low"})

        calls = event_store.save_event.call_args_list
        assert len(calls) == 3
        sequences = [c[0][0].sequence for c in calls]
        assert sequences == [1, 1, 1]  # each is a standalone event

    def test_event_trace_id_included(self, store: PolicyStore):
        """Events carry the manager's trace_id (or a generated UUID)."""
        event_store = MagicMock()
        manager = SecurityManager(policy_store=store, event_store=event_store)

        manager.evaluate({"name": "test", "risk": "low"})

        event = event_store.save_event.call_args[0][0]
        assert event.trace_id is not None
        assert len(event.trace_id) > 0

    def test_event_source_is_security_manager(self, store: PolicyStore):
        """All events originate from source='security_manager'."""
        event_store = MagicMock()
        manager = SecurityManager(policy_store=store, event_store=event_store)

        manager.evaluate({"name": "test", "risk": "low"})

        event = event_store.save_event.call_args[0][0]
        assert event.source == "security_manager"

    def test_multiple_evaluations_all_emitted(self, store: PolicyStore):
        """Multiple evaluate calls each produce a separate event."""
        event_store = MagicMock()
        manager = SecurityManager(policy_store=store, event_store=event_store)

        manager.evaluate({"name": "one", "risk": "low"})
        manager.evaluate({"name": "two", "risk": "low"})
        manager.evaluate({"name": "three", "risk": "low"})

        assert event_store.save_event.call_count == 3


# ====================================================================
# 9. Policy versioning and updates
# ====================================================================

class TestPolicyVersioning:
    """Policy version tracking and update semantics."""

    def test_new_policy_version_1(self, store: PolicyStore):
        """A freshly inserted policy has version 1."""
        p = make_policy(policy_id="pol-new", target_patterns=["a.*"])
        store.upsert(p)
        assert store.get("pol-new").version == 1

    def test_version_bumps_on_update(self, store: PolicyStore):
        """Re-upserting the same policy ID increments version."""
        store.upsert(make_policy(policy_id="pol-v", target_patterns=["v1.*"]))
        v1 = store.get("pol-v")
        assert v1 is not None
        assert v1.version == 1

        store.upsert(make_policy(policy_id="pol-v", target_patterns=["v2.*"]))
        v2 = store.get("pol-v")
        assert v2 is not None
        assert v2.version == 2
        assert v2.target_patterns == ["v2.*"]

    def test_created_at_preserved_on_update(self, store: PolicyStore):
        """created_at is preserved across updates; updated_at is refreshed."""
        store.upsert(make_policy(policy_id="pol-ts", target_patterns=["t1.*"]))
        v1 = store.get("pol-ts")
        original_created = v1.created_at

        store.upsert(make_policy(policy_id="pol-ts", target_patterns=["t2.*"]))
        v2 = store.get("pol-ts")
        assert v2.created_at == original_created  # preserved

    def test_version_always_bumps_regardless_of_data_change(self, store: PolicyStore):
        """Version bumps even when the content is identical."""
        store.upsert(make_policy(policy_id="pol-idem", target_patterns=["same.*"]))
        assert store.get("pol-idem").version == 1

        store.upsert(make_policy(policy_id="pol-idem", target_patterns=["same.*"]))
        assert store.get("pol-idem").version == 2

    def test_version_accumulates_across_multiple_updates(self, store: PolicyStore):
        """Version increments correctly across many updates."""
        p = make_policy(policy_id="pol-acc", target_patterns=["v1.*"])
        for i in range(5):
            p.target_patterns = [f"v{i+1}.*"]
            store.upsert(p)
        assert store.get("pol-acc").version == 5

    def test_versions_independent_per_policy(self, store: PolicyStore):
        """Version counters are independent for different policies."""
        store.upsert(make_policy(policy_id="a", target_patterns=["a.*"]))
        store.upsert(make_policy(policy_id="b", target_patterns=["b.*"]))
        store.upsert(make_policy(policy_id="a", target_patterns=["a.*"]))  # a → v2

        assert store.get("a").version == 2
        assert store.get("b").version == 1

    def test_version_reflects_in_list_all(self, store: PolicyStore):
        """list_all returns policies with correct version numbers."""
        store.upsert(make_policy(policy_id="x", target_patterns=["x.*"]))
        store.upsert(make_policy(policy_id="x", target_patterns=["x.*"]))  # x → v2
        store.upsert(make_policy(policy_id="x", target_patterns=["x.*"]))  # x → v3

        policies = store.list_all()
        for p in policies:
            if p.policy_id == "x":
                assert p.version == 3

    def test_version_is_integer(self, store: PolicyStore):
        """Version is stored and retrieved as an integer."""
        store.upsert(make_policy(policy_id="vint", target_patterns=["v.*"]))
        for _ in range(3):
            store.upsert(make_policy(policy_id="vint", target_patterns=["v.*"]))
        p = store.get("vint")
        assert isinstance(p.version, int)
        assert p.version == 4


# ====================================================================
# 10. Edge cases: empty policies, malformed patterns, missing capabilities
# ====================================================================

class TestEdgeCases:
    """Edge cases and error handling for the security module."""

    # ── Empty / minimal inputs ──

    def test_empty_capability_name_in_dict(self, manager: SecurityManager):
        """An empty 'name' in a capability dict raises SecurityError."""
        with pytest.raises(SecurityError, match="name"):
            manager.evaluate({"name": "", "risk": "low"})

    def test_missing_name_key_in_dict(self, manager: SecurityManager):
        """A dict without a 'name' key raises SecurityError."""
        with pytest.raises(SecurityError, match="name"):
            manager.evaluate({"risk": "low"})

    def test_evaluate_no_args_raises(self, manager: SecurityManager):
        """Calling evaluate() with no arguments raises SecurityError."""
        with pytest.raises(SecurityError, match="capability_name"):
            manager.evaluate()

    def test_evaluate_invalid_type_raises(self, manager: SecurityManager):
        """Passing an unsupported type (e.g. int) raises SecurityError."""
        with pytest.raises(SecurityError, match="Unsupported"):
            manager.evaluate(42)  # type: ignore[arg-type]

    # ── Malformed policy data ──

    def test_malformed_review_rules_string(self, manager: SecurityManager, store: PolicyStore):
        """A string instead of list for allow/deny gracefully falls through to default."""
        store.upsert(make_policy(
            policy_id="p-mal", target_patterns=["mal.*"],
            review_rules={"allow": "not_a_list"},
        ))
        result = manager.evaluate({"name": "mal.test", "risk": "low"})
        # Should not crash, should fall through to default
        assert result.decision == SecurityDecision.ALLOW

    def test_malformed_review_rules_missing_keys(self, manager: SecurityManager, store: PolicyStore):
        """review_rules with unexpected keys doesn't crash."""
        store.upsert(make_policy(
            policy_id="p-weird", target_patterns=["w.*"],
            review_rules={"unknown_key": [1, 2, 3]},
        ))
        result = manager.evaluate({"name": "w.action", "risk": "low"})
        assert result.decision == SecurityDecision.ALLOW

    def test_empty_review_rules(self, manager: SecurityManager, store: PolicyStore):
        """Empty review_rules dict is treated as no restrictions."""
        store.upsert(make_policy(
            policy_id="p-empty", target_patterns=["empty.*"], review_rules={},
        ))
        result = manager.evaluate({"name": "empty.cap", "risk": "low"})
        assert result.decision == SecurityDecision.ALLOW

    def test_empty_target_patterns(self, store: PolicyStore):
        """A policy with no target patterns matches nothing."""
        store.upsert(Policy(policy_id="no-patterns", target_patterns=[]))
        assert store.get_for_capability("anything") == []

    # ── Missing / null fields ──

    def test_get_for_capability_non_existent_capability(self, store: PolicyStore):
        """Querying for a capability that doesn't exist returns empty list."""
        store.upsert(make_policy(policy_id="p", target_patterns=["specific.*"]))
        matches = store.get_for_capability("non.existent")
        assert matches == []

    def test_risk_level_defaults_to_medium(self, manager: SecurityManager, store: PolicyStore):
        """When risk is not specified, it defaults to medium."""
        store.upsert(make_policy(policy_id="catch", target_patterns=["*"]))
        result = manager.evaluate({"name": "test"})
        assert result.risk_level == "medium"

    def test_capability_name_kwarg_without_risk(self, manager: SecurityManager):
        """capability_name alone works; risk_level defaults to medium."""
        result = manager.evaluate(capability_name="test.api")
        assert result.capability_name == "test.api"
        assert result.risk_level == "medium"
        assert result.decision == SecurityDecision.DENY

    # ── Policy interactions ──

    def test_multiple_policies_mixed_allow_and_review(self, manager: SecurityManager, store: PolicyStore):
        """Multiple policies with different rules resolve correctly."""
        store.upsert(make_policy(
            policy_id="base", target_patterns=["data.*"],
            review_rules={"require_review_for": ["critical"]},
        ))
        store.upsert(make_policy(
            policy_id="override", target_patterns=["data.special"],
            review_rules={"allow": ["data.special"]},
        ))

        # data.special should be ALLOWed by the override policy (explicit allow)
        result = manager.evaluate({"name": "data.special", "risk": "critical"})
        assert result.decision == SecurityDecision.ALLOW

        # data.normal with critical risk should still require review
        result = manager.evaluate({"name": "data.normal", "risk": "critical"})
        assert result.decision == SecurityDecision.REQUIRE_REVIEW

    def test_spec_allowed_contexts_glob_matching(self, manager: SecurityManager, store: PolicyStore):
        """allowed_contexts uses glob patterns to match context keys."""
        store.upsert(make_policy(policy_id="glob-p", target_patterns=["g.*"]))
        result = manager.evaluate(
            {"name": "g.test", "risk": "low", "allowed_contexts": ["internal_*"]},
            {"internal_ip": "10.0.0.1", "user_role": "admin"},
        )
        assert result.decision == SecurityDecision.ALLOW

    def test_spec_allowed_contexts_no_context_fails_closed(self, manager: SecurityManager, store: PolicyStore):
        """When spec restricts context but no context given, deny (fail closed)."""
        store.upsert(make_policy(policy_id="ctx-p3", target_patterns=["z.*"]))
        result = manager.evaluate(
            {"name": "z.test", "risk": "low", "allowed_contexts": ["internal_ip"]},
        )
        assert result.decision == SecurityDecision.DENY

    # ── EvaluationResult ──

    def test_evaluation_result_to_tuple(self):
        result = EvaluationResult(
            decision=SecurityDecision.ALLOW,
            rationale="Allowed",
            policy_id="pol-1",
            risk_level="low",
            capability_name="test",
        )
        tup = result.to_tuple()
        assert tup == (SecurityDecision.ALLOW, "Allowed", "pol-1")

    def test_evaluation_result_to_tuple_none_policy(self):
        result = EvaluationResult(
            decision=SecurityDecision.DENY,
            rationale="No policy",
            policy_id=None,
            risk_level="low",
            capability_name="test",
        )
        tup = result.to_tuple()
        assert tup == (SecurityDecision.DENY, "No policy", None)

    def test_evaluation_result_all_fields(self):
        result = EvaluationResult(
            decision=SecurityDecision.REQUIRE_REVIEW,
            rationale="Review needed",
            policy_id="pol-review",
            risk_level="high",
            capability_name="risky.op",
        )
        assert result.decision == SecurityDecision.REQUIRE_REVIEW
        assert result.rationale == "Review needed"
        assert result.policy_id == "pol-review"
        assert result.risk_level == "high"
        assert result.capability_name == "risky.op"

    # ── SecurityRisk enum ──

    def test_security_decision_members(self):
        assert SecurityDecision.ALLOW.value == "allow"
        assert SecurityDecision.DENY.value == "deny"
        assert SecurityDecision.REQUIRE_REVIEW.value == "require_review"
        assert len(set(SecurityDecision)) == 3

    def test_security_risk_from_str_valid(self):
        assert SecurityRisk.from_str("low") == SecurityRisk.LOW
        assert SecurityRisk.from_str("MEDIUM") == SecurityRisk.MEDIUM
        assert SecurityRisk.from_str("High") == SecurityRisk.HIGH
        assert SecurityRisk.from_str("critical") == SecurityRisk.CRITICAL

    def test_security_risk_from_str_unknown_defaults_medium(self):
        assert SecurityRisk.from_str("unknown") == SecurityRisk.MEDIUM
        assert SecurityRisk.from_str("") == SecurityRisk.MEDIUM

    def test_security_risk_comparison(self):
        assert SecurityRisk.LOW <= SecurityRisk.MEDIUM
        assert SecurityRisk.MEDIUM <= SecurityRisk.HIGH
        assert SecurityRisk.HIGH <= SecurityRisk.CRITICAL
        assert SecurityRisk.CRITICAL >= SecurityRisk.HIGH
        assert not (SecurityRisk.LOW >= SecurityRisk.HIGH)

    def test_security_risk_levels_ordered(self):
        levels = list(SecurityRisk)
        assert levels == [
            SecurityRisk.LOW,
            SecurityRisk.MEDIUM,
            SecurityRisk.HIGH,
            SecurityRisk.CRITICAL,
        ]
