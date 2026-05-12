# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import os


class Config:
    """Flask application configuration loaded from environment variables."""

    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = FLASK_ENV == "development"

    # Paths
    CONFIGS_PATH = os.getenv("CONFIGS_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs", "points"))
    STATES_PATH = os.getenv("STATES_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "states"))
    BACKUPS_PATH = os.getenv("BACKUPS_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups"))
    TASK_DB_PATH = os.getenv("TASK_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tasks.db"))

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = os.getenv("LOG_FORMAT", "text")
    LOG_FILE = os.getenv("LOG_FILE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "hydro_forecast.log"))
    LOG_FILE_MAX_BYTES = int(os.getenv("LOG_FILE_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB
    LOG_FILE_BACKUP_COUNT = int(os.getenv("LOG_FILE_BACKUP_COUNT", "5"))

    # Rate limiting
    RATE_LIMIT_DEFAULT = os.getenv("RATE_LIMIT_DEFAULT", "60/minute")
    RATE_LIMIT_FORECAST = os.getenv("RATE_LIMIT_FORECAST", "10/minute")

    # Prometheus
    PROMETHEUS_ENABLED = os.getenv("PROMETHEUS_ENABLED", "true").lower() == "true"

    # Backup
    BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "7"))

    # Task retention
    TASK_RETENTION_DAYS = int(os.getenv("TASK_RETENTION_DAYS", "7"))

    # ARPEGE cache
    ARPEGE_CACHE_TTL_HOURS = int(os.getenv("ARPEGE_CACHE_TTL_HOURS", "6"))
