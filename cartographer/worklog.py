from __future__ import annotations

import random
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


MAX_RETRIES = 5
BASE_DELAY = 0.05
MAX_DELAY = 5.0


def _retry_with_backoff(operation: str, func: callable) -> Any:
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return func()
        except sqlite3.OperationalError as e:
            last_error = e
            if "database is locked" not in str(e).lower():
                raise
            delay = min(BASE_DELAY * (2**attempt) + random.uniform(0, 0.1), MAX_DELAY)
            time.sleep(delay)
        except Exception:
            raise
    raise sqlite3.OperationalError(
        f"database locked after {MAX_RETRIES} retries: {operation}"
    ) from last_error


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started REAL,
    ended REAL,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    description TEXT,
    status TEXT DEFAULT 'pending',
    result TEXT,
    created REAL,
    completed REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


@dataclass(slots=True)
class WorklogSession:
    id: str
    started: float


class Worklog:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _connection(self):
        def get_connection():
            return self._connect()

        connection = _retry_with_backoff("connect", get_connection)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(SCHEMA)

    def start_session(self) -> WorklogSession:
        session_id = f"session-{time.strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:6]}"
        started = time.time()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO sessions (id, started, ended, summary) VALUES (?, ?, NULL, '')",
                (session_id, started),
            )
            connection.execute(
                "INSERT INTO state (key, value) VALUES ('current_session', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (session_id,),
            )
        return WorklogSession(id=session_id, started=started)

    def current_session_id(self) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM state WHERE key = 'current_session'"
            ).fetchone()
        return None if row is None else str(row["value"])

    def ensure_session(self) -> str:
        session_id = self.current_session_id()
        if session_id:
            return session_id
        return self.start_session().id

    def add_task(self, session_id: str, description: str) -> str:
        task_id = f"w{uuid.uuid4().hex[:8]}"
        now = time.time()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks (id, session_id, description, status, result, created, completed)
                VALUES (?, ?, ?, 'in_progress', '', ?, NULL)
                """,
                (task_id, session_id, description, now),
            )
        return task_id

    def complete_task(self, task_id: str, *, result: str = "") -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'completed', result = ?, completed = ?
                WHERE id = ?
                """,
                (result, time.time(), task_id),
            )

    def fail_task(self, task_id: str, *, result: str = "") -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'failed', result = ?, completed = ?
                WHERE id = ?
                """,
                (result, time.time(), task_id),
            )

    def end_session(self, session_id: str, *, summary: str = "") -> None:
        with self._connection() as connection:
            if summary:
                connection.execute(
                    """
                    UPDATE sessions
                    SET summary = CASE
                        WHEN COALESCE(summary, '') = '' THEN ?
                        ELSE summary || char(10) || ?
                    END
                    WHERE id = ?
                    """,
                    (summary, summary, session_id),
                )
            connection.execute(
                "UPDATE sessions SET ended = COALESCE(ended, ?) WHERE id = ?",
                (time.time(), session_id),
            )
            current = connection.execute(
                "SELECT value FROM state WHERE key = 'current_session'"
            ).fetchone()
            if current and current["value"] == session_id:
                connection.execute("DELETE FROM state WHERE key = 'current_session'")

    def log(self, message: str) -> str:
        session_id = self.ensure_session()
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET summary = CASE
                    WHEN COALESCE(summary, '') = '' THEN ?
                    ELSE summary || char(10) || ?
                END
                WHERE id = ?
                """,
                (line, line, session_id),
            )
        return session_id

    def status(self) -> dict[str, object]:
        with self._connection() as connection:
            in_progress = connection.execute(
                """
                SELECT id, session_id, description, created
                FROM tasks
                WHERE status = 'in_progress'
                ORDER BY created ASC
                """
            ).fetchall()
            last_session = connection.execute(
                """
                SELECT id, started, ended, summary
                FROM sessions
                ORDER BY started DESC
                LIMIT 1
                """
            ).fetchone()
        return {
            "current_session_id": self.current_session_id(),
            "in_progress": [dict(row) for row in in_progress],
            "last_session": None if last_session is None else dict(last_session),
        }


def record_operation(db_path: Path, description: str, result: str) -> str:
    worklog = Worklog(db_path)
    session_id = worklog.start_session().id
    task_id = worklog.add_task(session_id, description)
    worklog.complete_task(task_id, result=result)
    worklog.end_session(session_id, summary=result)
    return task_id
