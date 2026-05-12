from flasgger import Swagger
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

cors = CORS()
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
swagger = None


def init_extensions(app):
    """Initialize all Flask extensions."""
    global swagger

    # CORS
    cors.init_app(app)

    # Rate limiting
    limiter.init_app(app)
    app.config["RATELIMIT_DEFAULT"] = app.config.get("RATE_LIMIT_DEFAULT", "60/minute")

    # Swagger at root /
    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": "apispec",
                "route": "/apispec.json",
                "rule_filter": lambda rule: True,
                "model_filter": lambda tag: True,
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/",
    }

    swagger_template = {
        "info": {
            "title": "Hydro Forecast API",
            "description": "API de prevision hydrologique - Modeles GR4H + KarstMod",
            "version": "1.0.0",
        },
        "basePath": "/",
        "schemes": ["http", "https"],
    }

    swagger = Swagger(app, config=swagger_config, template=swagger_template)
