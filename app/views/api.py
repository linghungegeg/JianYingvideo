import os
import json
import threading
import tkinter as tk
from tkinter import filedialog
from flask import Blueprint, request, jsonify, current_app, session
from sqlalchemy import or_
from werkzeug.security import generate_password_hash, check_password_hash
from app.utils.helpers import get_config, set_config, get_site_settings
from app.models.template_model import TemplateModel
from app.models.task import Task
from app.tasks import generate_video_task, handle_generate_success
from app.extensions import db
from app.models.user import User
from app.utils.auth_token import extract_bearer_token, issue_token, validate_token
from app.services.user_quota_service import get_or_create_quota, quota_to_dict, deduct_quota
from app.utils.jianying_mcp.utils.effect_manager import JianYingResourceManager
from app.services.duo_video_service import DuoVideoService

api_bp = Blueprint('api', __name__, url_prefix='/api')

def _extract_template_info(template_path):
    materials = []
    texts = []
    if not template_path:
        return materials, texts
    draft_content = os.path.join(template_path, 'draft_content.json')
    if not os.path.exists(draft_content):
        return materials, texts
    try:
        with open(draft_content, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return materials, texts

    mats = data.get('materials', {})
    for media_type in ('videos', 'images', 'audios'):
        for item in mats.get(media_type, []) or []:
            if not isinstance(item, dict):
                continue
            path = item.get('path') or item.get('file_path') or ''
            if path:
                name = os.path.basename(path)
                if name and name not in materials:
                    materials.append(name)

    for item in mats.get('texts', []) or []:
        if not isinstance(item, dict):
            continue
        default_text = item.get('recognize_text') or item.get('content') or ''
        texts.append({
            'index': len(texts),
            'default': default_text,
            'material_id': item.get('id')
        })

    return materials, texts


def _auth_error(message, code=401):
    return jsonify({'ok': False, 'error': message}), code


def get_auth_user(require_admin=False):
    token = extract_bearer_token(request)
    user, _token_obj, err = validate_token(token)
    if err == 'missing':
        return None, _auth_error('缺少登录令牌', 401)
    if err == 'invalid':
        return None, _auth_error('登录令牌无效', 401)
    if err == 'expired':
        return None, _auth_error('登录已过期，请重新登录', 401)
    if err == 'user_missing':
        return None, _auth_error('用户不存在', 401)
    if require_admin and user.role != 'admin':
        return None, _auth_error('需要管理员权限', 403)
    return user, None

def browse_folder_thread():
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory()
    root.destroy()
    return folder

@api_bp.route('/browse-folder', methods=['POST'])
def browse_folder():
    result = {}
    def target():
        nonlocal result
        result['folder'] = browse_folder_thread()
    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    return jsonify({'folder': result.get('folder', '')})

@api_bp.route('/site-settings', methods=['GET', 'POST'])
def site_settings():
    if request.method == 'POST':
        title = request.form.get('title', '')
        keywords = request.form.get('keywords', '')
        description = request.form.get('description', '')
        set_config('site_title', title)
        set_config('site_keywords', keywords)
        set_config('site_description', description)
        return jsonify({'success': True})
    else:
        return jsonify(get_site_settings())

@api_bp.route('/settings', methods=['POST'])
def save_settings():
    folder = request.form.get('material_folder', '')
    set_config('material_folder', folder)
    return jsonify({'success': True})

@api_bp.route('/material-folder', methods=['GET', 'POST'])
def material_folder():
    if request.method == 'POST':
        folder = request.form.get('folder', '')
        set_config('material_folder', folder)
        return jsonify({'success': True})
    else:
        return jsonify({'folder': get_config('material_folder')})

@api_bp.route('/drafts-folder', methods=['GET', 'POST'])
def drafts_folder():
    if request.method == 'POST':
        folder = request.form.get('folder', '')
        set_config('drafts_folder', folder)
        return jsonify({'success': True})
    else:
        return jsonify({'folder': get_config('drafts_folder')})

@api_bp.route('/effects/types', methods=['GET'])
def effects_types():
    manager = JianYingResourceManager()
    types = list(manager.EFFECT_TYPE_MAPPING.keys())
    return jsonify({'types': types})

@api_bp.route('/effects/list', methods=['POST'])
def effects_list():
    data = request.get_json() or {}
    effect_type = data.get('effect_type')
    keyword = data.get('keyword')
    limit = data.get('limit')
    is_vip = data.get('is_vip')

    if not effect_type:
        return jsonify({'error': '缺少 effect_type'}), 400

    manager = JianYingResourceManager()
    try:
        effects = manager.find_by_type(effect_type=effect_type, is_vip=is_vip, limit=limit, keyword=keyword)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({'effect_type': effect_type, 'total': len(effects), 'effects': effects})

@api_bp.route('/duo/resources/categories', methods=['GET'])
def duo_categories():
    svc = DuoVideoService()
    return jsonify({'categories': svc.list_categories()})

@api_bp.route('/duo/cache/status', methods=['GET'])
def duo_cache_status():
    svc = DuoVideoService()
    cache_file = os.path.join(svc.cache_dir, 'duo_index.json')
    return jsonify({
        'cache_file': cache_file,
        'exists': os.path.exists(cache_file),
        'version': svc.get_version(),
        'resource_path': svc.resource_path,
        'resource_count': svc.resource_count(),
        'search_mode': 'sqlite' if os.getenv('DUO_USE_SQLITE', '0') == '1' else 'memory'
    })

@api_bp.route('/duo/cache/refresh', methods=['POST'])
def duo_cache_refresh():
    svc = DuoVideoService()
    data = request.get_json(silent=True) or {}
    path = data.get('resource_path') or svc.resource_path
    if path:
        svc.load_resources(path)
        svc._load_index_from_cache()
        return jsonify({'ok': True, 'resource_path': path})
    return jsonify({'ok': False, 'error': 'resource path not set'}), 400


@api_bp.route('/duo/resources/upload', methods=['POST'])
def duo_resources_upload():
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'file required'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'ok': False, 'error': 'filename required'}), 400
    save_dir = os.path.join(os.getcwd(), 'app', 'utils', 'duo_resources')
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, 'resources.json')
    f.save(save_path)
    # refresh index
    svc = DuoVideoService(resource_path=save_path)
    svc.load_resources(save_path)
    svc._load_index_from_cache()
    return jsonify({'ok': True, 'path': save_path, 'count': svc.resource_count()})


