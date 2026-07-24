"""
Intent OS — Store Base Class

Provides the common ``__init__`` / ``_get_conn`` / ``close`` pattern
shared by all five Intent OS stores:

  - AgentStore      (agent_store.py)
  - EventStore      (event_store.py)
  - EvidenceStore   (evidence_store.py)
  - ContextStore    (context_store.py)
  - PolicyStore     (security.py)

Subclasses must implement ``_init_db`` (create tables) and
``_migrate_schema`` (add columns for new versions).
"""

from __future__ import annotations

import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class StoreBase(ABC):
    """Base class for all Intent OS SQLite-backed stores.

    Provides the common initialisation, connection management, and
    schema migration lifecycle.  Subclasses supply a default database
    path via ``_default_db_path()`` and implement ``_init_db`` /
    ``_migrate_schema``.

    Usage::

        class MyStore(StoreBase):
            @staticmethod
            def _default_db_path() -> str:
                return str(Path.home() / ".intent-os" / "my_store.db")

            def _init_db(self) -> None:
                conn = self._get_conn()
                conn.execute("CREATE TABLE IF NOT EXISTS ...")
                conn.commit()

            def _migrate_schema(self) -> None:
                conn = self._get_conn()
                # ALTER TABLE ... ADD COLUMN ...
                conn.commit()
    """

    # ── Constructor ─────────────────────────────────────────────

    def __init__(self, db_path: str | None = None) -> None:
        """Initialise the store.

        Args:
            db_path: Filesystem path to the SQLite database file.
                When ``None``, the value returned by ``_default_db_path()``
                is used.  The parent directory is created automatically.
        """
        self._db_path = str(db_path or self._default_db_path())
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    @staticmethod
    def _default_db_path() -> str:
        """Return the default database path for this store.

        Subclasses **must** override this or always pass an explicit
        ``db_path`` to the constructor.
        """
        raise NotImplementedError(
            "Subclasses must define _default_db_path() or pass db_path"
        )

    # ── Connection management ───────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Return a new SQLite connection with ``row_factory`` set.

        The connection uses a 30-second timeout.  Callers are responsible
        for closing the returned connection when done.
        """
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def close(self) -> None:
        """Close any persistent resources held by the store.

        The default implementation is a no-op.  Subclasses that hold
        long-lived connections (e.g. thread-local or context-managed)
        should override this method.
        """
        pass

    # ── Abstract schema lifecycle ───────────────────────────────

    @abstractmethod
    def _init_db(self) -> None:
        """Create the database tables if they do not already exist.

        Called once during ``__init__``.  Must be idempotent — use
        ``CREATE TABLE IF NOT EXISTS``.
        """
        ...

    @abstractmethod
    def _migrate_schema(self) -> None:
        """Migrate the database schema to the latest version.

        Called after ``_init_db``.  Should add any columns or tables
        that were introduced after the initial schema was created.
        Implementations should guard each migration with a
        ``PRAGMA table_info`` check so the method remains safe to call
        on an already-migrated database.
        """
        ...
