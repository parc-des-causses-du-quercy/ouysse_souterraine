"""
Task service — async forecast execution with ThreadPoolExecutor + SQLite.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..db.tasks import TaskDB

logger = logging.getLogger(__name__)


class TaskService:
    """Manages async forecast tasks with a single-worker thread pool."""

    def __init__(self):
        self.db = None
        self.executor = None
        self._app = None

    def init_app(self, app):
        """Initialize with Flask app context."""
        self._app = app
        db_path = app.config["TASK_DB_PATH"]
        self.db = TaskDB(db_path)
        self.executor = ThreadPoolExecutor(max_workers=1)
        logger.info("Task service initialized", extra={"db_path": db_path})

    def submit_forecast(self, point_id, request_data, forecast_fn):
        """Submit a forecast task for async execution.

        Args:
            point_id: measurement point identifier
            request_data: dict with forecast request parameters
            forecast_fn: callable(point_id, request_data) -> dict result

        Returns:
            dict with task_id, point_id, status, created_at
        """
        task_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        self.db.create_task(task_id, point_id, created_at, request_data)

        # Submit to thread pool
        app = self._app
        self.executor.submit(self._run_task, app, task_id, point_id, request_data, forecast_fn)

        # Log queue depth (pending + running tasks)
        queue_pending = len(self.db.list_tasks(status="pending")) + len(self.db.list_tasks(status="running"))
        logger.info("Forecast task submitted", extra={
            "task_id": task_id, "point_id": point_id, "queue_depth": queue_pending,
        })

        return {
            "task_id": task_id,
            "point_id": point_id,
            "status": "pending",
            "created_at": created_at,
            "poll_url": f"/api/v1/tasks/{task_id}",
        }

    def _run_task(self, app, task_id, point_id, request_data, forecast_fn):
        """Execute forecast task in worker thread."""
        with app.app_context():
            started_at = datetime.now(timezone.utc).isoformat()
            self.db.update_task_started(task_id, started_at)
            start_time = time.time()

            logger.info("Forecast task started", extra={"task_id": task_id, "point_id": point_id})

            try:
                result = forecast_fn(point_id, request_data)
                duration = time.time() - start_time
                completed_at = datetime.now(timezone.utc).isoformat()
                self.db.update_task_completed(task_id, completed_at, result, duration)

                logger.info("Forecast task completed", extra={
                    "task_id": task_id,
                    "point_id": point_id,
                    "duration_seconds": round(duration, 2),
                })

            except Exception as e:
                duration = time.time() - start_time
                completed_at = datetime.now(timezone.utc).isoformat()
                # Build a structured error matching the {code, message, details}
                # contract used by HTTP-level error handlers (see app/__init__.py
                # errorhandlers). Stored as JSON so polling clients get a
                # consistent object shape regardless of failure source.
                error_obj = {
                    "code": getattr(e, "code", None) or type(e).__name__,
                    "message": str(e),
                    "details": getattr(e, "details", None),
                }
                self.db.update_task_failed(task_id, completed_at, error_obj, duration)

                logger.error("Forecast task failed", extra={
                    "task_id": task_id,
                    "point_id": point_id,
                    "error_code": error_obj["code"],
                    "error": error_obj["message"],
                    "duration_seconds": round(duration, 2),
                })

    def get_task(self, task_id):
        """Get task by ID."""
        return self.db.get_task(task_id)

    def list_tasks(self, point_id=None, status=None, limit=50):
        """List tasks with optional filters."""
        return self.db.list_tasks(point_id=point_id, status=status, limit=limit)

    def delete_task(self, task_id):
        """Delete a task."""
        return self.db.delete_task(task_id)


# Singleton instance
task_service = TaskService()