@api_bp.route('/duo/ffmpeg/status', methods=['GET'])
def duo_ffmpeg_status():
    ffmpeg = os.getenv('FFMPEG_PATH')
    if ffmpeg and os.path.exists(ffmpeg):
        return jsonify({'ok': True, 'path': ffmpeg, 'source': 'FFMPEG_PATH'})
    import shutil
    exe = shutil.which('ffmpeg')
    if exe:
        return jsonify({'ok': True, 'path': exe, 'source': 'PATH'})
    return jsonify({'ok': False, 'error': 'ffmpeg not found'})

@api_bp.route('/duo/resources/search', methods=['POST'])
def duo_search():
    data = request.get_json() or {}
    category = data.get('category')
    keyword = data.get('keyword')
    limit = data.get('limit', 50)
    offset = data.get('offset', 0)
    svc = DuoVideoService()
    total = svc.count(category=category, keyword=keyword)
    results = svc.search(category=category, keyword=keyword, limit=limit, offset=offset)
    return jsonify({'total': total, 'items': [r.__dict__ for r in results]})

@api_bp.route('/duo/resources/get/<rid>', methods=['GET'])
def duo_get(rid):
    svc = DuoVideoService()
    res = svc.get_by_id(rid)
    if not res:
        return jsonify({'error': 'resource not found'}), 404
    return jsonify(res.__dict__)


