"""
Points API blueprint — read-only access to measurement point configurations.

Configs are managed directly via YAML files on disk (mounted as Docker volumes).
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

from flask import Blueprint, jsonify

from ..services import config_service
from ..services.config_service import PointNotFoundError

points_bp = Blueprint("points", __name__)


@points_bp.route("/points", methods=["GET"])
def list_points():
    """List all configured measurement points.
    ---
    tags:
      - Points
    responses:
      200:
        description: List of point IDs
        schema:
          type: object
          properties:
            points:
              type: array
              items:
                type: string
              example: ["ouysse"]
            count:
              type: integer
    """
    points = config_service.list_points()
    return jsonify({"points": points, "count": len(points)})


@points_bp.route("/points/<point_id>", methods=["GET"])
def get_point(point_id):
    """Get full configuration for a measurement point.
    ---
    tags:
      - Points
    parameters:
      - name: point_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Point configuration
      404:
        description: Point not found
    """
    try:
        config = config_service.load_point_config(point_id)
        return jsonify(config)
    except PointNotFoundError:
        return jsonify({"error": {
            "code": "POINT_NOT_FOUND",
            "message": f"Point '{point_id}' not found",
            "details": None,
        }}), 404
