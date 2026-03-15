import os
import logging
import json

from flask import Blueprint, request, jsonify, send_from_directory

from app.services.jianying_service import JianYingService
from app.services.jianying.usage import check_and_increment
from app.services.jianying.batch_service import enqueue_batch_generation
from app.services.jianying.openapi import get_openapi_spec
from app.services.jianying.api_keys import verify_key, create_key, revoke_key, delete_key, get_key_by_raw
from app.services.jianying.quota import check_and_increment_quota
from app.services.jianying.quota_templates import get_template, upsert_template
from app.services.jianying.permissions import get_permission_template
from app.models.api_key import ApiKey
from app.models.api_usage import ApiUsage
from app.models.api_audit import ApiAuditLog
from app.models.task_effect_log import TaskEffectLog
from app.extensions import db


mcp_api_bp = Blueprint("mcp_api", __name__, url_prefix="/api/mcp")
logger = logging.getLogger("mcp_api")


def _require_api_key():
    if os.getenv("MCP_API_ENABLED", "0") != "1":
        return False, ("MCP API disabled", 403)
    required_key = os.getenv("MCP_API_KEY", "")
    provided = request.headers.get("X-API-Key", "")
    if required_key:
        if provided != required_key:
            return False, ("invalid api key", 401)
        return True, None
    # DB keys
    if verify_key(provided):
        return True, None
    return False, ("invalid api key", 401)


def _client_id():
    return request.headers.get("X-Client-Id", "") or request.headers.get("X-API-Key", "") or request.remote_addr or "unknown"


def _require_admin():
    admin_key = os.getenv("MCP_ADMIN_KEY", "")
    if not admin_key:
        return False, ("admin key not configured", 403)
    provided = request.headers.get("X-Admin-Key", "")
    if provided != admin_key:
        return False, ("invalid admin key", 401)
    return True, None


@mcp_api_bp.before_request
def _guard():
    ok, err = _require_api_key()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    # optional user binding enforcement
    if os.getenv("MCP_ENFORCE_USER", "0") == "1":
        api_key = request.headers.get("X-API-Key", "")
        key_obj = get_key_by_raw(api_key)
        if key_obj and key_obj.user_id:
            user_id = request.headers.get("X-User-Id", "")
            if str(key_obj.user_id) != str(user_id):
                return jsonify({"ok": False, "code": "user_mismatch", "message": "api key not allowed for this user"}), 403
    # role-based access
    api_key = request.headers.get("X-API-Key", "")
    action = None
    if request.path.endswith("/execute") and request.method == "POST":
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
    key_obj = get_key_by_raw(api_key) if api_key else None
    if key_obj and action:
        read_only_actions = {"utility.parse_media", "utility.find_effects"}
        if key_obj.role == "readonly" and action not in read_only_actions:
            return jsonify({"ok": False, "code": "forbidden", "message": "readonly key"}), 403
        # allow/deny lists
        if key_obj.allow_actions:
            allow_set = {a.strip() for a in key_obj.allow_actions.split(",") if a.strip()}
            if action not in allow_set:
                return jsonify({"ok": False, "code": "forbidden", "message": "action not allowed"}), 403
        if key_obj.deny_actions:
            deny_set = {a.strip() for a in key_obj.deny_actions.split(",") if a.strip()}
            if action in deny_set:
                return jsonify({"ok": False, "code": "forbidden", "message": "action denied"}), 403
    # quota by key + action
    if api_key and action and key_obj:
        if not check_and_increment_quota(key_obj.id, action):
            return jsonify({"ok": False, "code": "quota_exceeded", "message": "action quota exceeded"}), 429
    cid = _client_id()
    if not check_and_increment(cid):
        return jsonify({"ok": False, "code": "rate_limited", "message": "daily limit exceeded"}), 429


