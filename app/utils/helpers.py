import random
import os
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime
from flask import current_app
from app.extensions import db
from app.models.config import Config
from app.models.user_material import UserMaterial


def get_config(key, default=''):
    config = Config.query.filter_by(key=key).first()
    return config.value if config else default


def set_config(key, value):
    config = Config.query.filter_by(key=key).first()
    if config:
        config.value = value
    else:
        config = Config(key=key, value=value)
        db.session.add(config)
    db.session.commit()


def set_configs(values: dict):
    items = values if isinstance(values, dict) else {}
    if not items:
        return
    existing = {
        config.key: config
        for config in Config.query.filter(Config.key.in_(list(items.keys()))).all()
    }
    for key, value in items.items():
        normalized = '' if value is None else str(value)
        config = existing.get(key)
        if config:
            config.value = normalized
            continue
        db.session.add(Config(key=key, value=normalized))
    db.session.commit()


def get_material_folder():
    return get_config('material_folder')


def get_drafts_folder():
    return get_config('drafts_folder')


def set_drafts_folder(path):
    set_config('drafts_folder', path)


def _candidate_draft_roots() -> list[str]:
    roots = []
    configured = get_drafts_folder()
    if configured:
        roots.append(configured)

    home = Path.home()
    env_candidates = [
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("APPDATA"),
        str(home / "AppData" / "Local"),
        str(home / "AppData" / "Roaming"),
    ]
    suffixes = [
        ("JianyingPro", "User Data", "Projects", "com.lveditor.draft"),
        ("JianyingPro", "User Data", "Projects"),
        ("CapCut", "User Data", "Projects", "com.lveditor.draft"),
        ("CapCut", "User Data", "Projects"),
        ("CapCut International", "User Data", "Projects", "com.lveditor.draft"),
        ("CapCut International", "User Data", "Projects"),
    ]
    for base in env_candidates:
        if not base:
            continue
        for suffix in suffixes:
            roots.append(str(Path(base, *suffix)))

    # common manual folders
    roots.extend(
        [
            str(home / "Videos" / "JianyingPro Drafts"),
            str(home / "Videos" / "CapCut Drafts"),
            "E:/JianyingPro Drafts",
            "E:/CapCut Drafts",
            "E:/jycaogao/JianyingPro Drafts",
            "D:/JianyingPro Drafts",
            "D:/CapCut Drafts",
        ]
    )

    deduped = []
    seen = set()
    for item in roots:
        norm = os.path.normpath(item)
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(norm)
    return deduped


def discover_draft_roots() -> list[dict]:
    items = []
    for root in _candidate_draft_roots():
        exists = os.path.isdir(root)
        label = "自定义目录" if os.path.normpath(root) == os.path.normpath(get_drafts_folder() or "") else (
            "剪映国际版" if "capcut" in root.lower() else "剪映"
        )
        items.append({"path": root, "label": label, "exists": exists})
    return items


