"""
Prometheus metrics endpoint.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import time

from flask import Blueprint, Response, current_app, g, request

metrics_bp = Blueprint("metrics", __name__)

# Simple in-memory counters (thread-safe via GIL for basic operations)
_counters = {
    "forecast_requests_total": {},  # {point_id: {status: count}}
    "http_requests_total": {},      # {method_path: count}
    "state_resets_total": {},       # {point_id_reason: count}
}
_histograms = {
    "forecast_duration_seconds": [],  # list of (point_id, duration)
    "request_duration_seconds": [],   # list of (method_path, duration)
}


def record_forecast_request(point_id, status):
    """Record a forecast request metric."""
    key = f"{point_id}_{status}"
    _counters["forecast_requests_total"][key] = _counters["forecast_requests_total"].get(key, 0) + 1


def record_forecast_duration(point_id, duration):
    """Record forecast duration."""
    _histograms["forecast_duration_seconds"].append((point_id, duration))
    # Keep only last 1000 entries
    if len(_histograms["forecast_duration_seconds"]) > 1000:
        _histograms["forecast_duration_seconds"] = _histograms["forecast_duration_seconds"][-1000:]


def record_state_reset(point_id, reason):
    """Record an auto-reset event for a point.

    Reasons: 'age' (gap > ADVANCE_MAX_HOURS but <= AUTO_RESET_MAX_HOURS).
    """
    key = f"{point_id}|{reason}"
    _counters["state_resets_total"][key] = _counters["state_resets_total"].get(key, 0) + 1


@metrics_bp.before_app_request
def _start_timer():
    g.start_time = time.time()


@metrics_bp.after_app_request
def _record_request(response):
    if hasattr(g, "start_time"):
        duration = time.time() - g.start_time
        key = f"{request.method}_{request.path}"
        _counters["http_requests_total"][key] = _counters["http_requests_total"].get(key, 0) + 1
        _histograms["request_duration_seconds"].append((key, duration))
        if len(_histograms["request_duration_seconds"]) > 1000:
            _histograms["request_duration_seconds"] = _histograms["request_duration_seconds"][-1000:]
    return response


@metrics_bp.route("/metrics", methods=["GET"])
def prometheus_metrics():
    """Prometheus-compatible metrics endpoint.
    ---
    tags:
      - Monitoring
    responses:
      200:
        description: Prometheus metrics in text format
    """
    if not current_app.config.get("PROMETHEUS_ENABLED", True):
        return Response("# Prometheus metrics disabled\n", mimetype="text/plain")

    lines = []

    # Forecast requests counter
    lines.append("# HELP forecast_requests_total Total number of forecast requests")
    lines.append("# TYPE forecast_requests_total counter")
    for key, count in _counters["forecast_requests_total"].items():
        parts = key.rsplit("_", 1)
        if len(parts) == 2:
            lines.append(f'forecast_requests_total{{point_id="{parts[0]}",status="{parts[1]}"}} {count}')

    # HTTP requests counter
    lines.append("# HELP http_requests_total Total HTTP requests")
    lines.append("# TYPE http_requests_total counter")
    for key, count in _counters["http_requests_total"].items():
        lines.append(f'http_requests_total{{endpoint="{key}"}} {count}')

    # State auto-resets counter
    lines.append("# HELP state_resets_total Auto-resets triggered when state drift exceeds ADVANCE_MAX_HOURS")
    lines.append("# TYPE state_resets_total counter")
    for key, count in _counters["state_resets_total"].items():
        parts = key.split("|", 1)
        if len(parts) == 2:
            lines.append(f'state_resets_total{{point_id="{parts[0]}",reason="{parts[1]}"}} {count}')

    # Forecast duration summary
    durations = _histograms["forecast_duration_seconds"]
    if durations:
        lines.append("# HELP forecast_duration_seconds Forecast execution duration")
        lines.append("# TYPE forecast_duration_seconds summary")
        values = [d[1] for d in durations]
        lines.append(f"forecast_duration_seconds_count {len(values)}")
        lines.append(f"forecast_duration_seconds_sum {sum(values):.2f}")

    # Tasks in queue
    try:
        from ..services.task_service import task_service
        pending = len(task_service.list_tasks(status="pending"))
        running = len(task_service.list_tasks(status="running"))
        lines.append("# HELP tasks_in_queue Number of tasks in queue")
        lines.append("# TYPE tasks_in_queue gauge")
        lines.append(f'tasks_in_queue{{status="pending"}} {pending}')
        lines.append(f'tasks_in_queue{{status="running"}} {running}')
    except Exception:
        pass

    return Response("\n".join(lines) + "\n", mimetype="text/plain; charset=utf-8")
