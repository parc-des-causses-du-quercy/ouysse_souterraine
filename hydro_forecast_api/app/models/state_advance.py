"""
State advancement helper — derives the advance and forecast windows from
the saved state's timestamp.

Lets runners advance the saved reservoir states by exactly the time elapsed
since the previous run (T_target - T_state), regardless of run cadence,
and run the forecast simulation only on data not already consumed.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ADVANCE_WARN_HOURS = 6
ADVANCE_MAX_HOURS = 24
# Hard ceiling above which even an auto-reset is refused: forces a human
# check that the upstream data outage has actually been resolved before
# the API repairs itself.
AUTO_RESET_MAX_HOURS = 168  # 7 days
# Tolerance when state_time precedes the start of available ARPEGE data
# (typical when ARPEGE rolls forward between two slow-cadence assimilation
# updates). Below this, we silently clip the advance window to start at
# ARPEGE_start instead of raising — the lost meteo of that small window
# is hydrologically negligible compared to a full state reset.
BACKWARD_TOLERANCE_HOURS = 6


class StateAdvanceError(Exception):
    pass


def compute_sim_window(df_index, state_time, target_time):
    """
    Determine which rows of df to feed into the advance and forecast simulations.

    Args:
        df_index: pandas DatetimeIndex of the meteorological data.
        state_time: ISO string or pd.Timestamp — instant represented by the
                    loaded state. None for legacy/fresh states.
        target_time: ISO string or pd.Timestamp — instant we want the
                     advanced state to represent (typically lastQ_datetime).

    Returns:
        (sim_mask, advance_mask, advance_hours):
            sim_mask: bool array selecting rows for the long forecast sim
                      (everything after state_time, or all rows if None).
            advance_mask: bool array selecting rows in ]state_time, target_time]
                          (or up to target_time if state_time is None) used
                          to advance the saved state to the new target.
            advance_hours: float, the gap in hours between state and target.

    Raises:
        StateAdvanceError if the gap exceeds ADVANCE_MAX_HOURS or if
        state_time precedes the available ARPEGE data.
    """
    target_ts = pd.to_datetime(target_time)

    if state_time is None:
        sim_mask = np.ones(len(df_index), dtype=bool)
        advance_mask = np.asarray(df_index <= target_ts)
        return sim_mask, advance_mask, 0.0

    state_ts = pd.to_datetime(state_time)
    advance_hours = (target_ts - state_ts).total_seconds() / 3600.0

    if advance_hours <= 0:
        sim_mask = np.asarray(df_index > state_ts)
        advance_mask = np.zeros(len(df_index), dtype=bool)
        return sim_mask, advance_mask, advance_hours

    if advance_hours > ADVANCE_MAX_HOURS:
        raise StateAdvanceError(
            f"State is {advance_hours:.1f}h behind target "
            f"(>{ADVANCE_MAX_HOURS}h limit). "
            f"forecast_service should auto-reset if gap <= {AUTO_RESET_MAX_HOURS}h."
        )

    data_start = df_index.min()
    if state_ts < data_start:
        # ARPEGE rolled forward past state_time. If the gap is small (typical
        # when slow-cadence assimilation makes target_time lag and ARPEGE
        # advances between two updates), clip the advance window to start at
        # data_start. The lost meteo is short and `lastQ` reassimilates the
        # outlet at target_time, so the bias is negligible.
        backward_gap_hours = (data_start - state_ts).total_seconds() / 3600.0
        if backward_gap_hours > BACKWARD_TOLERANCE_HOURS:
            raise StateAdvanceError(
                f"ARPEGE data starts at {data_start.isoformat()} but "
                f"state_time is {state_ts.isoformat()} ({backward_gap_hours:.1f}h "
                f"before, > {BACKWARD_TOLERANCE_HOURS}h tolerance) — cannot "
                "advance from before available data. forecast_service should "
                f"auto-reset if forward gap <= {AUTO_RESET_MAX_HOURS}h."
            )
        logger.info(
            "State precedes ARPEGE; clipping advance to data start",
            extra={
                "state_time": state_ts.isoformat(),
                "data_start": data_start.isoformat(),
                "backward_gap_hours": round(backward_gap_hours, 2),
            },
        )
        # Clip so downstream masks treat the state as if represented at
        # data_start. The state itself is unchanged; only the advance window
        # boundary moves.
        state_ts = data_start - pd.Timedelta(seconds=1)

    if advance_hours > ADVANCE_WARN_HOURS:
        logger.info(
            "State advance window larger than usual",
            extra={"advance_hours": round(advance_hours, 2)},
        )

    sim_mask = np.asarray(df_index > state_ts)
    advance_mask = np.asarray((df_index > state_ts) & (df_index <= target_ts))
    return sim_mask, advance_mask, advance_hours
