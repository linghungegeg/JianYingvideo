from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, session

from app.extensions import db
from app.models.template import Template
from app.utils.helpers import (
    get_drafts_folder,
    get_material_folder,
    get_site_settings,
    read_generate_logs,
)


user_bp = Blueprint("user", __name__)


def login_required(func):
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"success": False, "error": "未登录"}), 401
        return func(*args, **kwargs)

    return decorated_function


@user_bp.route("/")
def dashboard():
    return render_template("user/index.html", site_settings=get_site_settings())


@user_bp.route("/user")
def user_home():
    return render_template("user/index.html", site_settings=get_site_settings())


@user_bp.route("/user/home")
def user_home_page():
    return redirect("/user")


@user_bp.route("/user/logs")
def user_logs_page():
    return redirect("/user")


@user_bp.route("/user/settings")
def user_settings_page():
    return redirect("/user")


@user_bp.route("/user/generate")
def user_generate_page():
    return redirect("/user")


@user_bp.route("/api/dashboard-data")
@login_required
def dashboard_data():
    if session.get("role") == "admin":
        total_templates = Template.query.count()
        active_templates = Template.query.filter_by(status=1).count()
        total_duration = db.session.query(db.func.sum(Template.duration)).scalar() or 0
        total_generates = db.session.query(db.func.sum(Template.generate_count)).scalar() or 0
    else:
        user_id = session["user_id"]
        base_query = Template.query.filter(
            (Template.user_id == user_id) | (Template.user_id.is_(None))
        )
        total_templates = base_query.count()
        active_templates = base_query.filter(Template.status == 1).count()
        total_duration = base_query.with_entities(db.func.sum(Template.duration)).scalar() or 0
        total_generates = (
            base_query.with_entities(db.func.sum(Template.generate_count)).scalar() or 0
        )

    hot_templates = Template.query.order_by(Template.generate_count.desc()).limit(5).all()
    return jsonify(
        {
            "total_templates": total_templates,
            "active_templates": active_templates,
            "total_duration": total_duration,
            "total_generates": total_generates,
            "hot_templates": [
                {
                    "id": template.id,
                    "name": template.name,
                    "category": template.category,
                    "generate_count": template.generate_count,
                }
                for template in hot_templates
            ],
        }
    )


@user_bp.route("/api/logs")
@login_required
def api_logs():
    logs = read_generate_logs(limit=500)
    role = session.get("role")
    user_id = session.get("user_id")

    if role != "admin":
        logs = [record for record in logs if record.get("user_id") == user_id]

    return jsonify(list(reversed(logs)))


@user_bp.route("/api/dashboard-fragment")
@login_required
def dashboard_fragment():
    return jsonify({"ok": True, "message": "Legacy compatibility endpoint. Use /api/dashboard-data."})


@user_bp.route("/material-fragment")
@login_required
def material_fragment():
    return jsonify({"ok": True, "folder": get_material_folder()})


@user_bp.route("/site-fragment")
@login_required
def site_fragment():
    return jsonify({"ok": True, "settings": get_site_settings()})


@user_bp.route("/drafts-folder-fragment")
@login_required
def drafts_folder_fragment():
    return jsonify({"ok": True, "folder": get_drafts_folder()})


@user_bp.route("/billing-fragment")
@login_required
def billing_fragment():
    return jsonify({"ok": True, "message": "Legacy compatibility endpoint."})
