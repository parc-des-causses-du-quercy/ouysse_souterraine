"""
Sensors API blueprint — discover input/output sensors for a measurement point.

Derived dynamically from the point's YAML configuration.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

from flask import Blueprint, jsonify

from ..services.config_service import PointNotFoundError, load_point_config

sensors_bp = Blueprint("sensors", __name__)


@sensors_bp.route("/points/<point_id>/sensors", methods=["GET"])
def get_sensors(point_id):
    """List sensors for a measurement point.
    ---
    tags:
      - Sensors
    parameters:
      - name: point_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: List of sensors with their roles
        schema:
          type: object
          properties:
            point_id:
              type: string
            sensors:
              type: array
              items:
                type: object
                properties:
                  name:
                    type: string
                    description: Sensor identifier (used in forecast request/response)
                  type:
                    type: string
                    enum: [tributary, outlet]
                  model:
                    type: string
                    enum: [gr4h, karstmod]
                  input:
                    type: boolean
                    description: Whether lastQ is expected as input
                  output:
                    type: boolean
                    description: Whether forecast values are returned
      404:
        description: Point not found
    """
    try:
        config = load_point_config(point_id)
    except PointNotFoundError:
        return jsonify({"error": {
            "code": "POINT_NOT_FOUND",
            "message": f"Point '{point_id}' not found",
            "details": None,
        }}), 404

    sensors = []

    # Tributaries (GR4H)
    for trib in config.get("tributaries", []):
        sensors.append({
            "name": trib["basin_id"],
            "type": "tributary",
            "model": "gr4h",
            "input": True,
            "output": True,
        })

    # Outlet (KarstMod) — uses point_id as sensor name
    sensors.append({
        "name": point_id,
        "type": "outlet",
        "model": "karstmod",
        "input": True,
        "output": True,
    })

    return jsonify({"point_id": point_id, "sensors": sensors})
