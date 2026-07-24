"""
Intent OS — Database migration command.

Merges 7 legacy per-store SQLite databases into the unified
``~/.intent-os/intent.db``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

OLD_DB_FILES = [
    "events.db",
    "agents.db",
    "contexts.db",
    "evidence.db",
    "experience.db",
    "store.db",
    "policies.db",
]


def cmd_db(args: Any) -> None:
    """Entry point for ``intent-os db <subcommand>``."""
    action = getattr(args, "action", None)
    if action == "migrate":
        _cmd_migrate(args)
    else:
        from core.registry import RegistryError
        raise RegistryError(f"Unknown db action: {action}")


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------

def _cmd_migrate(_args: Any) -> None:
    """Copy data from old per-store DBs into the unified intent.db."""
    base_dir = Path.home() / ".intent-os"
    unified_path = base_dir / "intent.db"

    base_dir.mkdir(parents=True, exist_ok=True)

    # Open the unified DB (WAL mode for safety)
    unified = sqlite3.connect(str(unified_path), timeout=30)
    unified.execute("PRAGMA journal_mode=WAL;")
    unified.execute("PRAGMA foreign_keys=OFF;")

    total_migrated = 0

    for old_name in OLD_DB_FILES:
        old_path = base_dir / old_name
        if not old_path.exists():
            continue

        try:
            old = sqlite3.connect(str(old_path), timeout=30)
            old.row_factory = sqlite3.Row

            # Discover all user tables (skip sqlite_* and _schema_version)
            tables = [
                r[0] for r in
                old.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                    "AND name != '_schema_version'"
                ).fetchall()
            ]

            migrated = 0
            for table in tables:
                # Get column names
                cols = [c[1] for c in old.execute(f"PRAGMA table_info({table})").fetchall()]
                if not cols:
                    continue
                col_list = ", ".join(cols)
                placeholders = ", ".join("?" for _ in cols)

                # Ensure table exists in unified DB
                _ensure_table_from_old(unified, old, table)

                # Read all rows from old DB
                rows = old.execute(f"SELECT {col_list} FROM {table}").fetchall()

                # Insert into unified DB
                for row in rows:
                    try:
                        unified.execute(
                            f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                            tuple(row),
                        )
                        migrated += 1
                    except sqlite3.OperationalError:
                        pass  # Skip if schema mismatch

            unified.commit()
            old.close()

            table_desc = ", ".join(tables) if tables else "(no tables)"
            print(f"  Migrated {migrated} rows from {old_name}  [{table_desc}]")
            total_migrated += migrated

        except sqlite3.Error as exc:
            print(f"  Skipping {old_name}: {exc}")

    unified.close()

    print()
    print(f"Migration complete. {total_migrated} total rows migrated.")
    print(f"Old DBs preserved at {base_dir}/. You can delete them manually.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_table_from_old(
    unified: sqlite3.Connection, old: sqlite3.Connection, table: str,
) -> None:
    """Recreate *table* in *unified* from the schema in *old*."""
    if _table_exists(unified, table):
        return
    cursor = old.execute(
        f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    row = cursor.fetchone()
    if row is None:
        return
    unified.execute(row[0])
    unified.commit()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cursor.fetchone() is not None
