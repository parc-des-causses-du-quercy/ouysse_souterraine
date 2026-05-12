"""
State service — manage model states per point with backup and file locking.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import json
import logging
import os
import shutil
from datetime import datetime, timedelta

import numpy as np
from filelock import FileLock
from flask import current_app

logger = logging.getLogger(__name__)


def _states_path():
    return current_app.config["STATES_PATH"]


def _backups_path():
    return current_app.config["BACKUPS_PATH"]


def _point_states_dir(point_id):
    return os.path.join(_states_path(), point_id)


def _state_filepath(point_id, component):
    return os.path.join(_point_states_dir(point_id), f"{component}.json")


def _lock_filepath(point_id, component):
    return _state_filepath(point_id, component) + ".lock"


def _serialize_states(states):
    """Convert numpy arrays to lists for JSON serialization."""
    return {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in states.items()}


def _deserialize_states(states):
    """Convert lists back to numpy arrays."""
    return {k: np.array(v) if isinstance(v, list) else v for k, v in states.items()}


def load_state(point_id, component, default=None):
    """Load state for a specific component of a point.

    Args:
        point_id: measurement point identifier
        component: component name (e.g., 'themines_gr4h', 'karstmod')
        default: default state dict if file doesn't exist

    Returns:
        dict with state values
    """
    filepath = _state_filepath(point_id, component)
    if not os.path.exists(filepath):
        logger.debug("State file not found, using defaults", extra={
            "point_id": point_id, "component": component
        })
        return default or {}

    lock = FileLock(_lock_filepath(point_id, component), timeout=30)
    with lock:
        with open(filepath, "r") as f:
            states = json.load(f)
    return _deserialize_states(states)


def save_state(point_id, component, states):
    """Save state for a specific component with automatic backup.

    Uses write-to-temp-then-rename for atomic writes.
    """
    dirpath = _point_states_dir(point_id)
    os.makedirs(dirpath, exist_ok=True)

    filepath = _state_filepath(point_id, component)

    # Backup existing state before overwriting
    if os.path.exists(filepath):
        _backup_state(point_id, component, filepath)

    lock = FileLock(_lock_filepath(point_id, component), timeout=30)
    with lock:
        tmp_filepath = filepath + ".tmp"
        with open(tmp_filepath, "w") as f:
            json.dump(_serialize_states(states), f)
        # Atomic rename
        os.replace(tmp_filepath, filepath)

    logger.debug("State saved", extra={"point_id": point_id, "component": component})


def load_all_states(point_id):
    """Load all component states for a point.

    Returns:
        dict of {component_name: state_dict}
    """
    dirpath = _point_states_dir(point_id)
    if not os.path.exists(dirpath):
        return {}

    states = {}
    for f in os.listdir(dirpath):
        if f.endswith(".json"):
            component = f[:-5]  # remove .json
            states[component] = load_state(point_id, component)
    return states


def save_all_states(point_id, states_dict):
    """Save all component states for a point.

    Args:
        states_dict: dict of {component_name: state_dict}
    """
    for component, states in states_dict.items():
        save_state(point_id, component, states)


def delete_all_states(point_id):
    """Delete all states for a point (reset to defaults)."""
    dirpath = _point_states_dir(point_id)
    if os.path.exists(dirpath):
        # Backup before delete
        _backup_all_states(point_id)
        shutil.rmtree(dirpath)
        logger.info("All states deleted", extra={"point_id": point_id})


def _backup_state(point_id, component, filepath):
    """Backup a single state file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(_backups_path(), point_id, timestamp)
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, f"{component}.json")
    shutil.copy2(filepath, backup_path)


def _backup_all_states(point_id):
    """Backup all states for a point."""
    dirpath = _point_states_dir(point_id)
    if not os.path.exists(dirpath):
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(_backups_path(), point_id, timestamp)
    shutil.copytree(dirpath, backup_dir)
    logger.info("States backed up", extra={"point_id": point_id, "backup": backup_dir})


def cleanup_old_backups(retention_days=None):
    """Remove backups older than retention_days."""
    if retention_days is None:
        retention_days = current_app.config.get("BACKUP_RETENTION_DAYS", 7)

    backups_path = _backups_path()
    if not os.path.exists(backups_path):
        return

    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0

    for point_id in os.listdir(backups_path):
        point_backup_dir = os.path.join(backups_path, point_id)
        if not os.path.isdir(point_backup_dir):
            continue
        for timestamp_dir in os.listdir(point_backup_dir):
            try:
                ts = datetime.strptime(timestamp_dir, "%Y%m%d_%H%M%S")
                if ts < cutoff:
                    shutil.rmtree(os.path.join(point_backup_dir, timestamp_dir))
                    removed += 1
            except ValueError:
                continue

    if removed:
        logger.info("Cleaned up old backups", extra={"removed": removed})
