import json
import os
import zipfile
import uuid
import csv
import io
from functools import wraps
from flask import Blueprint, request, jsonify, session, current_app, Response
from datetime import datetime
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.user import User
from app.models.user_quota import UserQuota
from app.models.template_model import TemplateModel
from app.utils.auth_token import extract_bearer_token, validate_token
from app.services.user_quota_service import adjust_quota, quota_to_dict

# 尝试导入 JianYingApi（用于解析草稿）
try:
    from app.utils.JianYingApi.Drafts import Draft as JYDraft
    JY_AVAILABLE = True
except ImportError:
    JY_AVAILABLE = False
    print("警告: JianYingApi 未正确导入，文字解析将只依赖 JSON 读取")

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_token_required():
    token = extract_bearer_token(request)
    user, _token_obj, err = validate_token(token)
    if err:
        return None, jsonify({'ok': False, 'error': '管理员令牌无效或已过期'}), 401
    if user.role != 'admin':
        return None, jsonify({'ok': False, 'error': '需要管理员权限'}), 403
    return user, None, None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'error': '????'}), 401
        if session.get('role') != 'admin':
            return jsonify({'success': False, 'error': '???????'}), 403
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/users-page')
@admin_required
def users_page():
    return jsonify({'ok': True, 'message': 'API service only'})


@admin_bp.route('/users')
@admin_required
def users_page_alias():
    return jsonify({'ok': True, 'message': 'API service only'})

@admin_bp.route('/users-fragment')
@admin_required
def users_fragment():
    return jsonify({'ok': True, 'message': 'API service only'})

@admin_bp.route('/api/users')
@admin_required
def api_users():
    users = User.query.order_by(User.id).all()
    quotas = {q.user_id: q for q in UserQuota.query.all()}
    data = [{
        'id': u.id,
        'username': u.username,
        'email': u.email,
        'role': u.role,
        'created_at': u.created_at.strftime('%Y-%m-%d %H:%M') if u.created_at else '',
        'remaining': quotas.get(u.id).remaining if quotas.get(u.id) else 0,
        'total_generated': quotas.get(u.id).total_generated if quotas.get(u.id) else 0,
        'vip_expire_at': quotas.get(u.id).vip_expire_at.isoformat() if quotas.get(u.id) and quotas.get(u.id).vip_expire_at else None
    } for u in users]
    return jsonify(data)

@admin_bp.route('/api/users/<int:id>', methods=['DELETE'])
@admin_required
def api_delete_user(id):
    if id == session['user_id']:
        return jsonify({'success': False, 'error': '不能删除自己'})
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True})

@admin_bp.route('/api/users/<int:id>/role', methods=['POST'])
@admin_required
def api_change_role(id):
    user = User.query.get_or_404(id)
    new_role = request.json.get('role')
    if new_role not in ['admin', 'user']:
        return jsonify({'success': False, 'error': '无效角色'})
    user.role = new_role
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/user/quota', methods=['POST'])
def admin_update_quota():
    _admin, resp, code = admin_token_required()
    if resp:
        return resp, code
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': '?? user_id'}), 400
    remaining = data.get('remaining')
    delta = data.get('delta')
    vip_expire_at = data.get('vip_expire_at')
    vip_dt = None
    if vip_expire_at:
        try:
            vip_dt = datetime.fromisoformat(vip_expire_at)
        except Exception:
            return jsonify({'ok': False, 'error': 'vip_expire_at 格式错误'}), 400
    elif vip_expire_at == '':
        vip_dt = None

    quota = adjust_quota(user_id, remaining=remaining, delta=delta, vip_expire_at=vip_dt)
    return jsonify({'ok': True, 'user_id': user_id, **quota_to_dict(quota)})


@admin_bp.route('/user/quota/batch', methods=['POST'])
def admin_update_quota_batch():
    _admin, resp, code = admin_token_required()
    if resp:
        return resp, code
    data = request.get_json(silent=True) or {}
    items = data.get('items') or []
    if not isinstance(items, list):
        return jsonify({'ok': False, 'error': 'items 必须是数组'}), 400

    results = []
    for item in items:
        try:
            user_id = item.get('user_id')
            if not user_id:
                results.append({'ok': False, 'error': '缺少 user_id'})
                continue
            remaining = item.get('remaining')
            delta = item.get('delta')
            vip_expire_at = item.get('vip_expire_at')
            vip_dt = None
            if vip_expire_at:
                try:
                    vip_dt = datetime.fromisoformat(vip_expire_at)
                except Exception:
                    results.append({'ok': False, 'user_id': user_id, 'error': 'vip_expire_at 格式错误'})
                    continue
            elif vip_expire_at == '':
                vip_dt = None

            quota = adjust_quota(user_id, remaining=remaining, delta=delta, vip_expire_at=vip_dt)
            results.append({'ok': True, 'user_id': user_id, **quota_to_dict(quota)})
        except Exception as e:
            results.append({'ok': False, 'user_id': item.get('user_id'), 'error': str(e)})
    return jsonify({'ok': True, 'results': results})


@admin_bp.route('/users/export', methods=['GET'])
def admin_export_users():
    _admin, resp, code = admin_token_required()
    if resp:
        return resp, code
    users = User.query.order_by(User.id).all()
    quotas = {q.user_id: q for q in UserQuota.query.all()}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'username', 'email', 'role', 'remaining', 'total_generated', 'vip_expire_at', 'created_at'])
    for u in users:
        q = quotas.get(u.id)
        writer.writerow([
            u.id,
            u.username,
            u.email or '',
            u.role,
            q.remaining if q else 0,
            q.total_generated if q else 0,
            q.vip_expire_at.isoformat() if q and q.vip_expire_at else '',
            u.created_at.strftime('%Y-%m-%d %H:%M') if u.created_at else ''
        ])
    csv_data = output.getvalue()
    output.close()

    resp = Response(csv_data, mimetype='text/csv; charset=utf-8')
    resp.headers['Content-Disposition'] = 'attachment; filename=users_quota.csv'
    return resp


@admin_bp.route('/logs-page')
@admin_required
def logs_page():
    return jsonify({'ok': True, 'message': 'API service only'})

@admin_bp.route('/api/logs')
@admin_required
def api_logs():
    return jsonify([])
