import os
from flask import Flask
from flask_cors import CORS
from config import Config
from app.extensions import db, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    CORS(
        app,
        resources={
            r"/api/*": {"origins": ["http://localhost:5173", "http://127.0.0.1:5173"]},
            r"/mcp/*": {"origins": ["http://localhost:5173", "http://127.0.0.1:5173"]},
        },
    )

    db.init_app(app)
    migrate.init_app(app, db)

    # 注册蓝图（迁移/脚本模式可跳过）
    if os.getenv('VF_MINIMAL_APP') != '1':
        from app.views.auth import auth_bp
        from app.views.user import user_bp
        from app.views.admin import admin_bp
        from app.views.admin_mcp import mcp_admin_bp
        from app.views.api import api_bp
        from app.views.mcp_api import mcp_api_bp

        app.register_blueprint(auth_bp)
        app.register_blueprint(user_bp)
        app.register_blueprint(admin_bp)
        app.register_blueprint(mcp_admin_bp)
        app.register_blueprint(api_bp)
        app.register_blueprint(mcp_api_bp)

    # 确保模型加载
    with app.app_context():
        from app.models import user, user_token, user_quota, template, template_model, task, task_effect_log, api_usage, api_key, api_audit, api_quota, api_quota_usage, api_quota_template

    return app
