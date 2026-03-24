import os
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from config import Config
from app.extensions import db, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    enable_mcp_api = os.getenv("VF_ENABLE_MCP_API", "1") == "1"

    CORS(
        app,
        resources={
            r"/api/*": {"origins": "*"},
            r"/mcp/*": {"origins": "*"},
        },
    )

    db.init_app(app)
    migrate.init_app(app, db)

    @app.after_request
    def _ensure_utf8_response(resp):
        content_type = resp.headers.get("Content-Type", "")
        if content_type.startswith("text/html") or content_type.startswith("text/plain"):
            if "charset" not in content_type.lower():
                resp.headers["Content-Type"] = f"{content_type}; charset=utf-8"
        return resp

    @app.errorhandler(Exception)
    def _handle_api_exception(exc):
        if not str(request.path or "").startswith("/api/"):
            if isinstance(exc, HTTPException):
                return exc
            logging.exception("unhandled non-api exception: %s", request.path)
            return "Internal Server Error", 500
        if isinstance(exc, HTTPException):
            return jsonify({
                "ok": False,
                "error": exc.description or exc.name or "request failed",
            }), exc.code or 500
        logging.exception("unhandled api exception: %s", request.path)
        return jsonify({
            "ok": False,
            "error": str(exc) or "server error",
        }), 500

    # Register blueprints (minimal mode can skip)
    if os.getenv('VF_MINIMAL_APP') != '1':
        from app.views.auth import auth_bp
        from app.views.api import api_bp
        from app.views.user import user_bp
        from app.views.admin import admin_bp

        app.register_blueprint(auth_bp)
        app.register_blueprint(api_bp)
        app.register_blueprint(user_bp)
        app.register_blueprint(admin_bp)
        if enable_mcp_api:
            from app.views.mcp_api import mcp_api_bp
            from app.views.admin_mcp import mcp_admin_bp

            app.register_blueprint(mcp_api_bp)
            app.register_blueprint(mcp_admin_bp)

    # Ensure model imports
    with app.app_context():
        from app.models import user, user_token, user_quota, template, template_model, task, task_effect_log, api_usage, api_key, api_audit, api_quota, api_quota_usage, api_quota_template, resource_exchange_post, cdk_template, config
        try:
            from app.models.config import Config as RuntimeConfig

            RuntimeConfig.__table__.create(bind=db.engine, checkfirst=True)
        except Exception:
            logging.exception("ensure config table on startup failed")

    return app