@mcp_api_bp.route("/execute", methods=["POST"])
def execute():
    payload = request.get_json(force=True) or {}
    action = payload.get("action")
    params = payload.get("params") or {}

    svc = JianYingService()
    handler_map = {
        # draft
        "draft.create": svc.create_draft,
        "draft.export": svc.export_draft,
        # track
        "track.create": svc.create_track,
        # video
        "video.add_segment": svc.add_video_segment,
        "video.add_animation": svc.add_video_animation,
        "video.add_transition": svc.add_video_transition,
        "video.add_filter": svc.add_video_filter,
        "video.add_mask": svc.add_video_mask,
        "video.add_keyframe": svc.add_video_keyframe,
        "video.add_background": svc.add_video_background_filling,
        "video.add_effect": svc.add_video_effect,
        # audio
        "audio.add_segment": svc.add_audio_segment,
        "audio.add_effect": svc.add_audio_effect,
        "audio.add_fade": svc.add_audio_fade,
        "audio.add_keyframe": svc.add_audio_keyframe,
        # text
        "text.add_segment": svc.add_text_segment,
        "text.add_animation": svc.add_text_animation,
        "text.add_bubble": svc.add_text_bubble,
        "text.add_effect": svc.add_text_effect,
        # utility
        "utility.parse_media": svc.parse_media_info,
        "utility.find_effects": svc.find_effects_by_type,
    }

    if action not in handler_map:
        return jsonify({"ok": False, "code": "invalid_action", "message": f"unknown action: {action}"}), 400

    try:
        result = handler_map[action](**params)
        resp = result.to_dict()
        _log_audit(action, "success" if result.ok else "failed", result.code, result.message, payload, resp)
        return jsonify(resp)
    except Exception as e:
        logger.exception("mcp_api execute failed")
        resp = {"ok": False, "code": "server_error", "message": str(e)}
        _log_audit(action, "error", "server_error", str(e), payload, resp)
        return jsonify(resp), 500


@mcp_api_bp.route("/batch/enqueue", methods=["POST"])
def enqueue_batch():
    payload = request.get_json(force=True) or {}
    result = enqueue_batch_generation(
        template_id=payload.get("template_id"),
        materials_root=payload.get("materials_root"),
        texts_input=payload.get("texts_input") or [],
        batch_count=payload.get("batch_count", 1),
        replace_materials=payload.get("replace_materials", True),
        replace_texts=payload.get("replace_texts", True),
        replace_type=payload.get("replace_type", "both"),
        replace_mode=payload.get("replace_mode", "order"),
        audio_enabled=payload.get("audio_enabled", False),
        user_id=payload.get("user_id"),
    )
    return jsonify(result.to_dict())


@mcp_api_bp.route("/openapi", methods=["GET"])
def openapi_spec():
    return jsonify(get_openapi_spec())


@mcp_api_bp.route("/docs", methods=["GET"])
def swagger_ui():
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "mcp"))
    return send_from_directory(static_dir, "swagger.html")


def _log_audit(action, status, code, message, request_payload, response_payload):
    try:
        api_key = request.headers.get("X-API-Key", "")
        key_obj = get_key_by_raw(api_key) if api_key else None
        audit = ApiAuditLog(
            client_id=_client_id(),
            action=action or "",
            status=status,
            code=code,
            message=message,
            request_payload=json.dumps(request_payload, ensure_ascii=False),
            response_payload=json.dumps(response_payload, ensure_ascii=False),
            key_role=key_obj.role if key_obj else None,
            key_allow=key_obj.allow_actions if key_obj else None,
            key_deny=key_obj.deny_actions if key_obj else None,
        )
        db.session.add(audit)
        db.session.commit()
    except Exception:
        db.session.rollback()


