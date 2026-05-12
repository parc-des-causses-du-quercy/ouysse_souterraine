"""Tests for the auto-reset recovery in forecast_service.run_forecast.

Covers the three regimes:
  - gap <= ADVANCE_MAX_HOURS (24h)        → normal pipeline, state_was_reset=False
  - 24h < gap <= AUTO_RESET_MAX_HOURS (7d) → backup + delete states, retry, state_was_reset=True
  - gap > AUTO_RESET_MAX_HOURS             → ForecastError(code=STATE_TOO_OLD_FOR_AUTO_RESET)

Uses `custom_meteo` to feed deterministic synthetic weather data, avoiding the
real ARPEGE network fetch.
"""

import json
import logging
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# -------------------------- Fixtures --------------------------


@pytest.fixture
def app():
    """Test Flask app with isolated temp directories."""
    from app import create_app

    test_app = create_app()
    test_app.config["TESTING"] = True
    test_app.config["CONFIGS_PATH"] = tempfile.mkdtemp()
    test_app.config["STATES_PATH"] = tempfile.mkdtemp()
    test_app.config["BACKUPS_PATH"] = tempfile.mkdtemp()
    test_app.config["TASK_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_tasks.db")

    from app.services.task_service import task_service
    task_service.init_app(test_app)
    return test_app


@pytest.fixture
def point_id(app):
    """Configure a minimal test point and return its id."""
    pid = "test_reset"
    with app.app_context():
        from app.services import config_service
        config_service.save_point_config(pid, {
            "point_id": pid,
            "latitude": 44.74,
            "karstmod": {
                "params": {
                    "RA": 650.0, "kCS": 0.24, "kMS": 0.028, "kMC": 0.0016,
                    "kEM": 0.00036, "kEC": 0.00001,
                    "alphaMS": 3.59, "alphaMC": 2.06,
                },
                "arpege_grid": {"indices": [[0, 0]], "weights": [1.0]},
            },
            "tributaries": [
                {
                    "basin_id": "trib_a",
                    "gr4h_params": {"X1": 290.0, "X2": -1.8, "X3": 59.0, "X4": 5.0},
                    "catchment_area_km2": 55.0,
                    "arpege_grid": {"indices": [[0, 0]], "weights": [1.0]},
                }
            ],
            "qsink_formula": {"multiplier": 1.2},
        })
    return pid


def _make_meteo_payload(start_iso, n_hours=120):
    """Return a custom_meteo payload covering [start, start+n_hours[ for both
    components used by the test point (trib_a + karst)."""
    timestamps = pd.date_range(start=start_iso, periods=n_hours, freq="h")
    iso_list = [t.isoformat() for t in timestamps]
    series = {
        "timestamps": iso_list,
        "precipitation_mm": [0.1] * n_hours,
        "temperature_c": [12.0] * n_hours,
        "evapotranspiration_mm": [0.05] * n_hours,
    }
    return {"trib_a": series, "karst": series}


def _seed_state(app, point_id, state_time_iso):
    """Write minimal valid state files with a given state_time."""
    states_dir = os.path.join(app.config["STATES_PATH"], point_id)
    os.makedirs(states_dir, exist_ok=True)

    gr4h_state = {
        "production_store": 0.35,
        "routing_store": 0.3,
        "uh1": [0.0] * 240,
        "uh2": [0.0] * 240,
        "state_time": state_time_iso,
    }
    karstmod_state = {
        "wlE_final": -5.0, "C_final": 5.0, "M_final": 10.0,
        "state_time": state_time_iso,
    }
    with open(os.path.join(states_dir, "trib_a_gr4h.json"), "w") as f:
        json.dump(gr4h_state, f)
    with open(os.path.join(states_dir, "karstmod.json"), "w") as f:
        json.dump(karstmod_state, f)


def _build_request(state_time_iso, gap_hours, n_hours=120):
    """Build a forecast request with target = state_time + gap_hours,
    and meteo data covering generously around the target."""
    state_ts = pd.to_datetime(state_time_iso)
    target_ts = state_ts + pd.Timedelta(hours=gap_hours)
    meteo_start = state_ts - pd.Timedelta(hours=2)
    return {
        "lastQ_datetime": target_ts.isoformat(),
        "tributaries": {"trib_a": {"lastQ": None}},
        "karstmod": {"lastQ": None},
        "custom_meteo": _make_meteo_payload(meteo_start.isoformat(), n_hours),
    }


# -------------------------- Tests: regime 1 (no reset) --------------------------


def test_normal_forecast_no_reset(app, point_id):
    """gap <= ADVANCE_MAX_HOURS: state_was_reset stays False, no delete."""
    state_time = "2026-05-01T00:00:00"
    _seed_state(app, point_id, state_time)
    request_data = _build_request(state_time, gap_hours=5)

    with app.app_context():
        from app.services import forecast_service
        result = forecast_service.run_forecast(point_id, request_data)

    assert result["metadata"]["state_was_reset"] is False
    assert result["metadata"]["reset_reason"] is None
    # State files still exist (no delete happened)
    states_dir = os.path.join(app.config["STATES_PATH"], point_id)
    assert os.path.exists(os.path.join(states_dir, "trib_a_gr4h.json"))
    assert os.path.exists(os.path.join(states_dir, "karstmod.json"))


