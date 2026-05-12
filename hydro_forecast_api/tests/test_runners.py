"""Tests for the GR4H and KarstMod runners — focus on the dual-simulation
pattern that replaces the previous +96h state-saving bug.

These tests don't need Flask or filesystem. They exercise the runners
directly with synthetic meteorology to validate the state-advance logic
and the Rust-direct GR4H call.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.models.gr4h_runner import run_gr4h, _run_gr4h_direct
from app.models.karstmod_runner import run_karstmod
from app.models.state_advance import (
    StateAdvanceError,
    compute_sim_window,
    ADVANCE_MAX_HOURS,
    BACKWARD_TOLERANCE_HOURS,
)
from hydrogr import ModelGr4h, InputDataHandler


GR4H_PARAMS = {"X1": 290.0, "X2": -1.8, "X3": 59.0, "X4": 5.0}
CATCHMENT_AREA = 55.0


def _make_arpege(n_hours=80, start="2026-05-04T00:00:00", seed=42):
    """Synthetic ARPEGE-like dataframe with a few rain events."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start, periods=n_hours, freq="h")
    pluie = np.zeros(n_hours)
    rain_events = rng.choice(n_hours, size=max(1, n_hours // 12), replace=False)
    for ev in rain_events:
        duration = rng.integers(2, 8)
        intensity = rng.exponential(1.5)
        end = min(ev + duration, n_hours)
        pluie[ev:end] = intensity * np.exp(-0.3 * np.arange(end - ev))
    temperature = 12 + 6 * np.sin(np.arange(n_hours) * 2 * np.pi / 24)
    et = np.full(n_hours, 0.05)
    return pd.DataFrame({
        "Date": dates,
        "precipitation": pluie,
        "temperature": temperature,
        "evapotranspiration": et,
    })


# -------------------------- compute_sim_window --------------------------


def test_sim_window_no_state_runs_full_df():
    df = _make_arpege(20)
    df.set_index("Date", inplace=True)
    sim_mask, advance_mask, advance_hours = compute_sim_window(
        df.index, state_time=None, target_time=df.index[5]
    )
    assert sim_mask.all()
    assert advance_mask.sum() == 6  # rows 0..5 inclusive
    assert advance_hours == 0.0


def test_sim_window_with_state_crops_correctly():
    df = _make_arpege(20)
    df.set_index("Date", inplace=True)
    state_time = df.index[3]
    target_time = df.index[7]
    sim_mask, advance_mask, advance_hours = compute_sim_window(
        df.index, state_time=state_time.isoformat(), target_time=target_time
    )
    # sim covers rows 4..19
    assert sim_mask.sum() == 16
    # advance covers rows 4..7 inclusive
    assert advance_mask.sum() == 4
    assert advance_hours == 4.0


def test_sim_window_raises_on_excessive_gap():
    df = _make_arpege(80)
    df.set_index("Date", inplace=True)
    state_time = df.index[0]
    target_time = state_time + pd.Timedelta(hours=ADVANCE_MAX_HOURS + 1)
    with pytest.raises(StateAdvanceError):
        compute_sim_window(df.index, state_time=state_time.isoformat(),
                           target_time=target_time)


def test_sim_window_raises_when_state_predates_data_beyond_tolerance():
    """Backward gap > BACKWARD_TOLERANCE_HOURS still raises so the
    forecast_service auto-reset wrapper picks it up."""
    df = _make_arpege(20)
    df.set_index("Date", inplace=True)
    state_time = df.index[0] - pd.Timedelta(hours=BACKWARD_TOLERANCE_HOURS + 4)
    target_time = df.index[5]
    with pytest.raises(StateAdvanceError, match="tolerance"):
        compute_sim_window(df.index, state_time=state_time.isoformat(),
                           target_time=target_time)


def test_sim_window_clips_when_state_within_backward_tolerance():
    """Backward gap <= BACKWARD_TOLERANCE_HOURS: clip to data_start, no raise.

    Triggered in production when ARPEGE rolls forward between two slow-cadence
    assimilation updates (e.g. alzou's 4h cadence). The state effectively
    represents data_start; the few hours of unsimulated meteo are absorbed by
    the next lastQ assimilation.
    """
    df = _make_arpege(20)
    df.set_index("Date", inplace=True)
    backward_gap = BACKWARD_TOLERANCE_HOURS - 1  # within tolerance
    state_time = df.index[0] - pd.Timedelta(hours=backward_gap)
    target_time = df.index[5]

    sim_mask, advance_mask, advance_hours = compute_sim_window(
        df.index, state_time=state_time.isoformat(), target_time=target_time
    )

    # All df rows should be in sim (state was clipped to before data_start)
    assert sim_mask.all()
    # advance covers rows 0..5 inclusive (everything up to target)
    assert advance_mask.sum() == 6
    # advance_hours reports the *apparent* gap (target - original state),
    # not the clipped one — kept as-is for observability of true drift
    assert advance_hours == pytest.approx(backward_gap + 5)


def test_sim_window_clip_at_exact_tolerance_boundary():
    """Backward gap exactly equal to BACKWARD_TOLERANCE_HOURS: still clipped
    (boundary inclusive). One second more would raise."""
    df = _make_arpege(20)
    df.set_index("Date", inplace=True)
    state_time = df.index[0] - pd.Timedelta(hours=BACKWARD_TOLERANCE_HOURS)
    target_time = df.index[5]
    # Should not raise at exact boundary
    sim_mask, _, _ = compute_sim_window(
        df.index, state_time=state_time.isoformat(), target_time=target_time
    )
    assert sim_mask.all()


# -------------------------- GR4H Rust direct call --------------------------


def test_gr4h_rust_direct_matches_wrapper():
    """The Rust binding called directly must produce the same output as the
    InputDataHandler-based wrapper for identical inputs and initial state."""
    df = _make_arpege(50)
    df_indexed = df.copy()
    df_indexed["Date"] = pd.to_datetime(df_indexed["Date"])
    df_indexed = df_indexed.set_index("Date")

    # Reference: InputDataHandler-based call (the way production used to do it)
    ref_model = ModelGr4h(GR4H_PARAMS)
    ref_outputs = ref_model.run(InputDataHandler(ModelGr4h, df_indexed).data)
    ref_states = ref_model.get_states()

    # Direct: same fresh model, fed via _run_gr4h_direct
    direct_model = ModelGr4h(GR4H_PARAMS)
    direct_outputs = _run_gr4h_direct(direct_model, df_indexed)
    direct_states = direct_model.get_states()

    np.testing.assert_allclose(
        direct_outputs["flow"].values, ref_outputs["flow"].values,
        rtol=1e-9, atol=1e-12,
    )
    for key in ("production_store", "routing_store"):
        np.testing.assert_allclose(direct_states[key], ref_states[key], rtol=1e-9)
    np.testing.assert_allclose(direct_states["uh1"], ref_states["uh1"], rtol=1e-9)
    np.testing.assert_allclose(direct_states["uh2"], ref_states["uh2"], rtol=1e-9)


# -------------------------- GR4H dual-sim coherence --------------------------


def test_gr4h_dual_sim_state_continuity():
    """Two consecutive runs reproduce a single long run (chained equivalence).

    Run A: full ARPEGE [0..80h], state_time=None, lastQ_datetime=t10.
           Saves a state representing t10. Records flow[t11..t80] from the
           long sim of A.
    Run B: same ARPEGE, state_time=t10, lastQ_datetime=t30.
           Loads A's saved state, advances to t30. Long sim runs from
           A's saved t10 state on rows >t10.
           Records flow[t11..t80] from the long sim of B.

    The flows should be IDENTICAL (the long sim of B from the saved state
    must reproduce the long sim of A on the same horizon)."""
    df = _make_arpege(80)

    response_a, full_a, states_a = run_gr4h(
        arpege_df=df, gr4h_params=GR4H_PARAMS,
        catchment_area_km2=CATCHMENT_AREA,
        states=None, lastQ=None,
        lastQ_datetime=df["Date"].iloc[10].isoformat(),
        state_time=None,
    )
    assert states_a["state_time"] == df["Date"].iloc[10].isoformat()

    saved_states = {k: v for k, v in states_a.items() if k != "state_time"}
    saved_state_time = states_a["state_time"]

    response_b, full_b, states_b = run_gr4h(
        arpege_df=df, gr4h_params=GR4H_PARAMS,
        catchment_area_km2=CATCHMENT_AREA,
        states=saved_states, lastQ=None,
        lastQ_datetime=df["Date"].iloc[30].isoformat(),
        state_time=saved_state_time,
    )

    # Both long sims should agree on rows >t10 (where B simulates and A also has)
    common_idx = full_b.index
    np.testing.assert_allclose(
        full_a.loc[common_idx, "flow"].values,
        full_b.loc[common_idx, "flow"].values,
        rtol=1e-9, atol=1e-10,
    )


def test_gr4h_state_time_is_persisted():
    df = _make_arpege(40)
    target_iso = df["Date"].iloc[12].isoformat()
    _, _, new_states = run_gr4h(
        arpege_df=df, gr4h_params=GR4H_PARAMS,
        catchment_area_km2=CATCHMENT_AREA,
        states=None, lastQ=None,
        lastQ_datetime=target_iso, state_time=None,
    )
    assert new_states["state_time"] == target_iso


def test_gr4h_assimilation_only_affects_response_not_full():
    """Assimilation must scale only the response output, not the full output
    used for qsink — otherwise the tributary contribution is biased."""
    df = _make_arpege(40)
    response, full, _ = run_gr4h(
        arpege_df=df, gr4h_params=GR4H_PARAMS,
        catchment_area_km2=CATCHMENT_AREA,
        states=None,
        lastQ=10.0,  # very large vs. modeled, forces a big correction factor
        lastQ_datetime=df["Date"].iloc[5].isoformat(),
        state_time=None,
    )
    # The first response value should equal lastQ (assimilation pinned it)
    assert abs(response["flow_m3_s"].iloc[0] - 10.0) < 1e-6
    # The full output at the same timestamp should NOT have been scaled
    overlap_idx = response.index[0]
    full_at_target = full.loc[overlap_idx, "flow_m3_s"]
    response_at_target = response["flow_m3_s"].iloc[0]
    # They differ unless the model already produced 10 m3/s naturally
    # (which it doesn't with these params and synthetic data)
    assert abs(full_at_target - response_at_target) > 0.1


# -------------------------- KarstMod dual-sim --------------------------


KARSTMOD_PARAMS = {
    "RA": 650.0, "kCS": 0.24, "kMS": 0.028, "kMC": 0.0016,
    "kEM": 0.00036, "kEC": 0.00001, "alphaMS": 3.59, "alphaMC": 2.06,
}


def test_karstmod_qsink_length_mismatch_raises():
    df = _make_arpege(40)
    bad_qsink = np.zeros(20)  # half the length
    with pytest.raises(ValueError, match="qsink length"):
        run_karstmod(
            arpege_df=df, qsink_full_m3_s=bad_qsink,
            params=KARSTMOD_PARAMS, states=None,
            lastQ_datetime=df["Date"].iloc[5].isoformat(),
        )


def test_karstmod_dual_sim_state_continuity():
    """Same chained-equivalence test as for GR4H."""
    df = _make_arpege(80)
    qsink = np.full(80, 0.5, dtype=np.float64)

    response_a, states_a = run_karstmod(
        arpege_df=df, qsink_full_m3_s=qsink,
        params=KARSTMOD_PARAMS, states=None,
        lastQ_datetime=df["Date"].iloc[10].isoformat(),
        state_time=None,
    )
    saved = {k: v for k, v in states_a.items() if k != "state_time"}

    response_b, _ = run_karstmod(
        arpege_df=df, qsink_full_m3_s=qsink,
        params=KARSTMOD_PARAMS, states=saved,
        lastQ_datetime=df["Date"].iloc[30].isoformat(),
        state_time=states_a["state_time"],
    )

    common_idx = response_b.index
    np.testing.assert_allclose(
        response_a.loc[common_idx, "flow_m3_s"].values,
        response_b.loc[common_idx, "flow_m3_s"].values,
        rtol=1e-7, atol=1e-9,
    )


def test_karstmod_state_time_persisted():
    df = _make_arpege(40)
    qsink = np.full(40, 0.3, dtype=np.float64)
    target_iso = df["Date"].iloc[12].isoformat()
    _, new_states = run_karstmod(
        arpege_df=df, qsink_full_m3_s=qsink,
        params=KARSTMOD_PARAMS, states=None,
        lastQ_datetime=target_iso, state_time=None,
    )
    assert new_states["state_time"] == target_iso
    for key in ("wlE_final", "C_final", "M_final"):
        assert key in new_states


@pytest.mark.filterwarnings("error::pandas.errors.SettingWithCopyWarning")
def test_karstmod_assimilation_no_pandas_warning():
    """Regression: assimilate_flow must not trigger SettingWithCopyWarning
    when applied to the filtered output of run_karstmod."""
    df = _make_arpege(40)
    qsink = np.full(40, 0.3, dtype=np.float64)
    response, _ = run_karstmod(
        arpege_df=df, qsink_full_m3_s=qsink,
        params=KARSTMOD_PARAMS, states=None,
        lastQ=2.5, lastQ_datetime=df["Date"].iloc[10].isoformat(),
        state_time=None,
    )
    assert abs(response["flow_m3_s"].iloc[0] - 2.5) < 1e-6
