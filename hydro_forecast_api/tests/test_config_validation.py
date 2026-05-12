"""Tests for API endpoints."""

import os
import sys
import tempfile

import pytest

# Ensure the app module is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def app():
    """Create a test Flask app."""
    from app import create_app

    test_app = create_app()
    test_app.config["TESTING"] = True
    # Use temp directories for tests
    test_app.config["CONFIGS_PATH"] = tempfile.mkdtemp()
    test_app.config["STATES_PATH"] = tempfile.mkdtemp()
    test_app.config["BACKUPS_PATH"] = tempfile.mkdtemp()
    test_app.config["TASK_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_tasks.db")
    # Reinitialize task service with the test DB (singleton was already
    # initialized by create_app with the default/production DB path)
    from app.services.task_service import task_service
    task_service.init_app(test_app)
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_test_point(app, point_id="test"):
    """Helper: create a point config directly via service (not API)."""
    with app.app_context():
        from app.services import config_service
        config_service.save_point_config(point_id, {
            "point_id": point_id,
            "latitude": 44.74,
            "karstmod": {
                "params": {
                    "RA": 650.0, "kCS": 0.24, "kMS": 0.028, "kMC": 0.0016,
                    "kEM": 0.00036, "kEC": 0.00001, "alphaMS": 3.59, "alphaMC": 2.06,
                },
                "arpege_grid": {
                    "indices": [[246, 336], [246, 337]],
                    "weights": [0.5, 0.5],
                },
            },
            "tributaries": [
                {
                    "basin_id": "test_basin",
                    "gr4h_params": {"X1": 290.0, "X2": -1.8, "X3": 59.0, "X4": 5.0},
                    "catchment_area_km2": 55.0,
                    "arpege_grid": {
                        "indices": [[247, 338]],
                        "weights": [1.0],
                    },
                }
            ],
            "qsink_formula": {"multiplier": 1.2},
        })


def test_health(client):
    """Test liveness endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["status"] == "ok"


def test_list_points_empty(client):
    """Test listing points when none configured."""
    response = client.get("/api/v1/points")
    assert response.status_code == 200
    assert response.json["count"] == 0


def test_list_and_get_point(client, app):
    """Test listing and retrieving a point config."""
    _create_test_point(app, "test_point")

    # Get
    response = client.get("/api/v1/points/test_point")
    assert response.status_code == 200
    assert response.json["point_id"] == "test_point"

    # List
    response = client.get("/api/v1/points")
    assert response.json["count"] == 1


def test_get_nonexistent_point(client):
    """Test getting a point that doesn't exist."""
    response = client.get("/api/v1/points/nonexistent")
    assert response.status_code == 404


def test_list_tasks_empty(client):
    """Test listing tasks when none exist."""
    response = client.get("/api/v1/tasks")
    assert response.status_code == 200
    assert response.json["count"] == 0


def test_get_nonexistent_task(client):
    """Test getting a task that doesn't exist."""
    response = client.get("/api/v1/tasks/nonexistent-id")
    assert response.status_code == 404


def test_forecast_nonexistent_point(client):
    """Test launching forecast for nonexistent point."""
    response = client.post("/api/v1/points/nonexistent/forecast", json={
        "lastQ_datetime": "2026-03-12T14:00:00"
    })
    assert response.status_code == 404


def test_forecast_missing_datetime(client, app):
    """Test launching forecast without lastQ_datetime."""
    _create_test_point(app, "test")

    response = client.post("/api/v1/points/test/forecast", json={})
    assert response.status_code == 422


def test_get_states(client, app):
    """Test reading states for a point."""
    _create_test_point(app, "test_states")

    response = client.get("/api/v1/points/test_states/states")
    assert response.status_code == 200
    assert response.json["point_id"] == "test_states"


def test_write_endpoints_removed(client):
    """Verify that write endpoints on points and states return 405."""
    response = client.post("/api/v1/points", json={})
    assert response.status_code == 405

    response = client.put("/api/v1/points/ouysse", json={})
    assert response.status_code == 405

    response = client.delete("/api/v1/points/ouysse")
    assert response.status_code == 405

    response = client.put("/api/v1/points/ouysse/states/karstmod", json={})
    assert response.status_code == 405

    response = client.delete("/api/v1/points/ouysse/states")
    assert response.status_code == 405
