# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

def register_blueprints(app):
    """Register all API blueprints."""
    from .health import health_bp
    from .forecast import forecast_bp
    from .points import points_bp
    from .states import states_bp
    from .sensors import sensors_bp
    from .metrics import metrics_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(forecast_bp, url_prefix="/api/v1")
    app.register_blueprint(points_bp, url_prefix="/api/v1")
    app.register_blueprint(states_bp, url_prefix="/api/v1")
    app.register_blueprint(sensors_bp, url_prefix="/api/v1")
    app.register_blueprint(metrics_bp)
