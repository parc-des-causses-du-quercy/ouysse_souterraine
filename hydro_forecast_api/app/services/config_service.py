"""
Configuration service — load/save/validate point configurations from YAML files.

Includes in-memory caching with file mtime invalidation to avoid
redundant YAML parsing on repeated calls.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging
import os
import threading

import yaml
from flask import current_app

logger = logging.getLogger(__name__)

# In-memory config cache: {point_id: (mtime, config_dict)}
_config_cache = {}
_cache_lock = threading.Lock()


class ConfigServiceError(Exception):
    pass


class PointNotFoundError(ConfigServiceError):
    pass


def _configs_path():
    return current_app.config["CONFIGS_PATH"]


def _point_filepath(point_id):
    return os.path.join(_configs_path(), f"{point_id}.yaml")


def list_points():
    """List all configured point IDs."""
    path = _configs_path()
    if not os.path.exists(path):
        return []
    points = []
    for f in sorted(os.listdir(path)):
        if f.endswith(".yaml") or f.endswith(".yml"):
            points.append(f.rsplit(".", 1)[0])
    return points


def load_point_config(point_id):
    """Load a point configuration from YAML file.

    Uses in-memory cache with file mtime invalidation.

    Returns:
        dict with full point configuration

    Raises:
        PointNotFoundError if config file doesn't exist
    """
    filepath = _point_filepath(point_id)
    if not os.path.exists(filepath):
        raise PointNotFoundError(f"Point '{point_id}' not found")

    current_mtime = os.path.getmtime(filepath)

    with _cache_lock:
        cached = _config_cache.get(point_id)
        if cached and cached[0] == current_mtime:
            logger.debug("Config cache hit", extra={"point_id": point_id})
            return cached[1]

    with open(filepath, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    with _cache_lock:
        _config_cache[point_id] = (current_mtime, config)

    logger.debug("Loaded config", extra={"point_id": point_id})
    return config


def save_point_config(point_id, config):
    """Save a point configuration to YAML file."""
    os.makedirs(_configs_path(), exist_ok=True)
    filepath = _point_filepath(point_id)
    config["point_id"] = point_id
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    with _cache_lock:
        _config_cache.pop(point_id, None)
    logger.info("Saved config", extra={"point_id": point_id})


def delete_point_config(point_id):
    """Delete a point configuration file.

    Raises:
        PointNotFoundError if config file doesn't exist
    """
    filepath = _point_filepath(point_id)
    if not os.path.exists(filepath):
        raise PointNotFoundError(f"Point '{point_id}' not found")
    os.remove(filepath)
    with _cache_lock:
        _config_cache.pop(point_id, None)
    logger.info("Deleted config", extra={"point_id": point_id})


def validate_point_config(config):
    """Validate a point configuration dict.

    Returns:
        list of error messages (empty if valid)
    """
    errors = []

    if not config.get("point_id"):
        errors.append("point_id is required")
    if not config.get("latitude"):
        errors.append("latitude is required")

    # Validate karstmod section
    karstmod = config.get("karstmod", {})
    km_params = karstmod.get("params", {})
    required_km = ["RA", "kCS", "kMS", "kMC", "kEM", "kEC", "alphaMS", "alphaMC"]
    for p in required_km:
        if p not in km_params:
            errors.append(f"karstmod.params.{p} is required")

    km_grid = karstmod.get("arpege_grid", {})
    if not km_grid.get("indices") or not km_grid.get("weights"):
        errors.append("karstmod.arpege_grid.indices and weights are required")
    elif len(km_grid["indices"]) != len(km_grid["weights"]):
        errors.append("karstmod.arpege_grid: indices and weights must have same length")

    # Validate tributaries
    tributaries = config.get("tributaries", [])
    for i, trib in enumerate(tributaries):
        if not trib.get("basin_id"):
            errors.append(f"tributaries[{i}].basin_id is required")
        gr4h = trib.get("gr4h_params", {})
        for p in ["X1", "X2", "X3", "X4"]:
            if p not in gr4h:
                errors.append(f"tributaries[{i}].gr4h_params.{p} is required")
        if not trib.get("catchment_area_km2"):
            errors.append(f"tributaries[{i}].catchment_area_km2 is required")
        tgrid = trib.get("arpege_grid", {})
        if not tgrid.get("indices") or not tgrid.get("weights"):
            errors.append(f"tributaries[{i}].arpege_grid.indices and weights are required")
        elif len(tgrid["indices"]) != len(tgrid["weights"]):
            errors.append(f"tributaries[{i}].arpege_grid: indices and weights must have same length")

    # Validate qsink_formula
    qsink = config.get("qsink_formula", {})
    if "multiplier" not in qsink:
        errors.append("qsink_formula.multiplier is required")

    return errors
