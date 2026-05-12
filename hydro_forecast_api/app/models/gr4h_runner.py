"""
GR4H model runner — stateless wrapper around the hydrogr library.

Bypasses hydrogr's InputDataHandler (Python wrapper had a bug with the data
handler) and calls the Rust binding directly. Uses a dual-simulation pattern:
a short run that advances the reservoir state from T_state to T_target, and
a long run that produces the 96h forecast from the same loaded initial state.
The short run is what gets persisted; the long run is what the API serves.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging
import time

import numpy as np
import pandas as pd
from hydrogr import ModelGr4h
from hydrogr._hydrogr import gr4h as gr4h_rust

from .state_advance import compute_sim_window

logger = logging.getLogger(__name__)


def filter_by_datetime(df, lastQ_datetime):
    if lastQ_datetime:
        lastQ_datetime = pd.to_datetime(lastQ_datetime)
        return df[df.index >= lastQ_datetime].copy()
    return df.copy()


def assimilate_flow(outputs, flow_col, last_q):
    if last_q and len(outputs) > 0 and outputs[flow_col].iloc[0] != 0:
        correction_factor = last_q / outputs[flow_col].iloc[0]
        outputs[flow_col] = outputs[flow_col] * correction_factor
    return outputs


def _run_gr4h_direct(model, df):
    """Run hydrogr GR4H via the Rust binding, mutating model in place."""
    pr = df["precipitation"].values.astype(np.float64)
    pet = df["evapotranspiration"].values.astype(np.float64)
    parameters = [
        model.parameters["X1"], model.parameters["X2"],
        model.parameters["X3"], model.parameters["X4"],
    ]
    states = np.zeros(2, dtype=np.float64)
    states[0] = model.production_store * model.parameters["X1"]
    states[1] = model.routing_store * model.parameters["X3"]

    new_states, uh1, uh2, flow = gr4h_rust(
        parameters, pr, pet, states,
        model.uh1.copy(), model.uh2.copy(),
    )

    model.production_store = new_states[0] / model.parameters["X1"]
    model.routing_store = new_states[1] / model.parameters["X3"]
    model.uh1 = uh1
    model.uh2 = uh2
    return pd.DataFrame({"flow": flow}, index=df.index)


def run_gr4h(arpege_df, gr4h_params, catchment_area_km2, states=None,
             lastQ=None, lastQ_datetime=None, state_time=None):
    """
    Run GR4H for a single tributary basin with state-advance pattern.

    Args:
        arpege_df: DataFrame with [Date, precipitation, temperature, evapotranspiration].
        gr4h_params: dict with X1, X2, X3, X4.
        catchment_area_km2: basin surface area in km².
        states: dict with previous model states (or None for fresh run).
        lastQ: last observed flow in m³/s for assimilation (or None).
        lastQ_datetime: ISO datetime — both target instant for state advance and
                        cutoff for the response output.
        state_time: ISO datetime — instant represented by `states`. None for
                    legacy/fresh states (advancement is skipped on this run).

    Returns:
        (response_outputs, full_outputs, new_states):
            response_outputs: DataFrame filtered to lastQ_datetime onwards,
                              with assimilation applied. Columns: flow, flow_m3_s.
            full_outputs: DataFrame covering full ARPEGE horizon, no assimilation.
                          Used by the caller to compute qsink without bias.
            new_states: dict with updated model states + 'state_time' (ISO string).
    """
    t_start = time.time()
    df = arpege_df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")

    target_time = pd.to_datetime(lastQ_datetime) if lastQ_datetime else df.index[0]

    sim_mask, advance_mask, advance_hours = compute_sim_window(
        df.index, state_time, target_time
    )

    # (1) Short simulation — advance the loaded state to T_target
    model_advance = ModelGr4h(gr4h_params)
    if states:
        model_advance.set_states(states)
    if advance_mask.any():
        _run_gr4h_direct(model_advance, df[advance_mask])
    new_states = model_advance.get_states()
    new_states["state_time"] = target_time.isoformat()

    # (2) Long simulation — same loaded initial state, runs only on rows NOT
    # already consumed (everything after state_time, or full df for fresh state)
    model_forecast = ModelGr4h(gr4h_params)
    if states:
        model_forecast.set_states(states)
    df_sim = df[sim_mask]
    if len(df_sim) > 0:
        full_outputs = _run_gr4h_direct(model_forecast, df_sim)
    else:
        full_outputs = pd.DataFrame({"flow": []}, index=df_sim.index)
    full_outputs["flow_m3_s"] = full_outputs["flow"] / 3.6 * catchment_area_km2

    # Build response output: filter then assimilate
    response_outputs = filter_by_datetime(full_outputs[["flow"]], lastQ_datetime)
    if lastQ:
        lastQ_mm_h = lastQ * 3.6 / catchment_area_km2
        response_outputs = assimilate_flow(response_outputs, "flow", lastQ_mm_h)
    response_outputs["flow_m3_s"] = response_outputs["flow"] / 3.6 * catchment_area_km2

    logger.info("GR4H run completed", extra={
        "catchment_area_km2": catchment_area_km2,
        "output_length": len(response_outputs),
        "assimilation": lastQ is not None,
        "advance_hours": round(advance_hours, 2),
        "duration_seconds": round(time.time() - t_start, 3),
    })

    return response_outputs, full_outputs, new_states
