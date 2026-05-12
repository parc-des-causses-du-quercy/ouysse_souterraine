"""Tests for the task error contract.

`task.error` must be a structured object {code, message, details} regardless
of failure source — same shape as HTTP-level errors. Legacy rows stored as
plain strings are wrapped on read for backward compatibility.
"""

import json
import os
import sys
import sqlite3
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


from app.db.tasks import TaskDB, _parse_error, _serialize_error


# -------------------------- Unit tests: helpers --------------------------


def test_serialize_error_dict_passes_through():
    s = _serialize_error({
        "code": "STATE_TOO_OLD_FOR_AUTO_RESET",
        "message": "x",
        "details": {"advance_hours": 200.0},
    })
    parsed = json.loads(s)
    assert parsed["code"] == "STATE_TOO_OLD_FOR_AUTO_RESET"
    assert parsed["message"] == "x"
    assert parsed["details"] == {"advance_hours": 200.0}


def test_serialize_error_string_wraps_into_object():
    s = _serialize_error("plain string error")
    parsed = json.loads(s)
    assert parsed == {"code": None, "message": "plain string error", "details": None}


def test_serialize_error_none_stays_none():
    assert _serialize_error(None) is None


def test_parse_error_object_round_trip():
    raw = json.dumps({"code": "X", "message": "Y", "details": None})
    parsed = _parse_error(raw)
    assert parsed == {"code": "X", "message": "Y", "details": None}


def test_parse_error_legacy_string_wrapped():
    """Legacy rows stored a plain prose string in the column."""
    parsed = _parse_error("StateAdvanceError: foo bar baz")
    assert parsed == {
        "code": None,
        "message": "StateAdvanceError: foo bar baz",
        "details": None,
    }


def test_parse_error_none():
    assert _parse_error(None) is None


def test_parse_error_invalid_json_falls_back_to_string():
    parsed = _parse_error("not json {")
    assert parsed["message"] == "not json {"
    assert parsed["code"] is None


def test_parse_error_object_missing_message_key_treated_as_legacy():
    """Defensive: if a row contains JSON but doesn't look like our schema,
    don't crash — treat it as opaque text."""
    raw = json.dumps([1, 2, 3])
    parsed = _parse_error(raw)
    assert parsed["message"] == raw
    assert parsed["code"] is None


# -------------------------- Integration: TaskDB --------------------------


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = TaskDB(path)
    yield db
    try:
        os.remove(path)
    except OSError:
        pass


def test_task_failed_round_trip_with_dict(db):
    db.create_task("task-1", "ouysse", "2026-05-07T10:00:00", {"foo": "bar"})
    err = {"code": "STATE_TOO_OLD_FOR_AUTO_RESET", "message": "200h", "details": None}
    db.update_task_failed("task-1", "2026-05-07T10:00:01", err, 1.5)

    task = db.get_task("task-1")
    assert task["status"] == "failed"
    assert isinstance(task["error"], dict)
    assert task["error"]["code"] == "STATE_TOO_OLD_FOR_AUTO_RESET"
    assert task["error"]["message"] == "200h"


def test_task_failed_round_trip_with_string_legacy_caller(db):
    """A caller that still passes a plain string still works — it's wrapped."""
    db.create_task("task-2", "ouysse", "2026-05-07T10:00:00", {})
    db.update_task_failed("task-2", "2026-05-07T10:00:01", "boom", 0.1)

    task = db.get_task("task-2")
    assert task["error"] == {"code": None, "message": "boom", "details": None}


def test_existing_legacy_string_rows_are_wrapped_on_read(db):
    """Rows written by the previous string-based code path must still
    deserialize to the new structured shape when read."""
    db.create_task("task-3", "ouysse", "2026-05-07T10:00:00", {})
    # Write a legacy-style plain string directly via SQL, bypassing the
    # serializer, to simulate an old row.
    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            "UPDATE tasks SET status='failed', completed_at=?, error=?, duration_seconds=? WHERE id=?",
            ("2026-05-07T10:00:01", "StateAdvanceError: legacy prose", 0.1, "task-3"),
        )

    task = db.get_task("task-3")
    assert isinstance(task["error"], dict)
    assert task["error"]["message"] == "StateAdvanceError: legacy prose"
    assert task["error"]["code"] is None


def test_task_completed_has_no_error(db):
    db.create_task("task-4", "ouysse", "2026-05-07T10:00:00", {})
    db.update_task_completed("task-4", "2026-05-07T10:00:02", {"x": 1}, 1.0)
    task = db.get_task("task-4")
    assert task["status"] == "completed"
    assert task["error"] is None
