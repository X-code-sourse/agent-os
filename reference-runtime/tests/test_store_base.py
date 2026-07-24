"""
Tests for StoreBase — the abstract base class for all Intent OS SQLite stores.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.store_base import StoreBase


# ── Minimal concrete subclass for testing ──

class _TestStore(StoreBase):
    """Minimal concrete StoreBase subclass used in tests."""

    _init_db_called: bool = False
    _migrate_called: bool = False

    @staticmethod
    def _default_db_path() -> str:
        return ":memory:"

    def _init_db(self) -> None:
        _TestStore._init_db_called = True
        conn = self._get_conn()
        conn.execute("CREATE TABLE IF NOT EXISTS test_items (id TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

    def _migrate_schema(self) -> None:
        _TestStore._migrate_called = True


class TestStoreBase:
    """Tests for the StoreBase abstract base class."""

    def test_init_creates_db(self, tmp_path):
        """__init__ calls _init_db during construction and creates the table."""
        _TestStore._init_db_called = False
        _TestStore._migrate_called = False

        db_path = str(tmp_path / "test_store.db")
        store = _TestStore(db_path=db_path)

        assert _TestStore._init_db_called is True
        assert store._db_path == db_path
        # Verify the table was created and persists across connections
        conn = store._get_conn()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_items'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_get_conn_returns_connection(self):
        """_get_conn returns a sqlite3.Connection with row_factory set."""
        store = _TestStore(db_path=":memory:")
        conn = store._get_conn()

        assert isinstance(conn, sqlite3.Connection)
        assert conn.row_factory == sqlite3.Row

        conn.close()

    def test_close_is_noop(self):
        """close() is a no-op by default (does not raise)."""
        store = _TestStore(db_path=":memory:")
        # Should not raise
        store.close()