@mcp_api_bp.route("/admin/keys", methods=["GET", "POST"])
def admin_keys():
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        name = payload.get("name") or "default"
        user_id = payload.get("user_id")
        group = payload.get("group") or "default"
        role = payload.get("role") or "write"
        raw = create_key(name, user_id=user_id, group=group, role=role)
        # allow/deny lists can be set later via update
        return jsonify({"ok": True, "code": "ok", "message": "created", "data": {"api_key": raw}})
    group = request.args.get("group")
    query = ApiKey.query
    if group:
        query = query.filter_by(group=group)
    keys = query.order_by(ApiKey.id.desc()).all()
    data = []
    for k in keys:
        data.append(
            {
                "id": k.id,
                "name": k.name,
                "group": k.group,
                "role": k.role,
                "allow_actions": k.allow_actions,
                "deny_actions": k.deny_actions,
                "active": k.active,
                "user_id": k.user_id,
                "created_at": k.created_at.isoformat() if k.created_at else None,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            }
        )
    return jsonify({"ok": True, "code": "ok", "data": data})


@mcp_api_bp.route("/admin/keys/<int:key_id>/revoke", methods=["POST"])
def admin_keys_revoke(key_id):
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    if revoke_key(key_id):
        return jsonify({"ok": True, "code": "ok", "message": "revoked"})
    return jsonify({"ok": False, "code": "not_found", "message": "key not found"}), 404


@mcp_api_bp.route("/admin/keys/<int:key_id>/delete", methods=["POST"])
def admin_keys_delete(key_id):
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    if delete_key(key_id):
        return jsonify({"ok": True, "code": "ok", "message": "deleted"})
    return jsonify({"ok": False, "code": "not_found", "message": "key not found"}), 404


@mcp_api_bp.route("/admin/keys/<int:key_id>/update", methods=["POST"])
def admin_keys_update(key_id):
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    payload = request.get_json(force=True) or {}
    key = ApiKey.query.get(key_id)
    if not key:
        return jsonify({"ok": False, "code": "not_found", "message": "key not found"}), 404
    if "name" in payload:
        key.name = payload.get("name") or key.name
    if "group" in payload:
        key.group = payload.get("group") or key.group
    if "role" in payload:
        key.role = payload.get("role") or key.role
    if "allow_actions" in payload:
        key.allow_actions = payload.get("allow_actions")
    if "deny_actions" in payload:
        key.deny_actions = payload.get("deny_actions")
    if "user_id" in payload:
        key.user_id = payload.get("user_id")
    if "active" in payload:
        key.active = bool(payload.get("active"))
    db.session.commit()
    return jsonify({"ok": True, "code": "ok", "message": "updated"})


@mcp_api_bp.route("/admin/usage", methods=["GET"])
def admin_usage():
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    client_id = request.args.get("client_id")
    query = ApiUsage.query
    if client_id:
        query = query.filter_by(client_id=client_id)
    rows = query.order_by(ApiUsage.usage_date.desc()).limit(200).all()
    data = [
        {
            "client_id": r.client_id,
            "usage_date": r.usage_date.isoformat(),
            "count": r.count,
        }
        for r in rows
    ]
    return jsonify({"ok": True, "code": "ok", "data": data})


@mcp_api_bp.route("/admin/quotas", methods=["GET", "POST"])
def admin_quotas():
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    from app.models.api_quota import ApiQuota
    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        key_id = payload.get("key_id")
        action = payload.get("action", "*")
        daily_limit = int(payload.get("daily_limit", 1000))
        item = ApiQuota.query.filter_by(key_id=key_id, action=action).first()
        if not item:
            item = ApiQuota(key_id=key_id, action=action, daily_limit=daily_limit)
            db.session.add(item)
        else:
            item.daily_limit = daily_limit
        db.session.commit()
        return jsonify({"ok": True, "code": "ok", "message": "quota upserted"})
    rows = ApiQuota.query.order_by(ApiQuota.id.desc()).all()
    data = [
        {
            "id": r.id,
            "key_id": r.key_id,
            "action": r.action,
            "daily_limit": r.daily_limit,
        }
        for r in rows
    ]
    return jsonify({"ok": True, "code": "ok", "data": data})


