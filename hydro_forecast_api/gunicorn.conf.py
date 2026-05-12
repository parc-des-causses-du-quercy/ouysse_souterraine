"""Gunicorn configuration file."""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging

# Endpoints polled automatically (Docker healthcheck, Prometheus scraper, k8s probes)
_NOISE_PATHS = ("/health", "/readiness", "/metrics", "/api/v1/tasks/")


class NoiseFilter(logging.Filter):
    """Filter out monitoring/probe requests from access logs."""

    def filter(self, record):
        msg = record.getMessage()
        return not any(path in msg for path in _NOISE_PATHS)


bind = "0.0.0.0:5000"
# Single worker on purpose: the ARPEGE in-memory cache and task_service
# singleton must be unique. Forecast execution runs in a separate
# ThreadPoolExecutor thread (see app/services/task_service.py), so HTTP
# serving stays responsive on the gthread pool while a long ARPEGE fetch
# (1-3 min) is in progress — cfgrib/socket IO release the GIL during the
# fetch, letting the HTTP threads serve polling/health/metrics in parallel.
workers = 1
threads = 4
worker_class = "gthread"  # explicit (auto-applied when threads > 1, but worth stating)
preload_app = True
timeout = 300
accesslog = "-"


def on_starting(server):
    """Attach noise filter to Gunicorn access logger."""
    gunicorn_access_logger = logging.getLogger("gunicorn.access")
    gunicorn_access_logger.addFilter(NoiseFilter())