# -------------------------- Tests: regime 2 (auto-reset) --------------------------


def test_auto_reset_when_state_63h_old(app, point_id):
    """gap of 63h triggers auto-reset, retry succeeds, flag is set."""
    state_time = "2026-05-01T00:00:00"
    _seed_state(app, point_id, state_time)
    request_data = _build_request(state_time, gap_hours=63, n_hours=140)

    with app.app_context():
        from app.services import forecast_service
        result = forecast_service.run_forecast(point_id, request_data)

    assert result["metadata"]["state_was_reset"] is True
    assert "63" in result["metadata"]["reset_reason"]
    assert "behind target" in result["metadata"]["reset_reason"]
    assert "records" in result and point_id in result["records"]


def test_auto_reset_creates_backup_before_delete(app, point_id):
    """The backup directory contains the pre-reset states."""
    state_time = "2026-05-01T00:00:00"
    _seed_state(app, point_id, state_time)
    request_data = _build_request(state_time, gap_hours=48, n_hours=140)

    with app.app_context():
        from app.services import forecast_service
        forecast_service.run_forecast(point_id, request_data)

    point_backups = os.path.join(app.config["BACKUPS_PATH"], point_id)
    assert os.path.exists(point_backups), "Backup directory was not created"
    timestamp_dirs = [
        d for d in os.listdir(point_backups)
        if os.path.isdir(os.path.join(point_backups, d))
    ]
    assert len(timestamp_dirs) >= 1, "Expected at least one timestamped backup folder"
    # The backup must contain the original state files (not the post-run ones)
    backed_up_files = os.listdir(os.path.join(point_backups, timestamp_dirs[0]))
    assert "trib_a_gr4h.json" in backed_up_files
    assert "karstmod.json" in backed_up_files


def test_auto_reset_logs_alarm(app, point_id, caplog):
    """An ERROR-level log with alarm=STATE_AUTO_RESET is emitted."""
    state_time = "2026-05-01T00:00:00"
    _seed_state(app, point_id, state_time)
    request_data = _build_request(state_time, gap_hours=48, n_hours=140)

    with caplog.at_level(logging.ERROR, logger="app.services.forecast_service"):
        with app.app_context():
            from app.services import forecast_service
            forecast_service.run_forecast(point_id, request_data)

    matching = [
        r for r in caplog.records
        if getattr(r, "alarm", None) == "STATE_AUTO_RESET"
    ]
    assert len(matching) == 1, "Expected exactly one STATE_AUTO_RESET alarm log"
    assert matching[0].levelname == "ERROR"


def test_auto_reset_increments_metric(app, point_id):
    """state_resets_total counter goes up by 1 after an auto-reset."""
    from app.api.metrics import _counters

    state_time = "2026-05-01T00:00:00"
    _seed_state(app, point_id, state_time)
    request_data = _build_request(state_time, gap_hours=48, n_hours=140)

    key = f"{point_id}|age"
    before = _counters["state_resets_total"].get(key, 0)

    with app.app_context():
        from app.services import forecast_service
        forecast_service.run_forecast(point_id, request_data)

    after = _counters["state_resets_total"].get(key, 0)
    assert after == before + 1


# -------------------------- Tests: regime 3 (refusal) --------------------------


def test_refuses_when_state_older_than_7d(app, point_id):
    """gap > AUTO_RESET_MAX_HOURS raises ForecastError with the structured code,
    and crucially does NOT delete the existing state."""
    state_time = "2026-05-01T00:00:00"
    _seed_state(app, point_id, state_time)
    request_data = _build_request(state_time, gap_hours=200, n_hours=240)

    with app.app_context():
        from app.services import forecast_service
        from app.services.forecast_service import ForecastError

        with pytest.raises(ForecastError) as exc_info:
            forecast_service.run_forecast(point_id, request_data)

    assert exc_info.value.code == "STATE_TOO_OLD_FOR_AUTO_RESET"
    assert "200" in str(exc_info.value)
    # State files must still be there — refusal must not destroy data.
    states_dir = os.path.join(app.config["STATES_PATH"], point_id)
    assert os.path.exists(os.path.join(states_dir, "trib_a_gr4h.json"))
    assert os.path.exists(os.path.join(states_dir, "karstmod.json"))


# -------------------------- Tests: response shape --------------------------


def test_response_metadata_always_carries_reset_keys(app, point_id):
    """state_was_reset / reset_reason are present in every successful response."""
    state_time = "2026-05-01T00:00:00"
    _seed_state(app, point_id, state_time)
    request_data = _build_request(state_time, gap_hours=5)

    with app.app_context():
        from app.services import forecast_service
        result = forecast_service.run_forecast(point_id, request_data)

    md = result["metadata"]
    assert "state_was_reset" in md
    assert "reset_reason" in md
    assert isinstance(md["state_was_reset"], bool)
    # reset_reason is either None (no reset) or a non-empty string
    assert md["reset_reason"] is None or isinstance(md["reset_reason"], str)