def list_local_drafts(limit: int = 30) -> list[dict]:
    drafts = []
    seen = set()
    for root_info in discover_draft_roots():
        root = root_info["path"]
        if not root_info["exists"]:
            continue
        try:
            for name in os.listdir(root):
                full = os.path.join(root, name)
                if not os.path.isdir(full):
                    continue
                if not os.path.exists(os.path.join(full, "draft_content.json")):
                    continue
                norm = os.path.normpath(full)
                if norm in seen:
                    continue
                seen.add(norm)
                stat = os.stat(full)
                drafts.append(
                    {
                        "name": name,
                        "path": full,
                        "root": root,
                        "source": root_info["label"],
                        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
        except Exception:
            continue
    drafts.sort(key=lambda item: item["updated_at"], reverse=True)
    return drafts[:limit]


def pick_random_material():
    folder = get_material_folder()
    if not folder or not os.path.exists(folder):
        return None
    files = [f for f in os.listdir(folder)
             if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    if not files:
        return None
    return os.path.join(folder, random.choice(files))


def _generate_log_path() -> str:
    base = os.path.join(os.getcwd(), "user_data", "logs")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "generate.log")


def log_generate(template_id, template_name, user_id, username, status, draft_name=None, error_msg=None):
    record = {
        "template_id": template_id,
        "template_name": template_name,
        "user_id": user_id,
        "username": username,
        "status": status,
        "draft_name": draft_name,
        "error_msg": error_msg,
        "created_at": datetime.utcnow().isoformat(),
    }
    try:
        path = _generate_log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logging.error("log_generate failed: %s", exc)


def read_generate_logs(limit: int = 200) -> list:
    path = _generate_log_path()
    if not os.path.exists(path):
        return []
    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        records.append(item)
                except Exception:
                    continue
    except Exception as exc:
        logging.error("read_generate_logs failed: %s", exc)
        return []
    if limit and len(records) > limit:
        return records[-limit:]
    return records


def get_site_settings():
    site_name = get_config('site_name', 'VideoFactory') or 'VideoFactory'
    title = get_config('site_title', f'{site_name} 工作台') or f'{site_name} 工作台'
    keywords = get_config('site_keywords', 'video,ai,generate') or 'video,ai,generate'
    description = (
        get_config('site_description', f'{site_name} 让创作更自由')
        or f'{site_name} 让创作更自由'
    )
    workspace_title = get_config('workspace_title', '工作台') or '工作台'
    workspace_subtitle = (
        get_config(
            'workspace_subtitle',
            '左侧切换功能，右侧执行操作。需要草稿时在当前页面完成选择。'
        )
        or '左侧切换功能，右侧执行操作。需要草稿时在当前页面完成选择。'
    )
    login_title = get_config('login_title', f'登录 {site_name}') or f'登录 {site_name}'
    login_subtitle = (
        get_config('login_subtitle', '登录后继续使用当前工作台。')
        or '登录后继续使用当前工作台。'
    )
    locked_title = get_config('locked_title', '登录后进入工作台') or '登录后进入工作台'
    locked_subtitle = (
        get_config('locked_subtitle', '登录后继续当前工作台。')
        or '登录后继续当前工作台。'
    )
    admin_title = get_config('admin_title', f'{site_name} 管理后台') or f'{site_name} 管理后台'
    admin_subtitle = (
        get_config('admin_subtitle', '授权、CDK、设备、用户与日志。')
        or '授权、CDK、设备、用户与日志。'
    )
    official_site_url = get_config('official_site_url', '') or ''
    download_url = get_config('download_url', '') or ''
    official_logo_url = get_config('official_logo_url', '') or ''
    return {
        'site_name': site_name,
        'title': title,
        'site_title': title,
        'keywords': keywords,
        'site_keywords': keywords,
        'description': description,
        'site_description': description,
        'official_site_url': official_site_url,
        'download_url': download_url,
        'official_logo_url': official_logo_url,
        'workspace_title': workspace_title,
        'workspace_subtitle': workspace_subtitle,
        'login_title': login_title,
        'login_subtitle': login_subtitle,
        'locked_title': locked_title,
        'locked_subtitle': locked_subtitle,
        'admin_title': admin_title,
        'admin_subtitle': admin_subtitle,
        'meta': {
            'site_name': site_name,
            'title': title,
            'keywords': keywords,
            'description': description,
        },
        'links': {
            'official_site_url': official_site_url,
            'download_url': download_url,
            'official_logo_url': official_logo_url,
        },
        'workspace': {
            'title': workspace_title,
            'subtitle': workspace_subtitle,
        },
        'login': {
            'title': login_title,
            'subtitle': login_subtitle,
        },
        'locked': {
            'title': locked_title,
            'subtitle': locked_subtitle,
        },
        'admin': {
            'title': admin_title,
            'subtitle': admin_subtitle,
        },
    }


def get_user_data_dir(user_id: int) -> str:
    base = os.path.join(os.getcwd(), "user_data", f"user_{user_id}")
    os.makedirs(base, exist_ok=True)
    return base


def load_user_config(user_id: int) -> dict:
    path = os.path.join(get_user_data_dir(user_id), "config.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logging.error("load_user_config failed: %s", exc)
        return {}


def _merge_dict(base: dict, incoming: dict) -> dict:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_dict(base.get(key, {}), value)
        else:
            base[key] = value
    return base


def save_user_config(user_id: int, data: dict, merge: bool = True) -> dict:
    payload = data if isinstance(data, dict) else {}
    if merge:
        current = load_user_config(user_id)
        payload = _merge_dict(current, payload)
    path = os.path.join(get_user_data_dir(user_id), "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def get_user_material_dir(user_id: int) -> str:
    base = get_material_folder()
    if not base:
        return ""
    root = os.path.join(base, f"user_{user_id}")
    os.makedirs(root, exist_ok=True)
    return root


def generate_uuid() -> str:
    return uuid.uuid4().hex


def add_user_material(user_id: int, file_path: str, file_type: str, tags=None, source: str = "openclaw", metadata_json=None) -> int:
    tags_payload = json.dumps(tags or [], ensure_ascii=False)
    metadata_payload = json.dumps(metadata or {}, ensure_ascii=False)
    item = UserMaterial(
        user_id=user_id,
        file_path=file_path,
        file_type=file_type,
        source=source,
        tags=tags_payload,
        metadata_json=metadata_payload,
    )
    db.session.add(item)
    db.session.commit()
    return item.id