@mcp_api_bp.route("/admin/quotas/group", methods=["POST"])
def admin_quotas_group():
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    payload = request.get_json(force=True) or {}
    group = payload.get("group") or "default"
    action = payload.get("action", "*")
    daily_limit = int(payload.get("daily_limit", 1000))

    keys = ApiKey.query.filter_by(group=group).all()
    if not keys:
        return jsonify({"ok": False, "code": "not_found", "message": "group not found"}), 404
    from app.models.api_quota import ApiQuota
    updated = 0
    for k in keys:
        item = ApiQuota.query.filter_by(key_id=k.id, action=action).first()
        if not item:
            item = ApiQuota(key_id=k.id, action=action, daily_limit=daily_limit)
            db.session.add(item)
        else:
            item.daily_limit = daily_limit
        updated += 1
    db.session.commit()
    return jsonify({"ok": True, "code": "ok", "message": f"updated {updated} keys"})


@mcp_api_bp.route("/admin/quotas/template", methods=["POST"])
def admin_quotas_template():
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    payload = request.get_json(force=True) or {}
    group = payload.get("group") or "default"
    template = payload.get("template") or "free"
    rules = get_template(template)
    if not rules:
        return jsonify({"ok": False, "code": "not_found", "message": "template not found"}), 404
    keys = ApiKey.query.filter_by(group=group).all()
    if not keys:
        return jsonify({"ok": False, "code": "not_found", "message": "group not found"}), 404
    from app.models.api_quota import ApiQuota
    updated = 0
    for k in keys:
        for action, daily_limit in rules.items():
            item = ApiQuota.query.filter_by(key_id=k.id, action=action).first()
            if not item:
                item = ApiQuota(key_id=k.id, action=action, daily_limit=daily_limit)
                db.session.add(item)
            else:
                item.daily_limit = daily_limit
            updated += 1
    db.session.commit()
    return jsonify({"ok": True, "code": "ok", "message": f"applied template {template} to {group}"})


@mcp_api_bp.route("/admin/templates", methods=["GET", "POST"])
def admin_templates():
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        name = payload.get("name")
        rules = payload.get("rules") or {}
        if not name or not isinstance(rules, dict):
            return jsonify({"ok": False, "code": "invalid", "message": "name and rules required"}), 400
        upsert_template(name, rules)
        return jsonify({"ok": True, "code": "ok", "message": "template upserted"})
    from app.models.api_quota_template import ApiQuotaTemplate
    rows = ApiQuotaTemplate.query.order_by(ApiQuotaTemplate.id.desc()).all()
    data = []
    for r in rows:
        data.append({"id": r.id, "name": r.name, "rules_json": r.rules_json})
    return jsonify({"ok": True, "code": "ok", "data": data})


@mcp_api_bp.route("/admin/permissions/template", methods=["POST"])
def admin_permissions_template():
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    payload = request.get_json(force=True) or {}
    key_id = payload.get("key_id")
    name = payload.get("template") or "readonly"
    rules = get_permission_template(name)
    if not key_id:
        return jsonify({"ok": False, "code": "invalid", "message": "key_id required"}), 400
    key = ApiKey.query.get(key_id)
    if not key:
        return jsonify({"ok": False, "code": "not_found", "message": "key not found"}), 404
    allow = ",".join(rules.get("allow", []))
    deny = ",".join(rules.get("deny", []))
    key.allow_actions = allow
    key.deny_actions = deny
    db.session.commit()
    return jsonify({"ok": True, "code": "ok", "message": f"permission template {name} applied"})


@mcp_api_bp.route("/admin/templates/<int:tmpl_id>/delete", methods=["POST"])
def admin_templates_delete(tmpl_id):
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    from app.models.api_quota_template import ApiQuotaTemplate
    item = ApiQuotaTemplate.query.get(tmpl_id)
    if not item:
        return jsonify({"ok": False, "code": "not_found", "message": "template not found"}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"ok": True, "code": "ok", "message": "deleted"})


