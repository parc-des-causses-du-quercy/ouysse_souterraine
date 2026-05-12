"""
KarstMod model runner — stateless wrapper around karstmod_engine.

Uses the same dual-simulation pattern as gr4h_runner: a short run that
advances the reservoir state from T_state to T_target (persisted), and a
long run that produces the 96h forecast from the same loaded initial
state (returned to the caller).
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging
import time

import numpy as np
import pandas as pd

from .karstmod_engine import karstmod_engine, to_q_mm_h
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


def _engine_kwargs(params):
    return dict(
        Emin=params.get("Emin", -15.0),
        kEM=params["kEM"], aEM=params.get("aEM", 1.0),
        kEC=params["kEC"], aEC=params.get("aEC", 1.0),
        kES=params.get("kES", 0.0), aES=params.get("aES", 1.0),
        kloss=params.get("kloss", 0.0), aloss=params.get("aloss", 1.0),
        Eloss=params.get("Eloss", 1e5),
        kCS=params["kCS"], aCS=1.0,
        kMS=params["kMS"], aMS=params["alphaMS"],
        kMC=params["kMC"], aMC=params["alphaMC"],
    )


def run_karstmod(arpege_df, qsink_full_m3_s, params, states=None,
                 lastQ=None, lastQ_datetime=None, state_time=None):
    """
    Run KarstMod for the karst outlet with state-advance pattern.

    Args:
        arpege_df: DataFrame with [Date, precipitation, temperature, evapotranspiration].
        qsink_full_m3_s: numpy array of sink discharge in m³/s, covering the
                         full ARPEGE horizon (same length as arpege_df).
        params: KarstMod parameters dict (RA, kCS, kMS, kMC, kEM, kEC,
                alphaMS, alphaMC, plus optional Emin/aEM/aEC/kES/...).
        states: dict with wlE_final, C_final, M_final (or None for defaults).
        lastQ: observed outlet discharge in m³/s for assimilation (or None).
        lastQ_datetime: ISO datetime — target instant for state advance and
                        cutoff for the response output.
        state_time: ISO datetime — instant represented by `states`. None for
                    legacy/fresh states (advancement is skipped on this run).

    Returns:
        (response_outputs, new_states):
            response_outputs: DataFrame from lastQ_datetime onwards with
                              assimilation applied. Single column: flow_m3_s.
            new_states: dict with wlE_final, C_final, M_final, state_time.
    """
    t_start = time.time()
    df = arpege_df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")

    if states is None:
        states = {"wlE_final": 0.0, "C_final": 0.0, "M_final": 0.0}

    RA = params["RA"]
    qsink_full_mm_h = to_q_mm_h(np.array(qsink_full_m3_s, dtype=np.float64), RA)

    if len(qsink_full_mm_h) != len(df):
        raise ValueError(
            f"qsink length ({len(qsink_full_mm_h)}) does not match ARPEGE "
            f"length ({len(df)}) — they must cover the same horizon."
        )

    target_time = pd.to_datetime(lastQ_datetime) if lastQ_datetime else df.index[0]
    engine_kwargs = _engine_kwargs(params)

    sim_mask, advance_mask, advance_hours = compute_sim_window(
        df.index, state_time, target_time
    )

    # (1) Short simulation — advance the loaded state to T_target
    if advance_mask.any():
        advance_idx = np.flatnonzero(advance_mask)
        _, wlE_adv, C_adv, M_adv = karstmod_engine(
            pr=df["precipitation"].values[advance_idx].astype(np.float64),
            pet=df["evapotranspiration"].values[advance_idx].astype(np.float64),
            qsink_mm=qsink_full_mm_h[advance_idx],
            area=RA,
            wlE_initial=states["wlE_final"],
            C_initial=states["C_final"],
            M_initial=states["M_final"],
            **engine_kwargs,
        )
        new_states = {
            "wlE_final": float(wlE_adv),
            "C_final": float(C_adv),
            "M_final": float(M_adv),
            "state_time": target_time.isoformat(),
        }
    else:
        new_states = {
            "wlE_final": float(states["wlE_final"]),
            "C_final": float(states["C_final"]),
            "M_final": float(states["M_final"]),
            "state_time": target_time.isoformat(),
        }

    # (2) Long simulation — same loaded initial state, runs only on rows NOT
    # already consumed (everything after state_time, or full df for fresh state)
    sim_idx = np.flatnonzero(sim_mask)
    df_sim = df.iloc[sim_idx]
    qsink_sim_mm_h = qsink_full_mm_h[sim_idx]

    qsim, *_ = karstmod_engine(
        pr=df_sim["precipitation"].values.astype(np.float64),
        pet=df_sim["evapotranspiration"].values.astype(np.float64),
        qsink_mm=qsink_sim_mm_h,
        area=RA,
        wlE_initial=states["wlE_final"],
        C_initial=states["C_final"],
        M_initial=states["M_final"],
        **engine_kwargs,
    )

    full_outputs = pd.DataFrame({"flow_m3_s": qsim}, index=df_sim.index)
    outputs = filter_by_datetime(full_outputs, lastQ_datetime)
    if lastQ:
        outputs = assimilate_flow(outputs, "flow_m3_s", lastQ)

    logger.info("KarstMod run completed", extra={
        "RA": RA,
        "output_length": len(outputs),
        "assimilation": lastQ is not None,
        "advance_hours": round(advance_hours, 2),
        "duration_seconds": round(time.time() - t_start, 3),
    })

    return outputs, new_states
