# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging
import os
import sys
import warnings
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify

from .config import Config
from .extensions import init_extensions

# Suppress noisy third-party warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="cfgrib")
warnings.filterwarnings("ignore", category=FutureWarning, module="xarray")


class ExtraFormatter(logging.Formatter):
    """Text formatter that appends extra fields as key=value pairs."""

    _BUILTIN = frozenset(logging.LogRecord(
        "", 0, "", 0, "", (), None
    ).__dict__.keys()) | {"message", "asctime"}

    def format(self, record):
        base = super().format(record)
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in self._BUILTIN and not k.startswith("_")
        }
        if extras:
            pairs = " ".join(f"{k}={v}" for k, v in extras.items())
            return f"{base} | {pairs}"
        return base


def setup_logging(app):
    """Configure logging to stdout + rotating file."""
    log_level = getattr(logging, app.config["LOG_LEVEL"].upper(), logging.INFO)
    text_formatter = ExtraFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Console handler
    if app.config.get("LOG_FORMAT") == "json":
        try:
            from pythonjsonlogger import json as jsonlogger

            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(jsonlogger.JsonFormatter(
                "%(timestamp)s %(level)s %(name)s %(message)s",
                rename_fields={"levelname": "level", "asctime": "timestamp"},
                timestamp=True,
            ))
        except ImportError:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(text_formatter)
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(text_formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    # File handler (rotating, always text format for easy reading)
    log_file = app.config.get("LOG_FILE")
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=app.config.get("LOG_FILE_MAX_BYTES", 10 * 1024 * 1024),
            backupCount=app.config.get("LOG_FILE_BACKUP_COUNT", 5),
            encoding="utf-8",
        )
        file_handler.setFormatter(text_formatter)
        root_logger.addHandler(file_handler)

    root_logger.setLevel(log_level)

    # Reduce noise from third-party libraries
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def create_app():
    """Flask application factory."""
    app = Flask(__name__)
    app.config.from_object(Config)

    # Logging
    setup_logging(app)

    # Extensions (CORS, rate limiter, Swagger)
    init_extensions(app)

    # Register blueprints
    from .api import register_blueprints
    register_blueprints(app)

    # Global error handlers
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": {"code": "NOT_FOUND", "message": str(e), "details": None}}), 404

    @app.errorhandler(422)
    def validation_error(e):
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": str(e), "details": None}}), 422

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"error": {"code": "RATE_LIMITED", "message": "Too many requests", "details": str(e)}}), 429

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": {"code": "INTERNAL_ERROR", "message": "Internal server error", "details": None}}), 500

    # Initialize task service (creates DB, starts thread pool)
    with app.app_context():
        from .services.task_service import task_service
        task_service.init_app(app)

    # Configure ARPEGE cache TTL from app config
    from .models.arpege_cache import configure_cache
    configure_cache(ttl_hours=app.config.get("ARPEGE_CACHE_TTL_HOURS", 6))

    # Start background maintenance scheduler (task purge, backup cleanup)
    from .maintenance import maintenance_scheduler
    maintenance_scheduler.init_app(app)

    logger = logging.getLogger(__name__)
    logger.info("Hydro Forecast API initialized")

    return app
