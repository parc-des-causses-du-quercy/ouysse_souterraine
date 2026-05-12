"""
SQLite task database — schema and CRUD operations for async task tracking.
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    point_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    request_json TEXT,
    result_json TEXT,
    error TEXT,
    duration_seconds REAL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_point_id ON tasks(point_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
"""


class TaskDB:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_task(self, task_id, point_id, created_at, request_data):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tasks (id, point_id, status, created_at, request_json) VALUES (?, ?, 'pending', ?, ?)",
                (task_id, point_id, created_at, json.dumps(request_data)),
            )
        logger.debug("Task created", extra={"task_id": task_id, "point_id": point_id})

    def update_task_started(self, task_id, started_at):
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ?",
                (started_at, task_id),
            )

    def update_task_completed(self, task_id, completed_at, result, duration):
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ?, result_json = ?, duration_seconds = ? WHERE id = ?",
                (completed_at, json.dumps(result), duration, task_id),
            )

    def update_task_failed(self, task_id, completed_at, error, duration):
        """Record a task failure.

        `error` accepts a dict with shape {code, message, details} (preferred)
        or a plain string (legacy callers). It is always persisted as a JSON
        string so reads return a consistent structured object.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = 'failed', completed_at = ?, error = ?, duration_seconds = ? WHERE id = ?",
                (completed_at, _serialize_error(error), duration, task_id),
            )

    def get_task(self, task_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def list_tasks(self, point_id=None, status=None, limit=50):
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []
        if point_id:
            query += " AND point_id = ?"
            params.append(point_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def delete_task(self, task_id):
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cursor.rowcount > 0

    def purge_old_tasks(self, retention_days=7):
        """Delete completed/failed tasks older than retention_days.

        Pending and running tasks are never deleted regardless of age.

        Returns:
            int: number of deleted rows
        """
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE status IN ('completed', 'failed') AND created_at < ?",
                (cutoff,),
            )
            count = cursor.rowcount
        if count:
            logger.info("Purged old tasks", extra={"deleted": count, "retention_days": retention_days})
        return count

    def _row_to_dict(self, row):
        d = dict(row)
        if d.get("result_json"):
            d["result"] = json.loads(d["result_json"])
        else:
            d["result"] = None
        if d.get("request_json"):
            d["request"] = json.loads(d["request_json"])
        else:
            d["request"] = None
        # error is stored as a JSON object {code, message, details};
        # legacy rows may contain a plain string — wrap them for the client
        # so the response shape stays consistent.
        d["error"] = _parse_error(d.get("error"))
        # Remove raw JSON fields from output
        d.pop("result_json", None)
        d.pop("request_json", None)
        return d


def _serialize_error(error):
    """Normalize an error into the JSON string we persist in the `error`
    column. Accepts a dict (preferred) or a plain string (legacy).
    """
    if error is None:
        return None
    if isinstance(error, dict):
        # Defensive: ensure all expected keys exist before serializing
        normalized = {
            "code": error.get("code"),
            "message": error.get("message", ""),
            "details": error.get("details"),
        }
        return json.dumps(normalized)
    return json.dumps({
        "code": None,
        "message": str(error),
        "details": None,
    })


def _parse_error(value):
    """Read the DB error column and return a {code, message, details} dict
    or None. Legacy rows that were stored as plain strings (pre-structured-
    error contract) are wrapped transparently."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict) and "message" in parsed:
            return {
                "code": parsed.get("code"),
                "message": parsed.get("message", ""),
                "details": parsed.get("details"),
            }
    except (json.JSONDecodeError, TypeError):
        pass
    return {"code": None, "message": str(value), "details": None}
