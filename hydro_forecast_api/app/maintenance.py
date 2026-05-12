"""
Background maintenance scheduler — periodic housekeeping tasks.

Runs in a daemon thread so it does not block app shutdown.
Tasks: purge old tasks from SQLite, clean up old state backups.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging
import threading

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 3600  # 1 hour


class MaintenanceScheduler:
    """Background daemon thread for periodic maintenance."""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._app = None

    def init_app(self, app):
        """Start the maintenance loop with Flask app context."""
        self._app = app
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="maintenance"
        )
        self._thread.start()
        logger.info("Maintenance scheduler started", extra={
            "interval_seconds": DEFAULT_INTERVAL_SECONDS,
        })

    def _loop(self):
        # Initial delay: let the app finish starting up
        self._stop_event.wait(60)
        while not self._stop_event.is_set():
            self._run_all()
            self._stop_event.wait(DEFAULT_INTERVAL_SECONDS)

    def _run_all(self):
        """Execute all maintenance tasks (each wrapped in try/except)."""
        with self._app.app_context():
            self._purge_old_tasks()
            self._cleanup_backups()

    def _purge_old_tasks(self):
        try:
            from .services.task_service import task_service
            from flask import current_app

            retention = current_app.config.get("TASK_RETENTION_DAYS", 7)
            deleted = task_service.db.purge_old_tasks(retention_days=retention)
            if deleted:
                logger.info("Maintenance: purged old tasks", extra={"deleted": deleted})
        except Exception:
            logger.exception("Maintenance: task purge failed")

    def _cleanup_backups(self):
        try:
            from .services import state_service

            state_service.cleanup_old_backups()
        except Exception:
            logger.exception("Maintenance: backup cleanup failed")

    def stop(self):
        """Signal the maintenance loop to stop."""
        self._stop_event.set()


# Singleton instance
maintenance_scheduler = MaintenanceScheduler()