# ========== 认证与用户配额 ==========
@api_bp.route('/auth/register', methods=['POST'])
def api_register():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    email = (data.get('email') or '').strip() or None
    auto_login = data.get('auto_login', True)

    if not username or not password:
        return jsonify({'ok': False, 'error': '用户名和密码不能为空'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'ok': False, 'error': '用户名已存在'}), 400
    if email and User.query.filter_by(email=email).first():
        return jsonify({'ok': False, 'error': '邮箱已存在'}), 400

    user = User(username=username, email=email, role='user')
    user.password_hash = generate_password_hash(password)
    db.session.add(user)
    db.session.commit()

    quota = get_or_create_quota(user.id)
    token_obj = issue_token(user.id) if auto_login else None
    return jsonify({
        'ok': True,
        'message': '注册成功',
        'token': token_obj.token if token_obj else None,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
            **quota_to_dict(quota)
        }
    })


@api_bp.route('/auth/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    account = (data.get('username') or data.get('email') or data.get('account') or '').strip()
    password = data.get('password') or ''
    if not account or not password:
        return jsonify({'ok': False, 'error': '请输入账号和密码'}), 400

    user = User.query.filter(or_(User.username == account, User.email == account)).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'ok': False, 'error': '账号或密码错误'}), 401

    token_obj = issue_token(user.id)
    quota = get_or_create_quota(user.id)
    return jsonify({
        'ok': True,
        'token': token_obj.token,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
            **quota_to_dict(quota)
        }
    })


@api_bp.route('/user/info', methods=['GET'])
def api_user_info():
    user, err = get_auth_user()
    if err:
        return err
    quota = get_or_create_quota(user.id)
    return jsonify({
        'ok': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
            **quota_to_dict(quota)
        }
    })


@api_bp.route('/user/deduct', methods=['POST'])
def api_user_deduct():
    user, err = get_auth_user()
    if err:
        return err
    ok, msg, quota = deduct_quota(user.id, amount=1)
    if not ok:
        return jsonify({'ok': False, 'error': msg, **quota_to_dict(quota)}), 400
    return jsonify({'ok': True, **quota_to_dict(quota)})

# ========== 原有的单个生成任务接口（保留） ==========
@api_bp.route('/generate', methods=['POST'])
def submit_task():
    from redis import Redis
    from rq import Queue

    data = request.get_json()
    template_id = data.get('template_id')
    texts_input = data.get('texts_input', [])
    materials_root = data.get('materials_root')
    effects_config = data.get('effects_config', {})
    duo_config = data.get('duo_config', {})

    if not template_id:
        return jsonify({'success': False, 'error': '缺少模板ID'}), 400
    if not materials_root:
        return jsonify({'success': False, 'error': '缺少素材路径'}), 400

    template = TemplateModel.query.get(template_id)
    if not template:
        return jsonify({'success': False, 'error': '模板不存在'}), 404

    redis_conn = Redis.from_url(current_app.config['REDIS_URL'])
    task_queue = Queue(connection=redis_conn)

    job = task_queue.enqueue(
        generate_video_task,
        template_id,
        materials_root,
        texts_input,
        1,
        True,
        True,
        'both',
        'order',
        False,
        effects_config,
        duo_config
    )

    task = Task(
        id=job.id,
        user_id=session.get('user_id', 1),
        template_id=template_id,
        status='pending'
    )
    db.session.add(task)
    db.session.commit()

    return jsonify({'success': True, 'task_id': job.id})