@mcp_api_bp.route("/admin/quotas/<int:quota_id>/delete", methods=["POST"])
def admin_quotas_delete(quota_id):
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    from app.models.api_quota import ApiQuota
    item = ApiQuota.query.get(quota_id)
    if not item:
        return jsonify({"ok": False, "code": "not_found", "message": "quota not found"}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"ok": True, "code": "ok", "message": "deleted"})


@mcp_api_bp.route("/admin/audit", methods=["GET"])
def admin_audit():
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))
    action = request.args.get("action")
    status = request.args.get("status")
    client_id = request.args.get("client_id")
    query = ApiAuditLog.query
    if action:
        query = query.filter_by(action=action)
    if status:
        query = query.filter_by(status=status)
    if client_id:
        query = query.filter_by(client_id=client_id)
    total = query.count()
    rows = query.order_by(ApiAuditLog.id.desc()).offset(offset).limit(limit).all()
    data = []
    for r in rows:
        data.append(
            {
                "id": r.id,
                "client_id": r.client_id,
                "action": r.action,
                "status": r.status,
                "code": r.code,
                "message": r.message,
                "key_role": r.key_role,
                "key_allow": r.key_allow,
                "key_deny": r.key_deny,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return jsonify({"ok": True, "code": "ok", "data": data, "total": total, "limit": limit, "offset": offset})


@mcp_api_bp.route("/admin/audit/export", methods=["GET"])
def admin_audit_export():
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    fmt = request.args.get("format", "json").lower()
    fields = request.args.get("fields", "")
    action = request.args.get("action")
    status = request.args.get("status")
    client_id = request.args.get("client_id")
    query = ApiAuditLog.query
    if action:
        query = query.filter_by(action=action)
    if status:
        query = query.filter_by(status=status)
    if client_id:
        query = query.filter_by(client_id=client_id)
    rows = query.order_by(ApiAuditLog.id.desc()).limit(1000).all()
    field_list = []
    if fields:
        field_list = [f.strip() for f in fields.split(",") if f.strip()]
    if fmt == "csv":
        import csv
        from io import StringIO
        output = StringIO()
        writer = csv.writer(output)
        default_fields = ["id", "client_id", "action", "status", "code", "message", "created_at"]
        export_fields = field_list or default_fields
        writer.writerow(export_fields)
        for r in rows:
            data = {
                "id": r.id,
                "client_id": r.client_id,
                "action": r.action,
                "status": r.status,
                "code": r.code,
                "message": r.message,
                "key_role": r.key_role,
                "key_allow": r.key_allow,
                "key_deny": r.key_deny,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            writer.writerow([data.get(f, "") for f in export_fields])
        return output.getvalue(), 200, {"Content-Type": "text/csv"}
    data = []
    for r in rows:
        item = {
            "id": r.id,
            "client_id": r.client_id,
            "action": r.action,
            "status": r.status,
            "code": r.code,
            "message": r.message,
            "key_role": r.key_role,
            "key_allow": r.key_allow,
            "key_deny": r.key_deny,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        if field_list:
            item = {k: item.get(k) for k in field_list}
        data.append(item)
    return jsonify({"ok": True, "code": "ok", "data": data})


@mcp_api_bp.route("/admin/effect-logs", methods=["GET"])
def admin_effect_logs():
    ok, err = _require_admin()
    if not ok:
        msg, code = err
        return jsonify({"ok": False, "code": "auth_failed", "message": msg}), code
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    task_id = request.args.get("task_id")
    query = TaskEffectLog.query
    if task_id:
        query = query.filter_by(task_id=task_id)
    total = query.count()
    rows = query.order_by(TaskEffectLog.id.desc()).offset(offset).limit(limit).all()
    data = []
    for r in rows:
        data.append({
            "id": r.id,
            "task_id": r.task_id,
            "summary": r.summary,
            "created_at": r.created_at.isoformat() if r.created_at else None
        })
    return jsonify({"ok": True, "code": "ok", "data": data, "total": total, "limit": limit, "offset": offset})
