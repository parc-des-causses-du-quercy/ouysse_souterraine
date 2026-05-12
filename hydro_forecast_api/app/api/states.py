"""
States API blueprint — read-only access to model states.

States are updated automatically after each forecast.
Manual overrides can be done by editing JSON files directly on disk.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

from flask import Blueprint, jsonify

from ..services import state_service
from ..services.config_service import PointNotFoundError, load_point_config

states_bp = Blueprint("states", __name__)


def _ensure_point_exists(point_id):
    try:
        load_point_config(point_id)
    except PointNotFoundError:
        return False
    return True


@states_bp.route("/points/<point_id>/states", methods=["GET"])
def get_all_states(point_id):
    """Get all component states for a measurement point.
    ---
    tags:
      - States
    parameters:
      - name: point_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: All component states
      404:
        description: Point not found
    """
    if not _ensure_point_exists(point_id):
        return jsonify({"error": {
            "code": "POINT_NOT_FOUND",
            "message": f"Point '{point_id}' not found",
            "details": None,
        }}), 404

    states = state_service.load_all_states(point_id)
    serializable = {}
    for component, state in states.items():
        serializable[component] = state_service._serialize_states(state)

    return jsonify({"point_id": point_id, "states": serializable})


@states_bp.route("/points/<point_id>/states/<component>", methods=["GET"])
def get_state(point_id, component):
    """Get state for a specific component.
    ---
    tags:
      - States
    parameters:
      - name: point_id
        in: path
        type: string
        required: true
      - name: component
        in: path
        type: string
        required: true
        description: Component name (e.g. "themines_gr4h", "karstmod")
    responses:
      200:
        description: Component state
      404:
        description: Point or component not found
    """
    if not _ensure_point_exists(point_id):
        return jsonify({"error": {
            "code": "POINT_NOT_FOUND",
            "message": f"Point '{point_id}' not found",
            "details": None,
        }}), 404

    state = state_service.load_state(point_id, component)
    if not state:
        return jsonify({"error": {
            "code": "STATE_NOT_FOUND",
            "message": f"No state found for component '{component}'",
            "details": None,
        }}), 404

    serializable = state_service._serialize_states(state)
    return jsonify({"point_id": point_id, "component": component, "state": serializable})
