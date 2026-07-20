"""
Agent OS P1 — Event Backbone.

In-memory pub/sub Event Bus + optional SQLite Event Store.
Currently memory-only; SQLite store is a stub for Day 2+.
All modules communicate through this bus.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import Event

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Any]


class EventBus:
    """Simple synchronous in-memory event bus with optional SQLite persistence."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._subscriptions: dict[str, list[Handler]] = defaultdict(list)
        self._all_handlers: list[Handler] = []
        self._events: list[Event] = []
        self._db_path: Path | None = Path(db_path) if db_path else None
        self._db: sqlite3.Connection | None = None
        if self._db_path:
            self._init_db()

    # ── Pub/Sub ────────────────────────────────────────────────────────

    def publish(self, event: Event) -> None:
        """Publish an event: store, then notify subscribers."""
        self._events.append(event)
        if self._db:
            self._store_event(event)

        # Global listeners
        for handler in self._all_handlers:
            self._safe_call(handler, event)

        # Type-specific listeners
        for handler in self._subscriptions.get(event.type, []):
            self._safe_call(handler, event)

        for handler in self._subscriptions.get("*", []):
            self._safe_call(handler, event)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Register a handler for a specific event type. '*' catches all."""
        self._subscriptions[event_type].append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        """Register a handler that receives every event (debug/logging)."""
        self._all_handlers.append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        """Remove a specific handler."""
        self._subscriptions[event_type] = [
            h for h in self._subscriptions[event_type] if h is not handler
        ]

    # ── Query ──────────────────────────────────────────────────────────

    def recent_events(self, event_type: str | None = None, limit: int = 50) -> list[Event]:
        """Return recent events, optionally filtered by type."""
        filtered = (
            [e for e in self._events if e.type == event_type]
            if event_type
            else self._events
        )
        return filtered[-limit:]

    # ── Persistence (stub) ─────────────────────────────────────────────

    def _init_db(self) -> None:
        self._db = sqlite3.connect(str(self._db_path))
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                source TEXT NOT NULL,
                data TEXT,
                timestamp TEXT NOT NULL
            )
            """
        )
        self._db.commit()

    def _store_event(self, event: Event) -> None:
        import json
        try:
            self._db.execute(
                "INSERT INTO events (id, type, source, data, timestamp) VALUES (?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.type,
                    event.source,
                    json.dumps(event.data, default=str),
                    event.timestamp.isoformat(),
                ),
            )
            self._db.commit()
        except sqlite3.IntegrityError:
            pass  # duplicate event id

    def close(self) -> None:
        if self._db:
            self._db.close()

    # ── Internals ──────────────────────────────────────────────────────

    @staticmethod
    def _safe_call(handler: Handler, event: Event) -> None:
        try:
            handler(event)
        except Exception:
            logger.exception("Event handler %s failed on %s", handler, event)
