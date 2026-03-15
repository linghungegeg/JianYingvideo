from flask import Blueprint, jsonify
from app.views.admin import admin_required


mcp_admin_bp = Blueprint("mcp_admin", __name__, url_prefix="/admin/mcp")


@mcp_admin_bp.route("/", methods=["GET"])
@admin_required
def mcp_admin_page():
    return jsonify({'ok': True, 'message': 'API service only'})
