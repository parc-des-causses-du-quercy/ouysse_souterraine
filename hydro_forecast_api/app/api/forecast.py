"""
Forecast API blueprint — async forecast submission and task polling.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

from flask import Blueprint, jsonify, request

from ..extensions import limiter
from ..services.forecast_service import run_forecast
from ..services.task_service import task_service

forecast_bp = Blueprint("forecast", __name__)


@forecast_bp.route("/points/<point_id>/forecast", methods=["POST"])
@limiter.limit("10/minute")
def create_forecast(point_id):
    """Launch an async hydrological forecast for a measurement point.
    ---
    tags:
      - Forecasts
    parameters:
      - name: point_id
        in: path
        type: string
        required: true
        description: Measurement point identifier (e.g. "ouysse")
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            lastQ_datetime:
              type: string
              format: date-time
              description: Reference datetime for filtering (ISO 8601)
              example: "2026-03-12T14:00:00"
            tributaries:
              type: object
              description: Per-tributary assimilation data
              additionalProperties:
                type: object
                properties:
                  lastQ:
                    type: number
                    description: Last observed flow in m3/s
              example:
                themines: {lastQ: 2.28}
                alzou: {lastQ: 2.28}
            karstmod:
              type: object
              properties:
                lastQ:
                  type: number
                  description: Last observed outlet flow in m3/s
              example: {lastQ: 2.57}
            qsink_multiplier_override:
              type: number
              description: Override the Qsink multiplier from config
              example: null
            custom_meteo:
              type: object
              description: Custom meteorological data (replaces ARPEGE fetch). Keys are component names.
              example: null
    responses:
      202:
        description: Forecast task submitted
        schema:
          type: object
          properties:
            task_id:
              type: string
            point_id:
              type: string
            status:
              type: string
              enum: [pending]
            created_at:
              type: string
            poll_url:
              type: string
      404:
        description: Measurement point not found
      422:
        description: Invalid request body
      429:
        description: Rate limit exceeded
    """
    from ..services.config_service import PointNotFoundError, load_point_config

    # Validate point exists
    try:
        load_point_config(point_id)
    except PointNotFoundError:
        return jsonify({"error": {
            "code": "POINT_NOT_FOUND",
            "message": f"Point '{point_id}' not found",
            "details": None,
        }}), 404

    # Parse request body
    request_data = request.get_json(silent=True) or {}

    # Basic validation
    if not request_data.get("lastQ_datetime"):
        return jsonify({"error": {
            "code": "VALIDATION_ERROR",
            "message": "lastQ_datetime is required",
            "details": None,
        }}), 422

    # Submit async task
    task_info = task_service.submit_forecast(point_id, request_data, run_forecast)

    return jsonify(task_info), 202


@forecast_bp.route("/tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    """Get the status and result of a forecast task.
    ---
    tags:
      - Tasks
    parameters:
      - name: task_id
        in: path
        type: string
        required: true
        description: Task UUID
    responses:
      200:
        description: Task status and result
        schema:
          type: object
          properties:
            id:
              type: string
            point_id:
              type: string
            status:
              type: string
              enum: [pending, running, completed, failed]
            created_at:
              type: string
            started_at:
              type: string
            completed_at:
              type: string
            duration_seconds:
              type: number
            result:
              type: object
              description: Forecast result (only when status=completed)
            error:
              type: string
              description: Error message (only when status=failed)
      404:
        description: Task not found
    """
    task = task_service.get_task(task_id)
    if task is None:
        return jsonify({"error": {
            "code": "TASK_NOT_FOUND",
            "message": f"Task '{task_id}' not found",
            "details": None,
        }}), 404
    return jsonify(task)


@forecast_bp.route("/tasks", methods=["GET"])
def list_tasks():
    """List forecast tasks with optional filters.
    ---
    tags:
      - Tasks
    parameters:
      - name: point_id
        in: query
        type: string
        required: false
        description: Filter by measurement point
      - name: status
        in: query
        type: string
        required: false
        enum: [pending, running, completed, failed]
        description: Filter by task status
      - name: limit
        in: query
        type: integer
        required: false
        default: 50
        description: Maximum number of tasks to return
    responses:
      200:
        description: List of tasks
        schema:
          type: object
          properties:
            tasks:
              type: array
              items:
                type: object
            count:
              type: integer
    """
    point_id = request.args.get("point_id")
    status = request.args.get("status")
    limit = request.args.get("limit", 50, type=int)

    tasks = task_service.list_tasks(point_id=point_id, status=status, limit=limit)
    return jsonify({"tasks": tasks, "count": len(tasks)})


@forecast_bp.route("/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    """Delete a completed or failed task.
    ---
    tags:
      - Tasks
    parameters:
      - name: task_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Task deleted
      404:
        description: Task not found
    """
    deleted = task_service.delete_task(task_id)
    if not deleted:
        return jsonify({"error": {
            "code": "TASK_NOT_FOUND",
            "message": f"Task '{task_id}' not found",
            "details": None,
        }}), 404
    return jsonify({"message": "Task deleted"})
