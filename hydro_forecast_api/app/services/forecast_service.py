"""
Forecast service — orchestrates the full forecast pipeline.

Loads config, fetches weather data, runs GR4H + KarstMod, manages states.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging
import time

import numpy as np
import pandas as pd

from . import config_service, state_service
from ..api.metrics import record_state_reset
from ..models.arpege_fetcher import fetch_arpege_for_grids, parse_custom_meteo
from ..models.gr4h_runner import run_gr4h
from ..models.karstmod_runner import run_karstmod
from ..models.state_advance import (
    ADVANCE_MAX_HOURS,
    AUTO_RESET_MAX_HOURS,
    StateAdvanceError,
)

logger = logging.getLogger(__name__)


class ForecastError(Exception):
    """Forecast pipeline error.

    Optional `code` attribute lets the API/task layers serialize a structured
    error identifier (e.g. STATE_TOO_OLD_FOR_AUTO_RESET) on top of the message.
    """

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _max_state_age_hours(point_id, target_time):
    """Largest gap (hours) between any saved state_time and target_time.

    Returns 0.0 if no state is persisted yet (cold start). Used to decide
    whether an auto-reset is allowed (gap <= AUTO_RESET_MAX_HOURS) or must
    be refused for human intervention.
    """
    target_ts = pd.to_datetime(target_time)
    states = state_service.load_all_states(point_id)
    max_gap = 0.0
    for s in states.values():
        st = s.get("state_time") if isinstance(s, dict) else None
        if st is None:
            continue
        gap = (target_ts - pd.to_datetime(st)).total_seconds() / 3600.0
        if gap > max_gap:
            max_gap = gap
    return max_gap


def run_forecast(point_id, request_data):
    """
    Execute a full forecast for a measurement point with auto-recovery.

    This function is called by the task service in a worker thread.

    If the persisted state is more than ADVANCE_MAX_HOURS (24h) behind the
    target but at most AUTO_RESET_MAX_HOURS (168h = 7d), the state is
    auto-reset (backed up then deleted) and the forecast is retried once
    from defaults. The response carries `metadata.state_was_reset=true` and
    `metadata.reset_reason`.

    Beyond AUTO_RESET_MAX_HOURS, the forecast is refused with a
    `STATE_TOO_OLD_FOR_AUTO_RESET` error code — manual intervention is
    required (see CONTRIBUTING.md § "Reprise après dérive d'état").

    Args:
        point_id: measurement point identifier
        request_data: dict with keys:
            - lastQ_datetime: ISO datetime string
            - tributaries: {basin_id: {"lastQ": float|None}}
            - karstmod: {"lastQ": float|None}
            - qsink_multiplier_override: float|None
            - custom_meteo: dict|None

    Returns:
        dict with forecast results
    """
    try:
        result = _run_forecast_once(point_id, request_data)
        result["metadata"]["state_was_reset"] = False
        result["metadata"]["reset_reason"] = None
        return result
    except StateAdvanceError as e:
        target = request_data.get("lastQ_datetime")
        advance_hours = _max_state_age_hours(point_id, target)
        if advance_hours > AUTO_RESET_MAX_HOURS:
            logger.critical("State too old for auto-reset", extra={
                "point_id": point_id,
                "advance_hours": round(advance_hours, 2),
                "limit_hours": AUTO_RESET_MAX_HOURS,
                "alarm": "STATE_TOO_OLD_FOR_AUTO_RESET",
            })
            raise ForecastError(
                f"State is {advance_hours:.1f}h behind target. "
                f"Auto-reset refused beyond {AUTO_RESET_MAX_HOURS}h "
                f"({AUTO_RESET_MAX_HOURS // 24}d). Manual intervention required: "
                "see CONTRIBUTING.md § 'Reprise après dérive d'état'.",
                code="STATE_TOO_OLD_FOR_AUTO_RESET",
            ) from e

        logger.error("Auto-resetting state", extra={
            "point_id": point_id,
            "advance_hours": round(advance_hours, 2),
            "alarm": "STATE_AUTO_RESET",
        })
        state_service.delete_all_states(point_id)
        record_state_reset(point_id, "age")
        result = _run_forecast_once(point_id, request_data)
        result["metadata"]["state_was_reset"] = True
        result["metadata"]["reset_reason"] = (
            f"State was {advance_hours:.1f}h behind target "
            f"(>{ADVANCE_MAX_HOURS}h advance limit). "
            "Reservoirs reset to YAML defaults; "
            "forecasts at T+24..T+96h may be degraded for 24-48h."
        )
        return result


def _run_forecast_once(point_id, request_data):
    """Single-pass forecast execution. Raises StateAdvanceError if a saved
    state is more than ADVANCE_MAX_HOURS behind target — caller decides
    whether to auto-reset and retry."""
    # 1. Load point config
    config = config_service.load_point_config(point_id)
    latitude = config["latitude"]
    tributaries_config = config.get("tributaries", [])
    karstmod_config = config["karstmod"]
    qsink_multiplier = config.get("qsink_formula", {}).get("multiplier", 1.0)

    if request_data.get("qsink_multiplier_override") is not None:
        qsink_multiplier = request_data["qsink_multiplier_override"]

    lastQ_datetime = request_data.get("lastQ_datetime")
    trib_requests = request_data.get("tributaries", {})
    karstmod_request = request_data.get("karstmod", {})

    # 2. Build ARPEGE grids for all components
    all_grids = {}
    for trib in tributaries_config:
        all_grids[trib["basin_id"]] = trib["arpege_grid"]
    all_grids["karst"] = karstmod_config["arpege_grid"]

    # 3. Fetch weather data (ARPEGE or custom)
    t_arpege = time.time()
    custom_meteo = request_data.get("custom_meteo")
    if custom_meteo:
        arpege_data, arpege_ref_time = parse_custom_meteo(custom_meteo)
    else:
        try:
            arpege_data, arpege_ref_time = fetch_arpege_for_grids(all_grids, latitude)
        except Exception as e:
            raise ForecastError(f"Failed to fetch ARPEGE data: {e}") from e
    duration_arpege = time.time() - t_arpege

    # 4. Clean old backups
    try:
        state_service.cleanup_old_backups()
    except Exception:
        pass  # Non-critical

    # 5. Run GR4H for each tributary
    t_gr4h_start = time.time()
    tributary_results = {}
    tributary_full_outputs = {}
    new_states = {}
    active_tributaries = []

    for trib in tributaries_config:
        basin_id = trib["basin_id"]
        if basin_id not in arpege_data:
            logger.warning("No ARPEGE data for tributary", extra={
                "point_id": point_id, "basin_id": basin_id
            })
            continue

        trib_req = trib_requests.get(basin_id, {})
        lastQ = trib_req.get("lastQ")

        # Load previous GR4H states (state_time is extracted then dropped
        # from the dict so hydrogr's set_states only sees model fields)
        gr4h_component = f"{basin_id}_gr4h"
        gr4h_states = state_service.load_state(point_id, gr4h_component)
        gr4h_state_time = gr4h_states.pop("state_time", None) if gr4h_states else None

        outputs, full_outputs, gr4h_new_states = run_gr4h(
            arpege_df=arpege_data[basin_id],
            gr4h_params=trib["gr4h_params"],
            catchment_area_km2=trib["catchment_area_km2"],
            states=gr4h_states if gr4h_states else None,
            lastQ=lastQ,
            lastQ_datetime=lastQ_datetime,
            state_time=gr4h_state_time,
        )

        tributary_results[basin_id] = outputs
        tributary_full_outputs[basin_id] = full_outputs
        new_states[gr4h_component] = gr4h_new_states
        active_tributaries.append(basin_id)

    duration_gr4h = time.time() - t_gr4h_start

    # 6. Combine tributary flows into Qsink (use unfiltered, non-assimilated
    # series). Tributary full_outputs cover only the simulation window
    # (rows > state_time); we splice them into a full-length array aligned
    # with the karst ARPEGE time axis. Pre-state_time positions stay 0 —
    # KarstMod will skip them via its own sim_mask.
    if not tributary_full_outputs:
        raise ForecastError("No tributary results available")

    sample_full_outputs = next(iter(tributary_full_outputs.values()))
    sim_window_idx = sample_full_outputs.index

    trib_sum = np.zeros(len(sim_window_idx), dtype=np.float64)
    for r in tributary_full_outputs.values():
        trib_sum += r["flow_m3_s"].values
    qsink_window = trib_sum * qsink_multiplier

    karst_arpege = arpege_data["karst"]
    karst_full_idx = pd.DatetimeIndex(pd.to_datetime(karst_arpege["Date"]))
    qsink_full = np.zeros(len(karst_full_idx), dtype=np.float64)
    positions = karst_full_idx.get_indexer(sim_window_idx)
    if (positions == -1).any():
        raise ForecastError(
            "ARPEGE time axis mismatch between tributaries and karst"
        )
    qsink_full[positions] = qsink_window

    # 7. Run KarstMod
    karstmod_states = state_service.load_state(
        point_id, "karstmod",
        default={"wlE_final": 0.0, "C_final": 0.0, "M_final": 0.0}
    )
    karstmod_state_time = karstmod_states.pop("state_time", None) if karstmod_states else None

    t_karstmod = time.time()

    outlet_outputs, km_new_states = run_karstmod(
        arpege_df=karst_arpege,
        qsink_full_m3_s=qsink_full,
        params=karstmod_config["params"],
        states=karstmod_states,
        lastQ=karstmod_request.get("lastQ"),
        lastQ_datetime=lastQ_datetime,
        state_time=karstmod_state_time,
    )
    duration_karstmod = time.time() - t_karstmod
    new_states["karstmod"] = km_new_states

    # 8. Save all new states
    t_save = time.time()
    state_service.save_all_states(point_id, new_states)
    duration_save = time.time() - t_save

    # 9. Build compact response
    assimilation_applied = (
        karstmod_request.get("lastQ") is not None
        or any(trib_requests.get(t, {}).get("lastQ") is not None for t in active_tributaries)
    )

    # Build records: sensor_name -> [[offset_hours, value], ...]
    records = {}

    # Outlet (sensor name = point_id)
    t0 = outlet_outputs.index[0]
    records[point_id] = [
        [int((t - t0).total_seconds() / 3600), round(float(v), 4)]
        for t, v in zip(outlet_outputs.index, outlet_outputs["flow_m3_s"].values)
    ]

    # Tributaries
    for basin_id, outputs in tributary_results.items():
        t0_trib = outputs.index[0]
        records[basin_id] = [
            [int((t - t0_trib).total_seconds() / 3600), round(float(v), 4)]
            for t, v in zip(outputs.index, outputs["flow_m3_s"].values)
        ]

    result = {
        "forecast_date": lastQ_datetime,
        "offset_unit": "hours",
        "arpege_reference_time": arpege_ref_time,
        "records": records,
        "metadata": {
            "assimilation_applied": assimilation_applied,
            "active_tributaries": active_tributaries,
            "qsink_multiplier": qsink_multiplier,
        },
    }

    logger.info("Forecast completed", extra={
        "point_id": point_id,
        "outlet_timesteps": len(outlet_outputs),
        "active_tributaries": active_tributaries,
        "duration_arpege_seconds": round(duration_arpege, 2),
        "duration_gr4h_seconds": round(duration_gr4h, 2),
        "duration_karstmod_seconds": round(duration_karstmod, 2),
        "duration_save_seconds": round(duration_save, 2),
        "duration_total_seconds": round(duration_arpege + duration_gr4h + duration_karstmod + duration_save, 2),
    })

    return result
