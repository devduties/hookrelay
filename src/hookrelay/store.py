import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from hookrelay.errors import NotFoundError
from hookrelay.models import Attempt, Endpoint, Event
from hookrelay.retry import RetryPolicy


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    """Small SQLite repository; each operation owns its connection and transaction."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        if str(database_path) != ":memory:":
            database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS endpoints (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    secret TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    endpoint_id TEXT NOT NULL REFERENCES endpoints(id),
                    payload_json TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'failed')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    last_error TEXT,
                    locked_until TEXT
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL REFERENCES events(id),
                    attempted_at TEXT NOT NULL,
                    status_code INTEGER,
                    response_body TEXT,
                    error TEXT,
                    duration_ms INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_events_endpoint ON events(endpoint_id, received_at);
                CREATE INDEX IF NOT EXISTS idx_attempts_event ON attempts(event_id, id);
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
            if "locked_until" not in columns:
                connection.execute("ALTER TABLE events ADD COLUMN locked_until TEXT")

    def create_endpoint(self, name: str, target_url: str, secret: str) -> Endpoint:
        endpoint = Endpoint(uuid4().hex, name, target_url, secret, datetime.now(UTC), True)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO endpoints (id, name, target_url, secret, created_at, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (
                    endpoint.id,
                    endpoint.name,
                    endpoint.target_url,
                    endpoint.secret,
                    endpoint.created_at.isoformat(),
                ),
            )
        return endpoint

    def get_endpoint(self, endpoint_id: str) -> Endpoint:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM endpoints WHERE id = ?", (endpoint_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("Endpoint not found")
        return Endpoint(
            row["id"],
            row["name"],
            row["target_url"],
            row["secret"],
            datetime.fromisoformat(row["created_at"]),
            bool(row["is_active"]),
        )

    def create_event(self, endpoint_id: str, payload: dict[str, Any]) -> Event:
        event = Event(
            uuid4().hex,
            endpoint_id,
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            datetime.now(UTC),
            "pending",
            0,
            None,
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO events "
                "(id, endpoint_id, payload_json, received_at, status) VALUES (?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.endpoint_id,
                    event.payload_json,
                    event.received_at.isoformat(),
                    event.status,
                ),
            )
        return event

    def get_event(self, event_id: str) -> Event:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise NotFoundError("Event not found")
        next_attempt = (
            datetime.fromisoformat(row["next_attempt_at"]) if row["next_attempt_at"] else None
        )
        return Event(
            row["id"],
            row["endpoint_id"],
            row["payload_json"],
            datetime.fromisoformat(row["received_at"]),
            row["status"],
            row["attempt_count"],
            next_attempt,
        )

    def record_attempt(
        self,
        event_id: str,
        status_code: int | None,
        response_body: str | None,
        error: str | None,
        duration_ms: int,
        retryable_error: bool = False,
        retry_policy: RetryPolicy | None = None,
    ) -> Attempt:
        policy = retry_policy or RetryPolicy()
        with self._connect() as connection:
            event_row = connection.execute(
                "SELECT attempt_count FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if event_row is None:
                raise NotFoundError("Event not found")
            decision = policy.decide(
                status_code=status_code,
                error=error,
                retryable_error=retryable_error,
                attempt_number=event_row["attempt_count"] + 1,
            )
            delivered = decision.status == "delivered"
            status = "pending" if decision.status == "retrying" else decision.status
            last_error = None if delivered else (error or f"Receiver returned HTTP {status_code}")
            cursor = connection.execute(
                "INSERT INTO attempts "
                "(event_id, attempted_at, status_code, response_body, error, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, _now(), status_code, response_body, error, duration_ms),
            )
            connection.execute(
                "UPDATE events "
                "SET status = ?, attempt_count = attempt_count + 1, last_error = ?, "
                "next_attempt_at = ?, locked_until = NULL WHERE id = ?",
                (
                    status,
                    last_error,
                    decision.next_attempt_at.isoformat() if decision.next_attempt_at else None,
                    event_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM attempts WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return Attempt(
            row["id"],
            row["event_id"],
            datetime.fromisoformat(row["attempted_at"]),
            row["status_code"],
            row["response_body"],
            row["error"],
            row["duration_ms"],
        )

    def claim_due_event(self, lease_seconds: int = 30) -> Event | None:
        """Atomically lease one due event so concurrent workers do not claim it together."""
        now = datetime.now(UTC)
        now_value = now.isoformat()
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM events WHERE status = 'pending' "
                "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
                "AND (locked_until IS NULL OR locked_until <= ?) "
                "ORDER BY received_at LIMIT 1",
                (now_value, now_value),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE events SET locked_until = ? WHERE id = ?",
                (lease_until, row["id"]),
            )
            event_id = row["id"]
        return self.get_event(event_id)

    def list_attempts(self, event_id: str) -> list[Attempt]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM attempts WHERE event_id = ? ORDER BY id", (event_id,)
            ).fetchall()
        return [
            Attempt(
                row["id"],
                row["event_id"],
                datetime.fromisoformat(row["attempted_at"]),
                row["status_code"],
                row["response_body"],
                row["error"],
                row["duration_ms"],
            )
            for row in rows
        ]
