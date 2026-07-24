"""
Intent OS — Evidence Store (BluePrint Layer 4 — Verification)

SQLite-backed persistent storage for execution evidence records.

Evidence backs every Agent claim with auditable source information.
Each evidence record links to an Execution via ``execution_id`` and
can form dependency chains (one evidence record can reference another
as its ``source_ref``).

Design constraints:
  - Evidence Store belongs to the Data Plane (CONSTITUTION Article II)
  - Evidence records are immutable once verified
  - Evidence chains support topological ordering for audit trails

Usage:
    store = EvidenceStore()
    store.save_evidence(evidence)
    records = store.get_evidence_by_execution("exec_abc123")
    store.verify_evidence("evi_xyz", verified_by="human-reviewer")
    chain = store.get_evidence_chain("exec_abc123")
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import Evidence


# Default database path
EVIDENCE_DB = str(Path.home() / ".intent-os" / "intent.db")


# SQL statements
CREATE_EVIDENCE_TABLE = """
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL DEFAULT '',
    raw_data_ref TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    verified INTEGER NOT NULL DEFAULT 0,
    verified_by TEXT,
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%Sf','now'))
);
"""

# Valid evidence source types
_VALID_SOURCE_TYPES = frozenset({"data", "calculation", "model_inference", "external_api"})


class EvidenceStoreError(Exception):
    """Raised when Evidence Store operations fail."""
    pass


class EvidenceStore:
    """SQLite-backed Evidence Store.

    Follows the same connection pattern as ContextStore — new connection
    per operation, closed immediately after.

    Usage:
        store = EvidenceStore()
        store.save_evidence(evidence)
        records = store.get_evidence_by_execution("exec_abc")
        store.verify_evidence("evi_xyz", verified_by="reviewer")
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = str(db_path or EVIDENCE_DB)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()
        conn.execute(CREATE_EVIDENCE_TABLE)
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Helpers ──

    @staticmethod
    def _ev_attr(evidence: Any, name: str, default: Any = None) -> Any:
        """Extract a value from evidence, supporting both dict and Evidence dataclass."""
        if isinstance(evidence, dict):
            return evidence.get(name, default)
        return getattr(evidence, name, default)

    # ── Evidence CRUD ──

    def save_evidence(self, evidence: Evidence) -> None:
        """Persist a single evidence record.

        Args:
            evidence: An Evidence dataclass instance, or a dict with equivalent keys.

        Raises:
            EvidenceStoreError: If the evidence source_type is not one of the
                valid values (data, calculation, model_inference, external_api).
        """
        source_type = self._ev_attr(evidence, "source_type", "")
        if source_type and source_type not in _VALID_SOURCE_TYPES:
            raise EvidenceStoreError(
                f"Invalid evidence source_type '{source_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_SOURCE_TYPES))}"
            )

        evidence_id = self._ev_attr(evidence, "evidence_id")
        execution_id = self._ev_attr(evidence, "execution_id")
        claim = self._ev_attr(evidence, "claim")
        source_ref = self._ev_attr(evidence, "source_ref", "")
        raw_data_ref = self._ev_attr(evidence, "raw_data_ref", "")
        confidence = self._ev_attr(evidence, "confidence", 0.0)
        verified = self._ev_attr(evidence, "verified", False)
        verified_by = self._ev_attr(evidence, "verified_by", None)
        verified_at = self._ev_attr(evidence, "verified_at", None)

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO evidence
                   (evidence_id, execution_id, claim, source_type, source_ref,
                    raw_data_ref, confidence, verified, verified_by, verified_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%Sf','now'))""",
                (
                    evidence_id,
                    execution_id,
                    claim,
                    source_type or "",
                    source_ref or "",
                    raw_data_ref or "",
                    confidence,
                    1 if verified else 0,
                    verified_by,
                    verified_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_evidence_by_execution(self, execution_id: str) -> list[dict[str, Any]]:
        """Return all evidence records for a given execution."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM evidence WHERE execution_id = ? ORDER BY created_at ASC",
                (execution_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_evidence_by_id(self, evidence_id: str) -> dict[str, Any] | None:
        """Return a single evidence record by ID."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?",
                (evidence_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def verify_evidence(self, evidence_id: str, verified_by: str) -> bool:
        """Mark an evidence record as verified. Returns True if updated."""
        conn = self._get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                "UPDATE evidence SET verified = 1, verified_by = ?, verified_at = ? WHERE evidence_id = ?",
                (verified_by, now, evidence_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_evidence_chain(self, execution_id: str) -> list[dict[str, Any]]:
        """Return the full evidence chain for an execution, ordered by dependence.

        Evidence records are sorted by creation time, and any record whose
        ``source_ref`` points to another evidence ID is listed after its
        dependency.
        """
        records = self.get_evidence_by_execution(execution_id)
        # Simple topological sort: evidence referencing another evidence
        # in its source_ref is placed after the referenced record.
        by_id = {r["evidence_id"]: r for r in records}
        ordered: list[dict[str, Any]] = []
        visited: set[str] = set()

        def _walk(eid: str) -> None:
            if eid in visited or eid not in by_id:
                return
            rec = by_id[eid]
            src = rec.get("source_ref", "")
            # If source_ref is an evidence ID, walk the dependency first
            if src in by_id:
                _walk(src)
            visited.add(eid)
            ordered.append(rec)

        for r in records:
            _walk(r["evidence_id"])
        return ordered

    def get_unverified_evidence(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return evidence records that have not yet been verified."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM evidence WHERE verified = 0 ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
