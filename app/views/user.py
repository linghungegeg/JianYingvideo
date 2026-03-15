import json
import os
from functools import wraps
from flask import Blueprint, request, jsonify, session, current_app
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.user import User
from app.models.template import Template
from app.models.template_model import TemplateModel   # 新增导入
from app.utils.helpers import get_config, set_config, get_material_folder, pick_random_material, log_generate, get_site_settings
from app.utils.jianying_api import create_draft_from_json

user_bp = Blueprint('user', __name__)

def _extract_template_info(template_path):
    materials_text = ''
    texts_json = '[]'
    if not template_path:
        return materials_text, texts_json
    draft_content = os.path.join(template_path, 'draft_content.json')
    if not os.path.exists(draft_content):
        return materials_text, texts_json
    try:
        with open(draft_content, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return materials_text, texts_json

    mats = data.get('materials', {})
    names = []
    for media_type in ('videos', 'images', 'audios'):
        for item in mats.get(media_type, []) or []:
            if not isinstance(item, dict):
                continue
            path = item.get('path') or item.get('file_path') or ''
            if path:
                name = os.path.basename(path)
                if name and name not in names:
                    names.append(name)

    texts = []
    for item in mats.get('texts', []) or []:
        if not isinstance(item, dict):
            continue
        default_text = item.get('recognize_text') or item.get('content') or ''
        texts.append({'index': len(texts), 'default': default_text, 'material_id': item.get('id')})

    materials_text = '
'.join(names)
    texts_json = json.dumps(texts, indent=2, ensure_ascii=False) if texts else '[]'
    return materials_text, texts_json

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'error': '????'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ================== 主页（仪表盘） ==================
@user_bp.route('/')
@login_required
def dashboard():
    return jsonify({'ok': True, 'message': 'API service only'})

@user_bp.route('/api/dashboard-data')
@login_required
def dashboard_data():
    if session['role'] == 'admin':
        total_templates = Template.query.count()
        active_templates = Template.query.filter_by(status=1).count()
        total_duration = db.session.query(db.func.sum(Template.duration)).scalar() or 0
        total_generates = db.session.query(db.func.sum(Template.generate_count)).scalar() or 0
    else:
        user_id = session['user_id']
        base_q = Template.query.filter((Template.user_id == user_id) | (Template.user_id.is_(None)))
        total_templates = base_q.count()
        active_templates = base_q.filter(Template.status == 1).count()
        total_duration = base_q.with_entities(db.func.sum(Template.duration)).scalar() or 0
        total_generates = base_q.with_entities(db.func.sum(Template.generate_count)).scalar() or 0

    hot_templates = Template.query.order_by(Template.generate_count.desc()).limit(5).all()
    data = {
        'total_templates': total_templates,
        'active_templates': active_templates,
        'total_duration': total_duration,
        'total_generates': total_generates,
        'hot_templates': [
            {'id': t.id, 'name': t.name, 'category': t.category, 'generate_count': t.generate_count}
            for t in hot_templates
        ]
    }
    return jsonify(data)

# ================== 模板列表页面 ==================
@user_bp.route('/templates-page')
@login_required
def templates_page():
    return jsonify({'ok': True, 'message': 'API service only'})

# ================== 上传页面 ==================
@user_bp.route('/upload-page')
@login_required
def upload_page():
    return jsonify({'ok': True, 'message': 'API service only'})

# ================== 生成记录页面 ==================
@user_bp.route('/logs-page')
@login_required
def logs_page():
    return jsonify({'ok': True, 'message': 'API service only'})

# ================== 素材路径设置页面 ==================
@user_bp.route('/settings-page')
@login_required
def settings_page():
    folder = get_material_folder()
    return jsonify({'ok': True, 'folder': folder})

# ================== 站点设置页面 ==================
@user_bp.route('/site-settings-page')
@login_required
def site_settings_page():
    settings = get_site_settings()
    return jsonify({'ok': True, 'settings': settings})

# ================== API: 模板列表 (JSON) ==================
@user_bp.route('/api/templates')
@login_required
def api_templates():
    if session['role'] == 'admin':
        templates = Template.query.order_by(Template.id.desc()).all()
    else:
        user_id = session['user_id']
        templates = Template.query.filter((Template.user_id == user_id) | (Template.user_id.is_(None))).order_by(Template.id.desc()).all()
    data = []
    for t in templates:
        data.append({
            'id': t.id,
            'name': t.name,
            'category': t.category,
            'tags': t.tags.split(',') if t.tags else [],
            'duration': t.duration,
            'status': t.status,
            'generate_count': t.generate_count,
            'created_at': t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else ''
        })
    return jsonify(data)

# ================== API: 模板详情 ==================
@user_bp.route('/api/template/<int:id>')
@login_required
def api_template_detail(id):
    template = Template.query.get_or_404(id)
    if session['role'] != 'admin' and template.user_id and template.user_id != session['user_id']:
        return jsonify({'error': '无权访问'}), 403
    json_content = {}
    if os.path.exists(template.json_path):
        with open(template.json_path, 'r', encoding='utf-8') as f:
            json_content = json.load(f)
    return jsonify({
        'id': template.id,
        'name': template.name,
        'category': template.category,
        'tags': template.tags,
        'json_content': json_content,
        'preview_image': template.preview_image,
        'duration': template.duration,
        'music_suggestions': template.music_suggestions,
        'default_text': template.default_text,
        'status': template.status,
        'generate_count': template.generate_count
    })

# ================== API: 生成草稿（旧版） ==================
@user_bp.route('/api/generate/<int:id>', methods=['POST'])
@login_required
def api_generate(id):
    template = Template.query.get_or_404(id)
    if session['role'] != 'admin' and template.user_id and template.user_id != session['user_id']:
        return jsonify({'success': False, 'error': '无权操作'}), 403
    if template.status != 1:
        return jsonify({'success': False, 'error': '模板未启用'})
    try:
        draft_name = create_draft_from_json(template.json_path)
        log_generate(template.id, template.name, session['user_id'], session['username'], 'success', draft_name)
        return jsonify({'success': True, 'draft': draft_name})
    except Exception as e:
        log_generate(template.id, template.name, session['user_id'], session['username'], 'failed', error_msg=str(e))
        return jsonify({'success': False, 'error': str(e)})

# ================== API: 切换状态 ==================
@user_bp.route('/api/toggle/<int:id>', methods=['POST'])
@login_required
def api_toggle(id):
    template = Template.query.get_or_404(id)
    if session['role'] != 'admin' and template.user_id and template.user_id != session['user_id']:
        return jsonify({'success': False, 'error': '无权操作'}), 403
    template.status = 0 if template.status == 1 else 1
    db.session.commit()
    return jsonify({'success': True, 'status': template.status})

# ================== API: 删除模板 ==================
@user_bp.route('/api/delete/<int:id>', methods=['DELETE'])
@login_required
def api_delete(id):
    template = Template.query.get_or_404(id)
    if session['role'] != 'admin' and template.user_id and template.user_id != session['user_id']:
        return jsonify({'success': False, 'error': '无权操作'}), 403
    if os.path.exists(template.json_path):
        os.remove(template.json_path)
    if template.preview_image and os.path.exists(template.preview_image):
        os.remove(template.preview_image)
    db.session.delete(template)
    db.session.commit()
    return jsonify({'success': True})

# ================== API: 上传模板（旧版） ==================
@user_bp.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    name = request.form.get('name', '').strip()
    category = request.form.get('category', '').strip()
    tags = request.form.get('tags', '').strip()
    json_file = request.files.get('json_file')
    preview_file = request.files.get('preview')
    if not name or not json_file:
        return jsonify({'success': False, 'error': '名称和JSON文件不能为空'})
    json_filename = secure_filename(json_file.filename)
    json_path = os.path.join(current_app.config['UPLOAD_FOLDER'], json_filename)
    json_file.save(json_path)
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        duration = data.get('duration', 0)
        music_suggestions = json.dumps(data.get('music_suggestions', []), ensure_ascii=False)
        default_text = data.get('default_text', '')
    except Exception as e:
        os.remove(json_path)
        return jsonify({'success': False, 'error': f'JSON解析失败: {str(e)}'})
    preview_path = None
    if preview_file and preview_file.filename:
        preview_filename = secure_filename(preview_file.filename)
        preview_path = os.path.join(current_app.config['UPLOAD_FOLDER'], preview_filename)
        preview_file.save(preview_path)
    template = Template(
        name=name, category=category, tags=tags,
        json_path=json_path, preview_image=preview_path,
        duration=duration, music_suggestions=music_suggestions,
        default_text=default_text, user_id=session['user_id']
    )
    db.session.add(template)
    db.session.commit()
    return jsonify({'success': True, 'id': template.id})

# ================== API: 生成记录 (JSON) ==================
@user_bp.route('/api/logs')
@login_required
def api_logs():
    """获取生成记录（JSON） - 暂未实现"""
    return jsonify([])

# ================== 片段路由（供index.html调用） ==================
@user_bp.route('/api/dashboard-fragment')
@login_required
def dashboard_fragment():
    return jsonify({'ok': True, 'message': 'API service only'})

@user_bp.route('/templates-fragment')
@login_required
def templates_fragment():
    return jsonify({'ok': True, 'message': 'API service only'})

@user_bp.route('/upload-fragment')
@login_required
def upload_fragment():
    return jsonify({'ok': True, 'message': 'API service only'})

@user_bp.route('/material-fragment')
@login_required
def material_fragment():
    folder = get_material_folder()
    return jsonify({'ok': True, 'folder': folder})

@user_bp.route('/logs-fragment')
@login_required
def logs_fragment():
    return jsonify({'ok': True, 'message': 'API service only'})

@user_bp.route('/site-fragment')
@login_required
def site_fragment():
    settings = get_site_settings()
    return jsonify({'ok': True, 'settings': settings})

@user_bp.route('/drafts-folder-fragment')
@login_required
def drafts_folder_fragment():
    from app.utils.helpers import get_drafts_folder
    folder = get_drafts_folder()
    return jsonify({'ok': True, 'folder': folder})

@user_bp.route('/billing-fragment')
@login_required
def billing_fragment():
    return jsonify({'ok': True, 'message': 'API service only'})

# ================== 新增：模板配置页面（针对剪映草稿模板） ==================
@user_bp.route('/configure-template/<int:template_id>')
@login_required
def configure_template_page(template_id):
    template = TemplateModel.query.get_or_404(template_id)
    if session['role'] != 'admin' and hasattr(template, 'user_id') and template.user_id != session['user_id']:
        return jsonify({'success': False, 'error': '???????'}), 403
    materials_text, texts_json = _extract_template_info(template.template_path)
    return jsonify({
        'template_id': template.id,
        'template_name': template.name,
        'materials_text': materials_text,
        'texts_json': texts_json
    })

