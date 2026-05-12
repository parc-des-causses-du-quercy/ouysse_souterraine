"""
Health check endpoints — liveness and readiness.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import os

from flask import Blueprint, current_app, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def liveness():
    """Liveness check — is the process alive?
    ---
    tags:
      - Health
    responses:
      200:
        description: Service is alive
        schema:
          type: object
          properties:
            status:
              type: string
              example: ok
    """
    return jsonify({"status": "ok"})


@health_bp.route("/readiness", methods=["GET"])
def readiness():
    """Readiness check — can the service handle requests?
    ---
    tags:
      - Health
    responses:
      200:
        description: Service is ready
      503:
        description: Service is not ready
    """
    checks = {}
    ready = True

    # Check configs directory exists and has at least one config
    configs_path = current_app.config["CONFIGS_PATH"]
    configs_exist = os.path.exists(configs_path) and any(
        f.endswith((".yaml", ".yml")) for f in os.listdir(configs_path)
    ) if os.path.exists(configs_path) else False
    checks["configs"] = "ok" if configs_exist else "no configs found"
    if not configs_exist:
        ready = False

    # Check task DB is accessible
    try:
        from ..services.task_service import task_service
        task_service.list_tasks(limit=1)
        checks["task_db"] = "ok"
    except Exception as e:
        checks["task_db"] = str(e)
        ready = False

    # Check states directory
    states_path = current_app.config["STATES_PATH"]
    checks["states_dir"] = "ok" if os.path.exists(states_path) else "directory missing"

    status_code = 200 if ready else 503
    return jsonify({"status": "ready" if ready else "not ready", "checks": checks}), status_code
