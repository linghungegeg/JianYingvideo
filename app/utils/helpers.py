import random
import os
import json
import uuid
import logging
import tempfile
from pathlib import Path
from datetime import datetime
from flask import current_app
from app.extensions import db
from app.models.config import Config
from app.models.user_material import UserMaterial
from app.utils.crypto import encrypt_text, decrypt_text
from app.utils.runtime_paths import runtime_file_path, runtime_path


_SECURE_VALUE_PREFIX = "enc::"
_SENSITIVE_CONFIG_KEYS = {
    "token",
    "api_key",
    "api_secret",
    "secret",
    "access_token",
}
_RUNTIME_LOCAL_STATE_KEYS = {
    "user_session_token",
    "admin_session_token",
    "license_offline_token",
    "license_offline_meta",
}
_SITE_SETTING_ENV_KEYS = {
    "site_name": "VF_SITE_NAME",
    "site_title": "VF_SITE_TITLE",
    "site_keywords": "VF_SITE_KEYWORDS",
    "site_description": "VF_SITE_DESCRIPTION",
    "workspace_title": "VF_WORKSPACE_TITLE",
    "workspace_subtitle": "VF_WORKSPACE_SUBTITLE",
    "login_title": "VF_LOGIN_TITLE",
    "login_subtitle": "VF_LOGIN_SUBTITLE",
    "locked_title": "VF_LOCKED_TITLE",
    "locked_subtitle": "VF_LOCKED_SUBTITLE",
    "admin_title": "VF_ADMIN_TITLE",
    "official_site_url": "VF_OFFICIAL_SITE_URL",
    "download_url": "VF_DOWNLOAD_URL",
    "official_logo_url": "VF_OFFICIAL_LOGO_URL",
}


def get_config(key, default=''):
    env_key = _SITE_SETTING_ENV_KEYS.get(str(key or "").strip())
    if env_key:
        env_value = (os.getenv(env_key) or "").strip()
        if env_value:
            return env_value
    try:
        config = Config.query.filter_by(key=key).first()
        return config.value if config else default
    except Exception as exc:
        logging.warning("get_config fallback for %s: %s", key, exc)
        return default


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
    return str(runtime_file_path("user_data", "logs", "generate.log"))


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
        },
    }


def get_user_data_dir(user_id: int) -> str:
    base = str(runtime_path("user_data", f"user_{user_id}"))
    os.makedirs(base, exist_ok=True)
    return base


def _is_sensitive_config_key(key: str) -> bool:
    return str(key or "").strip().lower() in _SENSITIVE_CONFIG_KEYS


def _encrypt_sensitive_value(value):
    if value in (None, ""):
        return ""
    if isinstance(value, str) and value.startswith(_SECURE_VALUE_PREFIX):
        return value
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, ensure_ascii=False)
    return f"{_SECURE_VALUE_PREFIX}{encrypt_text(raw)}"


def _decrypt_sensitive_value(value):
    if not isinstance(value, str):
        return value
    if not value.startswith(_SECURE_VALUE_PREFIX):
        return value
    return decrypt_text(value[len(_SECURE_VALUE_PREFIX):])


def _transform_sensitive_config_values(data, encrypt: bool):
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if _is_sensitive_config_key(key):
                result[key] = _encrypt_sensitive_value(value) if encrypt else _decrypt_sensitive_value(value)
            else:
                result[key] = _transform_sensitive_config_values(value, encrypt)
        return result
    if isinstance(data, list):
        return [_transform_sensitive_config_values(item, encrypt) for item in data]
    return data


def _runtime_local_state_path() -> str:
    return str(runtime_file_path("user_data", ".runtime_secure_state.json"))


def _write_json_file_atomic(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f"{target.stem}_", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except Exception:
            pass
        os.replace(temp_path, target)
        try:
            os.chmod(target, 0o600)
        except Exception:
            pass
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def _validate_runtime_local_state_key(key: str) -> str:
    normalized = str(key or "").strip()
    if normalized not in _RUNTIME_LOCAL_STATE_KEYS:
        raise ValueError("unsupported runtime local state key")
    return normalized


def _read_runtime_local_state_file() -> dict:
    path = _runtime_local_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logging.error("read runtime local state failed: %s", exc)
        return {}


def _write_runtime_local_state_file(data: dict) -> dict:
    payload = data if isinstance(data, dict) else {}
    path = _runtime_local_state_path()
    _write_json_file_atomic(path, payload)
    return payload


def load_runtime_local_state() -> dict:
    payload = _read_runtime_local_state_file()
    result = {}
    for key in _RUNTIME_LOCAL_STATE_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.startswith(_SECURE_VALUE_PREFIX):
            result[key] = decrypt_text(value[len(_SECURE_VALUE_PREFIX):])
        elif value is not None:
            result[key] = value
    return result


def get_runtime_local_state_value(key: str):
    normalized = _validate_runtime_local_state_key(key)
    return load_runtime_local_state().get(normalized, "")


def set_runtime_local_state_value(key: str, value) -> dict:
    normalized = _validate_runtime_local_state_key(key)
    payload = _read_runtime_local_state_file()
    payload[normalized] = _encrypt_sensitive_value("" if value is None else str(value))
    return _write_runtime_local_state_file(payload)


def remove_runtime_local_state_value(key: str) -> dict:
    normalized = _validate_runtime_local_state_key(key)
    payload = _read_runtime_local_state_file()
    if normalized in payload:
        payload.pop(normalized, None)
        return _write_runtime_local_state_file(payload)
    return payload


def load_user_config(user_id: int) -> dict:
    path = os.path.join(get_user_data_dir(user_id), "config.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return _transform_sensitive_config_values(data, encrypt=False)
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
    file_payload = _transform_sensitive_config_values(payload, encrypt=True)
    _write_json_file_atomic(path, file_payload)
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
