from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from config import DATETIME_FORMAT, DB_DIR, DB_PATH

logger = logging.getLogger(__name__)


class DBError(RuntimeError):
    """Database operation error wrapper."""
    pass


@dataclass(frozen=True)
class DBUser:
    """Typed view of a user record."""
    id: int
    username: str
    full_name: str
    created_at: str
    is_active: int
    expiry_mode: str
    expiry_value: str | None
    expiry_at: str | None
    traffic_limit_bytes: int
    traffic_used_bytes: int
    traffic_reset_mode: str
    last_traffic_reset: str | None
    ssh_public_key: str | None
    notes: str | None
    deleted_at: str | None


class Database:
    """SQLite access layer with basic migrations and CRUD helpers."""
    def __init__(self, db_path: Path = DB_PATH) -> None:
        """Create a database wrapper for the given SQLite path."""
        self.db_path = db_path
        self.lock = Lock()

    def connect(self) -> sqlite3.Connection:
        """Open a new database connection."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as exc:
            logger.error("DB connect failed: %s", exc)
            raise DBError(str(exc)) from exc

    def initialize(self) -> None:
        """Create database directory and apply migrations."""
        DB_DIR.mkdir(parents=True, exist_ok=True)
        with self.lock:
            conn = self.connect()
            try:
                self._apply_migrations(conn)
            finally:
                conn.close()

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        """Apply schema migrations for this database."""
        try:
            cur = conn.execute("PRAGMA user_version")
            version = int(cur.fetchone()[0])
            if version < 1:
                self._create_schema(conn)
                conn.execute("PRAGMA user_version = 1")
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            logger.error("DB migration failed: %s", exc)
            raise DBError(str(exc)) from exc

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        """Create the initial schema for a new database."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                expiry_mode TEXT NOT NULL,
                expiry_value TEXT,
                expiry_at TEXT,
                traffic_limit_bytes INTEGER NOT NULL DEFAULT 0,
                traffic_used_bytes INTEGER NOT NULL DEFAULT 0,
                traffic_reset_mode TEXT NOT NULL,
                last_traffic_reset TEXT,
                ssh_public_key TEXT,
                notes TEXT,
                deleted_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_users_active ON users (is_active);
            CREATE INDEX IF NOT EXISTS idx_users_expiry ON users (expiry_at);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    def create_user_record(self, data: dict[str, Any]) -> None:
        """Insert a user record into the database."""
        with self.lock:
            conn = self.connect()
            try:
                conn.execute(
                    """
                    INSERT INTO users (
                        username, full_name, created_at, is_active, expiry_mode,
                        expiry_value, expiry_at, traffic_limit_bytes,
                        traffic_used_bytes, traffic_reset_mode, last_traffic_reset,
                        ssh_public_key, notes, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["username"],
                        data.get("full_name", ""),
                        data["created_at"],
                        int(data.get("is_active", 1)),
                        data["expiry_mode"],
                        data.get("expiry_value"),
                        data.get("expiry_at"),
                        int(data.get("traffic_limit_bytes", 0)),
                        int(data.get("traffic_used_bytes", 0)),
                        data["traffic_reset_mode"],
                        data.get("last_traffic_reset"),
                        data.get("ssh_public_key"),
                        data.get("notes"),
                        data.get("deleted_at"),
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                logger.error("DB insert failed: %s", exc)
                raise DBError(str(exc)) from exc
            finally:
                conn.close()

    def update_user_record(self, username: str, fields: dict[str, Any]) -> None:
        """Update a user record by username with the provided fields."""
        if not fields:
            return
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [username]
        with self.lock:
            conn = self.connect()
            try:
                conn.execute(f"UPDATE users SET {columns} WHERE username = ?", values)
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                logger.error("DB update failed: %s", exc)
                raise DBError(str(exc)) from exc
            finally:
                conn.close()

    def soft_delete_user(self, username: str) -> None:
        """Soft-delete a user record and mark it inactive."""
        deleted_at = self.utcnow()
        self.update_user_record(username, {"deleted_at": deleted_at, "is_active": 0})

    def list_users(self, include_deleted: bool = False) -> list[DBUser]:
        """Return user records, optionally including soft-deleted rows."""
        with self.lock:
            conn = self.connect()
            try:
                if include_deleted:
                    cur = conn.execute("SELECT * FROM users ORDER BY username")
                else:
                    cur = conn.execute(
                        "SELECT * FROM users WHERE deleted_at IS NULL ORDER BY username"
                    )
                rows = [DBUser(**dict(row)) for row in cur.fetchall()]
                return rows
            except sqlite3.Error as exc:
                logger.error("DB list failed: %s", exc)
                raise DBError(str(exc)) from exc
            finally:
                conn.close()

    def get_user(self, username: str) -> DBUser | None:
        """Fetch a single user by username."""
        with self.lock:
            conn = self.connect()
            try:
                cur = conn.execute(
                    "SELECT * FROM users WHERE username = ?", (username,)
                )
                row = cur.fetchone()
                return DBUser(**dict(row)) if row else None
            except sqlite3.Error as exc:
                logger.error("DB get failed: %s", exc)
                raise DBError(str(exc)) from exc
            finally:
                conn.close()

    def record_event(self, username: str, event_type: str, message: str) -> None:
        """Append an audit event for a user."""
        created_at = self.utcnow()
        with self.lock:
            conn = self.connect()
            try:
                conn.execute(
                    "INSERT INTO events (username, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                    (username, event_type, message, created_at),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                logger.error("DB event insert failed: %s", exc)
                raise DBError(str(exc)) from exc
            finally:
                conn.close()

    def update_traffic(self, username: str, used_bytes: int) -> None:
        """Update traffic usage for a user."""
        self.update_user_record(username, {"traffic_used_bytes": used_bytes})

    def reset_traffic(self, username: str) -> None:
        """Reset traffic usage counters for a user."""
        now = self.utcnow()
        self.update_user_record(
            username, {"traffic_used_bytes": 0, "last_traffic_reset": now}
        )

    def update_bulk(self, updates: Iterable[tuple[str, dict[str, Any]]]) -> None:
        """Apply a list of username and field updates in a single transaction."""
        with self.lock:
            conn = self.connect()
            try:
                for username, fields in updates:
                    if not fields:
                        continue
                    columns = ", ".join(f"{key} = ?" for key in fields)
                    values = list(fields.values()) + [username]
                    conn.execute(
                        f"UPDATE users SET {columns} WHERE username = ?", values
                    )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                logger.error("DB bulk update failed: %s", exc)
                raise DBError(str(exc)) from exc
            finally:
                conn.close()

    @staticmethod
    def utcnow() -> str:
        """Return the current UTC timestamp in configured string format."""
        return datetime.now(timezone.utc).strftime(DATETIME_FORMAT)