@api_bp.route('/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    user, err = get_auth_user()
    if err:
        return err
    task = Task.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    if task.user_id and task.user_id != user.id:
        return jsonify({'success': False, 'error': '无权访问该任务'}), 403
    return jsonify({
        'task_id': task.id,
        'status': task.status,
        'progress': json.loads(task.progress) if task.progress else {},
        'result_url': task.result_url,
        'error_msg': task.error_msg,
        'created_at': task.created_at.isoformat() if task.created_at else None
    })

@api_bp.route('/generate-page', methods=['GET'])
def generate_page():
    return jsonify({'ok': True, 'message': 'API service only'})

# ========== 模板配置接口 ==========
@api_bp.route('/template/<int:template_id>/configure', methods=['POST'], endpoint='template_configure')
def configure_template_api(template_id):
    return jsonify({'ok': False, 'message': '????????????????????'}), 410


@api_bp.route('/template/<int:template_id>/configure', methods=['GET'], endpoint='get_template_config')
def get_template_config_api(template_id):
    template = TemplateModel.query.get_or_404(template_id)
    materials, texts = _extract_template_info(template.template_path)
    return jsonify({'materials': materials, 'texts': texts})


@api_bp.route('/template/<int:template_id>/tracks', methods=['GET'])
def get_template_tracks_api(template_id):
    template = TemplateModel.query.get_or_404(template_id)
    if not template.template_path:
        return jsonify({'tracks': []})
    draft_content = os.path.join(template.template_path, 'draft_content.json')
    if not os.path.exists(draft_content):
        return jsonify({'tracks': []})
    try:
        with open(draft_content, 'r', encoding='utf-8') as f:
            data = json.load(f)
        tracks = []
        seg_map = {}
        for idx, tr in enumerate(data.get('tracks', [])):
            ttype = tr.get('type')
            if ttype not in ('video', 'audio', 'text'):
                continue
            name = tr.get('name') or tr.get('track_name') or f"{ttype}_{idx}"
            seg_count = len(tr.get('segments', []) or [])
            tracks.append({'name': name, 'type': ttype})
            seg_map[name] = seg_count
        return jsonify({'tracks': tracks, 'segment_counts': seg_map})
    except Exception:
        return jsonify({'tracks': []})

# ========== 批量生成任务接口（接收所有前端选项） ==========
@api_bp.route('/generate-batch', methods=['POST'], endpoint='generate_batch')
def generate_batch_api():
    from redis import Redis
    from rq import Queue

    user, err = get_auth_user()
    if err:
        return err

    quota = get_or_create_quota(user.id)
    if quota.remaining <= 0:
        return jsonify({'error': '次数不足，请充值'}), 403

    data = request.get_json()
    template_id = data.get('template_id')
    materials_root = data.get('materials_root')
    texts_input = data.get('texts_input', [])        # 新格式：每段文字的内容数组及规则
    batch_count = data.get('batch_count', 1)
    replace_materials = data.get('replace_materials', True)
    replace_texts = data.get('replace_texts', True)
    replace_type = data.get('replace_type', 'both')   # image, video, both
    replace_mode = data.get('replace_mode', 'order')  # order, random
    audio_enabled = data.get('audio_enabled', False)
    effects_config = data.get('effects_config', {})
    duo_config = data.get('duo_config', {})

    template = TemplateModel.query.get_or_404(template_id)
    if replace_materials:
        materials, _ = _extract_template_info(template.template_path)
        if not materials:
            return jsonify({'error': '模板未配置可替换素材，无法替换素材'}), 400

    redis_conn = Redis.from_url(current_app.config['REDIS_URL'])
    task_queue = Queue(connection=redis_conn)

    job = task_queue.enqueue(
        generate_video_task,
        template_id,
        materials_root,
        texts_input,
        batch_count,
        replace_materials,
        replace_texts,
        replace_type,
        replace_mode,
        audio_enabled,
        effects_config,
        duo_config,
        user.id,
        on_success=handle_generate_success
    )

    task = Task(
        id=job.id,
        user_id=user.id,
        template_id=template_id,
        status='pending'
    )
    db.session.add(task)
    db.session.commit()

    return jsonify({'job_id': job.id})
