"""
Tests for EvidenceStore — SQLite-backed evidence persistence with verification.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.models import Evidence
from core.evidence_store import EvidenceStore, EvidenceStoreError


# ── Fixtures ──


@pytest.fixture
def store(tmp_path):
    """Return a fresh EvidenceStore backed by a temp file SQLite DB."""
    db_path = str(tmp_path / "test_evidence.db")
    return EvidenceStore(db_path=db_path)


def _make_evidence(
    evidence_id: str = "evi_test001",
    execution_id: str = "exec_test001",
    claim: str = "Test claim",
    source_type: str = "data",
    source_ref: str = "",
    confidence: float = 0.8,
    verified: bool = False,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        execution_id=execution_id,
        claim=claim,
        source_type=source_type,
        source_ref=source_ref,
        confidence=confidence,
        verified=verified,
    )


# ── Tests ──


class TestEvidenceStore:
    """Tests for EvidenceStore CRUD and verification."""

    # ── save and get ──

    def test_save_and_get_by_execution(self, store):
        """save_evidence persists; get_evidence_by_execution retrieves by execution_id."""
        ev = _make_evidence(
            evidence_id="evi_abc",
            execution_id="exec_xyz",
            claim="Revenue grew 12%",
            source_type="data",
            confidence=0.9,
        )
        store.save_evidence(ev)

        records = store.get_evidence_by_execution("exec_xyz")
        assert len(records) == 1
        assert records[0]["evidence_id"] == "evi_abc"
        assert records[0]["claim"] == "Revenue grew 12%"
        assert records[0]["source_type"] == "data"
        assert records[0]["confidence"] == 0.9

    def test_get_by_id(self, store):
        """get_evidence_by_id returns a single record."""
        ev = _make_evidence(evidence_id="evi_123", execution_id="exec_456")
        store.save_evidence(ev)

        record = store.get_evidence_by_id("evi_123")
        assert record is not None
        assert record["evidence_id"] == "evi_123"
        assert record["execution_id"] == "exec_456"

    def test_get_by_id_nonexistent(self, store):
        """get_evidence_by_id returns None for nonexistent ID."""
        result = store.get_evidence_by_id("evi_nonexistent")
        assert result is None

    def test_save_overwrites_by_id(self, store):
        """Saving evidence with same ID overwrites previous record."""
        ev1 = _make_evidence(evidence_id="evi_dup", claim="First claim")
        ev2 = _make_evidence(evidence_id="evi_dup", claim="Second claim")

        store.save_evidence(ev1)
        store.save_evidence(ev2)

        record = store.get_evidence_by_id("evi_dup")
        assert record is not None
        assert record["claim"] == "Second claim"

    # ── source_type validation ──

    def test_source_type_validation_invalid_raises(self, store):
        """save_evidence raises EvidenceStoreError for invalid source_type."""
        ev = _make_evidence(source_type="invalid_type")
        with pytest.raises(EvidenceStoreError, match="Invalid evidence source_type"):
            store.save_evidence(ev)

    def test_source_type_validation_empty_string_passes(self, store):
        """Empty source_type is allowed (no validation enforced on empty)."""
        ev = _make_evidence(source_type="")
        store.save_evidence(ev)  # should not raise
        record = store.get_evidence_by_id("evi_test001")
        assert record is not None

    def test_all_valid_source_types(self, store):
        """All four valid source_type values are accepted."""
        for st in ("data", "calculation", "model_inference", "external_api"):
            ev = _make_evidence(
                evidence_id=f"evi_{st}",
                execution_id=f"exec_{st}",
                source_type=st,
            )
            store.save_evidence(ev)  # should not raise
            record = store.get_evidence_by_id(f"evi_{st}")
            assert record is not None
            assert record["source_type"] == st

    # ── verify ──

    def test_verify_marks_as_verified(self, store):
        """verify_evidence() marks a record as verified with verifier info."""
        ev = _make_evidence(evidence_id="evi_v", verified=False)
        store.save_evidence(ev)

        result = store.verify_evidence("evi_v", verified_by="human-reviewer")
        assert result is True

        record = store.get_evidence_by_id("evi_v")
        assert record is not None
        assert record["verified"] == 1
        assert record["verified_by"] == "human-reviewer"
        assert record["verified_at"] is not None

    def test_verify_nonexistent_returns_false(self, store):
        """verify_evidence returns False for nonexistent evidence ID."""
        result = store.verify_evidence("evi_nonexistent", verified_by="someone")
        assert result is False

    # ── evidence chain ──

    def test_evidence_chain_orders_by_dependency(self, store):
        """get_evidence_chain() topologically orders evidence records."""
        # evi_dep depends on evi_base via source_ref
        ev_base = _make_evidence(
            evidence_id="evi_base",
            execution_id="exec_chain",
            claim="Base data",
            source_ref="",
        )
        ev_dep = _make_evidence(
            evidence_id="evi_dep",
            execution_id="exec_chain",
            claim="Derived from base",
            source_ref="evi_base",
        )
        ev_independent = _make_evidence(
            evidence_id="evi_ind",
            execution_id="exec_chain",
            claim="Independent",
            source_ref="",
        )
        store.save_evidence(ev_base)
        store.save_evidence(ev_dep)
        store.save_evidence(ev_independent)

        chain = store.get_evidence_chain("exec_chain")
        ids = [c["evidence_id"] for c in chain]
        assert len(ids) == 3
        # evi_base must come before evi_dep (dependency ordering)
        assert ids.index("evi_base") < ids.index("evi_dep")

    def test_evidence_chain_no_dependencies(self, store):
        """get_evidence_chain() works when no dependencies exist."""
        ev = _make_evidence(evidence_id="evi_solo", execution_id="exec_solo")
        store.save_evidence(ev)

        chain = store.get_evidence_chain("exec_solo")
        assert len(chain) == 1
        assert chain[0]["evidence_id"] == "evi_solo"

    # ── unverified ──

    def test_get_unverified_filters_correctly(self, store):
        """get_unverified_evidence() returns only unverified records."""
        ev1 = _make_evidence(evidence_id="evi_u1", execution_id="exec_u", verified=False)
        ev2 = _make_evidence(evidence_id="evi_u2", execution_id="exec_u", verified=True)
        store.save_evidence(ev1)
        store.save_evidence(ev2)

        unverified = store.get_unverified_evidence()
        assert len(unverified) == 1
        assert unverified[0]["evidence_id"] == "evi_u1"
        assert unverified[0]["verified"] == 0

    def test_get_unverified_all_verified(self, store):
        """get_unverified_evidence() returns empty list when all are verified."""
        ev = _make_evidence(evidence_id="evi_all_v", execution_id="exec_v", verified=True)
        store.save_evidence(ev)

        unverified = store.get_unverified_evidence()
        assert unverified == []

    # ── nonexistent execution ──

    def test_get_evidence_nonexistent_execution(self, store):
        """get_evidence_by_execution returns empty list for nonexistent execution_id."""
        records = store.get_evidence_by_execution("exec_nonexistent")
        assert records == []
        assert isinstance(records, list)

    # ── multiple evidence per execution ──

    def test_multiple_evidence_per_execution(self, store):
        """Multiple evidence records can be saved for a single execution."""
        ev1 = _make_evidence(evidence_id="evi_a", execution_id="exec_multi")
        ev2 = _make_evidence(evidence_id="evi_b", execution_id="exec_multi")
        ev3 = _make_evidence(evidence_id="evi_c", execution_id="exec_multi")
        store.save_evidence(ev1)
        store.save_evidence(ev2)
        store.save_evidence(ev3)

        records = store.get_evidence_by_execution("exec_multi")
        assert len(records) == 3
