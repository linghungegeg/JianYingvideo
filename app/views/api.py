import os
import json
import uuid
import threading
import base64
import hashlib
import shutil
import re
import time
import math
import platform
import socket
import sys
import subprocess
from collections import defaultdict
from typing import List, Optional, Union
from types import SimpleNamespace
import requests
import logging
from datetime import datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse
from flask import Blueprint, request, jsonify, current_app, session, send_file, Response
from sqlalchemy import or_, func
from werkzeug.security import generate_password_hash, check_password_hash
from app.utils.helpers import (
    get_config,
    set_config,
    set_configs,
    get_site_settings,
    get_material_folder,
    get_drafts_folder,
    discover_draft_roots,
    list_local_drafts,
    load_user_config,
    save_user_config,
    get_user_material_dir,
    get_user_data_dir,
    get_runtime_local_state_value,
    set_runtime_local_state_value,
    remove_runtime_local_state_value,
    generate_uuid,
    add_user_material,
    read_generate_logs,
)
from app.models.template_model import TemplateModel
from app.models.task import Task
from app.tasks import generate_video_task, handle_generate_success, generate_ai_task
from app.extensions import db
from app.models.user import User
from app.models.cdk_code import CdkCode
from app.models.cdk_template import CdkTemplate
from app.models.license_binding import LicenseBinding
from app.models.ai_provider import AIProvider
from app.models.user_api_key import UserApiKey
from app.models.ai_generation_log import AIGenerationLog
from app.models.ai_task import AITask
from app.models.user_material import UserMaterial
from app.models.manga_template import MangaTemplate
from app.models.manga_generation_log import MangaGenerationLog
from app.models.resource_exchange_post import ResourceExchangePost
from app.models.user_quota_log import UserQuotaLog
from app.models.user_quota import UserQuota
from app.utils.auth_token import extract_bearer_token, issue_token, validate_token
from app.services.user_quota_service import get_or_create_quota, quota_to_dict, deduct_quota
from app.utils.license_utils import generate_cdk_code, sign_payload, get_license_settings
from app.utils.jianying_mcp.utils.effect_manager import JianYingResourceManager
from app.utils.jianying_mcp.utils.index_manager import index_manager
from app.services.duo_video_service import DuoVideoService
from app.services.ai_service import generate_with_key
from app.services.openclaw_client import OpenClawClient
from app.utils.split_utils import (
    list_video_files,
    split_fixed_duration,
    split_by_count,
    detect_scenes,
    split_by_scenes,
    detect_silences,
    split_by_silence,
    split_by_subtitles,
    probe_video_info,
)
from app.utils.ffmpeg_utils import find_ffmpeg_with_source
from app.utils.remote_service import (
    call_remote_api,
    get_official_site_origin,
    remote_auth_mode_enabled,
)
from app.utils.security_ops import (
    audit_security_event,
    _audit_log_path,
    _rate_limit_path,
    build_identity,
    consume_rate_limit,
    get_request_ip,
)
from app.utils.runtime_paths import app_resource_path, runtime_file_path, runtime_path

api_bp = Blueprint('api', __name__, url_prefix='/api')
draft_logger = logging.getLogger("draft_inspect")
draft_logger.setLevel(logging.INFO)

_DRAFT_CONTENT_ENCODINGS = (
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "gb18030",
    "gbk",
)
_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
_VIDEO_EXTS = ('.mp4', '.mov', '.m4v', '.avi', '.mkv', '.flv', '.wmv')
_AUDIO_EXTS = ('.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac')
_ALL_MEDIA_EXTS = _IMAGE_EXTS + _VIDEO_EXTS + _AUDIO_EXTS

_OPTIONAL_API_FEATURE_PREFIXES = {
    "DUO_FEATURES_ENABLED": ("/api/duo/",),
    "OPENCLAW_FEATURES_ENABLED": ("/api/openclaw/",),
    "MANGA_FEATURES_ENABLED": ("/api/manga/", "/api/ai/manga/"),
}

_FEATURE_FLAG_META = {
    "duo": {
        "config_key": "DUO_FEATURES_ENABLED",
        "flag": "DUO_FEATURES_ENABLED",
        "label": "Duo 资源",
    },
    "openclaw": {
        "config_key": "OPENCLAW_FEATURES_ENABLED",
        "flag": "OPENCLAW_FEATURES_ENABLED",
        "label": "AI 漫剧服务",
    },
    "manga": {
        "config_key": "MANGA_FEATURES_ENABLED",
        "flag": "MANGA_FEATURES_ENABLED",
        "label": "AI 漫剧",
    },
}

_QUOTA_REASON_LABELS = {
    "register_trial": "新用户试用",
    "daily_checkin": "每日签到",
    "manga_generate": "AI 漫剧消耗",
    "generate_batch": "批量生成消耗",
    "export_drafts": "批量导出消耗",
    "license_activate": "激活授权",
    "refund": "失败返还",
    "invite_referrer_reward": "邀请激活奖励",
    "invite_invitee_reward": "受邀激活加赠",
}
_RESOURCE_EXCHANGE_PROJECT_LIMIT = 15
_RESOURCE_EXCHANGE_INTRO_LIMIT = 30
_RESOURCE_EXCHANGE_PAGE_SIZE = 20
_MAX_INVITE_REWARD_PERCENT = 100
_TRIAL_DEVICE_CLAIM_PREFIX = "trial_device_claim:"
_REMOTE_ONLINE_CACHE_TTL_SECONDS = 8
_REMOTE_AUTH_USER_CACHE_TTL_SECONDS = 900
_DESKTOP_TASK_CLAIM_TTL_MINUTES = 30
_remote_online_guard_cache = {
    "checked_at": 0.0,
    "status": None,
}
_remote_auth_user_cache = {}
_native_device_fingerprint_cache = None
_ASSISTANT_FREE_ACTIONS = {
    "navigate",
    "create_material_layout",
    "fill_text_template",
}
_REMOTE_PROXY_PREFIXES = (
    "/api/auth/",
    "/api/license/",
    "/api/admin/",
    "/api/resource-exchange/",
    "/api/ai/",
    "/api/user/keys",
    "/api/user/materials",
    "/api/manga/templates",
    "/api/manga/history",
    "/api/site-settings",
)
_REMOTE_PROXY_EXACTS = {
    "/api/user/info",
    "/api/user/points/overview",
    "/api/user/checkin",
}
_LOCAL_ONLY_PREFIXES = (
    "/api/runtime/",
    "/api/runtime-features",
    "/api/desktop/",
    "/api/browse-folder",
    "/api/browse-file",
    "/api/open-folder",
    "/api/workspace/settings",
    "/api/user/config",
    "/api/drafts/",
    "/api/draft/",
    "/api/generate-batch",
    "/api/task/",
    "/api/materials/",
    "/api/effects/",
    "/api/assistant/",
    "/api/openclaw/test",
    "/api/ai/manga/generate",
    "/api/ai/manga/generate-draft",
    "/api/duo/",
    "/api/split",
    "/api/export/",
    "/api/micro-adjust",
)
_REMOTE_PROXY_LOCAL_EXACTS = {
    "/api/task/refund",
}


def _desktop_dialog_unavailable_response():
    return jsonify(
        {
            "ok": False,
            "error": "当前环境不支持本地文件选择，请在桌面端客户端中操作。",
        }
    ), 400


def _select_local_directory():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None

    root = tk.Tk()
    root.withdraw()
    try:
        return filedialog.askdirectory()
    finally:
        root.destroy()


def _select_local_file():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None

    root = tk.Tk()
    root.withdraw()
    try:
        return filedialog.askopenfilename()
    finally:
        root.destroy()


def _raw_runtime_flags():
    return {
        key: bool(current_app.config.get(meta["config_key"]))
        for key, meta in _FEATURE_FLAG_META.items()
    }


def _effective_runtime_features():
    raw = _raw_runtime_flags()
    return {
        "duo": raw["duo"],
        "openclaw": raw["openclaw"],
        "manga": raw["manga"],
    }


def _run_background(app, target, *args, **kwargs):
    def runner():
        with app.app_context():
            try:
                target(*args, **kwargs)
            except Exception:
                logging.exception("background task failed")
    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread


@api_bp.before_request
def _guard_optional_api_features():
    path = request.path or ""
    if _should_proxy_remote_request():
        return _proxy_remote_response()
    raw_flags = _raw_runtime_flags()
    for config_key, prefixes in _OPTIONAL_API_FEATURE_PREFIXES.items():
        if not raw_flags.get(next((name for name, meta in _FEATURE_FLAG_META.items() if meta["config_key"] == config_key), ""), False):
            if any(path.startswith(prefix) for prefix in prefixes):
                return jsonify(
                    {
                        "ok": False,
                        "error": f"{config_key.lower()} is disabled in this build",
                    }
                ), 404
    if path == "/api/ai/manga/generate" and not raw_flags.get("openclaw", False):
        return jsonify(
            {
                "ok": False,
                "error": "openclaw_features_enabled is required for ai manga in this build",
            }
        ), 404

def _dedupe_keep_order(items):
    seen = set()
    output = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _safe_int_config(key: str, default: int = 0) -> int:
    try:
        return int(get_config(key, str(default)) or default)
    except Exception:
        return default


def _clamp_int(value, default: int = 0, minimum: int = 0, maximum: Optional[int] = None) -> int:
    try:
        number = int(value)
    except Exception:
        number = int(default)
    if number < minimum:
        number = minimum
    if maximum is not None and number > maximum:
        number = maximum
    return number


def _get_default_user_quota_value() -> int:
    raw = get_config("default_user_quota", str(current_app.config.get("DEFAULT_USER_QUOTA", 0)))
    return _clamp_int(raw or current_app.config.get("DEFAULT_USER_QUOTA", 0) or 0, 0, 0, None)


def _get_official_site_origin() -> str:
    return get_official_site_origin()


def _get_request_origin() -> str:
    try:
        return f"{request.scheme}://{request.host}"
    except Exception:
        return ""


def _is_local_runtime_request() -> bool:
    host = (request.host or "").split(":", 1)[0].strip().lower()
    remote_addr = (request.remote_addr or "").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1"} and remote_addr in {"127.0.0.1", "localhost", "::1", ""}


def _require_local_runtime_same_origin():
    if not _is_local_runtime_request():
        return jsonify({'ok': False, 'error': 'not available'}), 404

    request_origin = _get_request_origin().lower()
    origin = (request.headers.get("Origin") or "").strip().lower()
    referer = (request.headers.get("Referer") or "").strip().lower()
    if origin and origin != request_origin:
        return jsonify({'ok': False, 'error': 'cross-origin local runtime request blocked'}), 403
    if referer and not referer.startswith(f"{request_origin}/"):
        return jsonify({'ok': False, 'error': 'cross-origin local runtime request blocked'}), 403
    return None


def _normalize_http_service_url(value: str, *, allow_localhost: bool = True) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("service url must be a valid http/https address")
    hostname = (parsed.hostname or "").strip().lower()
    if not allow_localhost and hostname in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("localhost service url is not allowed in current mode")
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}"
    return normalized.rstrip("/")


def _should_use_remote_auth() -> bool:
    return _is_local_runtime_request() and remote_auth_mode_enabled() and bool(_get_official_site_origin())


def _build_remote_user(raw_user: dict):
    data = raw_user if isinstance(raw_user, dict) else {}
    return SimpleNamespace(
        id=int(data.get("id") or 0),
        username=data.get("username") or "",
        email=data.get("email"),
        role=data.get("role") or "user",
        ref_code=data.get("ref_code") or "",
        referrer_id=data.get("referrer_id"),
        membership_label=data.get("membership_label") or "",
        is_vip=bool(data.get("is_vip")),
    )


def _fetch_remote_user_by_token(token: str):
    response = call_remote_api(
        "/api/user/info",
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    try:
        data = response.json()
    except Exception:
        data = {}
    if not response.ok or not isinstance(data, dict) or not data.get("ok"):
        error = data.get("error") if isinstance(data, dict) else "remote auth failed"
        if response.status_code == 401:
            return None, error or "remote auth failed", 401
        if response.status_code == 403:
            return None, error or "remote auth failed", 403
        return None, error or f"remote auth failed: {response.status_code}", response.status_code or 502
    return _build_remote_user(data.get("user") or {}), None, None


def _remote_auth_cache_key(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _get_cached_remote_user(token: str):
    if not token:
        return None
    cache_key = _remote_auth_cache_key(token)
    cached = _remote_auth_user_cache.get(cache_key)
    if not isinstance(cached, dict):
        return None
    expires_at = float(cached.get("expires_at") or 0.0)
    if expires_at <= time.time():
        _remote_auth_user_cache.pop(cache_key, None)
        return None
    raw_user = cached.get("user")
    if not isinstance(raw_user, dict):
        _remote_auth_user_cache.pop(cache_key, None)
        return None
    return _build_remote_user(raw_user)


def _store_cached_remote_user(token: str, user) -> None:
    if not token or not user:
        return
    _remote_auth_user_cache[_remote_auth_cache_key(token)] = {
        "expires_at": time.time() + _REMOTE_AUTH_USER_CACHE_TTL_SECONDS,
        "user": {
            "id": getattr(user, "id", 0),
            "username": getattr(user, "username", ""),
            "email": getattr(user, "email", None),
            "role": getattr(user, "role", "user"),
            "ref_code": getattr(user, "ref_code", ""),
            "referrer_id": getattr(user, "referrer_id", None),
            "membership_label": getattr(user, "membership_label", ""),
            "is_vip": bool(getattr(user, "is_vip", False)),
        },
    }


def _should_proxy_remote_request() -> bool:
    if not _should_use_remote_auth():
        return False
    path = request.path or ""
    if path.endswith("/refund") and path.startswith("/api/task/"):
        return True
    if path in _REMOTE_PROXY_LOCAL_EXACTS:
        return True
    if any(path.startswith(prefix) for prefix in _LOCAL_ONLY_PREFIXES):
        return False
    if path in _REMOTE_PROXY_EXACTS:
        return True
    return any(path.startswith(prefix) for prefix in _REMOTE_PROXY_PREFIXES)


def _proxy_remote_response():
    response = call_remote_api(
        path=request.full_path if request.query_string else request.path,
        method=request.method,
        headers=dict(request.headers),
        data=request.get_data() if request.method in {"POST", "PUT", "PATCH", "DELETE"} else None,
        timeout=30,
    )
    flask_response = Response(response.content, status=response.status_code)
    for key, value in response.headers.items():
        lower_key = key.lower()
        if lower_key in {"content-length", "transfer-encoding", "content-encoding", "connection"}:
            continue
        flask_response.headers[key] = value
    return flask_response


def _get_native_device_fingerprint_payload() -> dict:
    global _native_device_fingerprint_cache
    if isinstance(_native_device_fingerprint_cache, dict) and _native_device_fingerprint_cache.get("fingerprint"):
        return dict(_native_device_fingerprint_cache)

    machine_guid = ""
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                machine_guid = str(winreg.QueryValueEx(key, "MachineGuid")[0] or "").strip()
        except Exception:
            machine_guid = ""
    volume_serial = ""
    if os.name == "nt":
        try:
            import subprocess

            system_drive = (os.getenv("SystemDrive") or "C:").strip()
            output = subprocess.check_output(
                ["cmd", "/c", "vol", system_drive],
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
            )
            matched = re.search(r"([A-F0-9]{4}-[A-F0-9]{4})", output.upper())
            if matched:
                volume_serial = matched.group(1)
        except Exception:
            volume_serial = ""

    hostname = socket.gethostname() or platform.node() or "desktop-runtime"
    label = os.getenv("COMPUTERNAME") or hostname
    raw_parts = [
        "desktop-runtime",
        platform.system(),
        platform.release(),
        platform.version(),
        platform.machine(),
        hostname,
        os.getenv("PROCESSOR_IDENTIFIER") or "",
        str(uuid.getnode() or ""),
        machine_guid,
        volume_serial,
    ]
    raw = "|".join([item for item in raw_parts if item])
    fingerprint = f"desktop-{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"
    _native_device_fingerprint_cache = {
        "fingerprint": fingerprint,
        "label": label,
        "source": "desktop_runtime",
    }
    return dict(_native_device_fingerprint_cache)


def _remote_online_status(force_refresh: bool = False) -> dict:
    now_ts = time.time()
    cached = _remote_online_guard_cache.get("status")
    checked_at = float(_remote_online_guard_cache.get("checked_at") or 0.0)
    if cached and not force_refresh and (now_ts - checked_at) < _REMOTE_ONLINE_CACHE_TTL_SECONDS:
        return dict(cached)

    official_origin = _get_official_site_origin()
    current_origin = _get_request_origin()
    official_netloc = (urlparse(official_origin).netloc or "").lower() if official_origin else ""
    current_netloc = (urlparse(current_origin).netloc or "").lower() if current_origin else ""

    if not official_origin:
        status = {
            "enabled": False,
            "ok": True,
            "reason": "official_site_url_not_configured",
            "official_origin": "",
            "server_time": _now().isoformat(),
        }
    elif official_netloc == current_netloc:
        status = {
            "enabled": False,
            "ok": True,
            "reason": "same_origin_server_mode",
            "official_origin": official_origin,
            "server_time": _now().isoformat(),
        }
    else:
        probe_url = f"{official_origin.rstrip('/')}/api/runtime-features"
        try:
            response = requests.get(probe_url, timeout=3)
            data = response.json() if response.headers.get("content-type", "").lower().find("application/json") >= 0 else {}
            ok = bool(response.ok and isinstance(data, dict) and data.get("ok"))
            status = {
                "enabled": True,
                "ok": ok,
                "reason": "remote_probe_ok" if ok else f"remote_probe_failed:{response.status_code}",
                "official_origin": official_origin,
                "server_time": _now().isoformat(),
            }
            if isinstance(data, dict):
                status["remote_server_time"] = data.get("server_time")
        except Exception as exc:
            status = {
                "enabled": True,
                "ok": False,
                "reason": "remote_probe_error",
                "official_origin": official_origin,
                "server_time": _now().isoformat(),
                "error": str(exc),
            }

    _remote_online_guard_cache["checked_at"] = now_ts
    _remote_online_guard_cache["status"] = dict(status)
    return status


def _require_remote_online(action_key: str):
    status = _remote_online_status()
    if status.get("ok"):
        return None
    return jsonify({
        "ok": False,
        "error": "当前功能需要联网校验后才能执行，请恢复网络后重试。",
        "action_key": action_key,
        "online_required": True,
        "online_status": status,
    }), 503


def _rate_limit_response(action_key: str, message: str, retry_after: int):
    return jsonify({
        "ok": False,
        "error": message,
        "action_key": action_key,
        "retry_after": int(retry_after or 0),
    }), 429


def _enforce_rate_limit(action_key: str, *, limit: int, window_seconds: int, identity_parts: list, user_id=None, details: dict = None):
    identity = build_identity(*identity_parts)
    allowed, remaining, retry_after = consume_rate_limit(action_key, identity, limit, window_seconds)
    if allowed:
        return None
    audit_security_event(
        f"{action_key}_rate_limited",
        level="warning",
        request_obj=request,
        user_id=user_id,
        details={
            "remaining": remaining,
            "retry_after": retry_after,
            **(details or {}),
        },
    )
    return _rate_limit_response(action_key, "请求过于频繁，请稍后重试", retry_after)


def _build_usage_policy() -> dict:
    manga_cost = int(get_config("manga_generate_cost", "1") or 1)
    export_cost = 1
    online_status = _remote_online_status()
    return {
        "count_consuming_actions": [
            {
                "key": "generate_batch",
                "label": "批量混剪",
                "cost_display": "每次成功生成任务扣 1 次",
                "online_required": True,
            },
            {
                "key": "export_drafts",
                "label": "批量导出",
                "cost_display": f"每次成功导出任务扣 {export_cost} 次",
                "online_required": True,
            },
            {
                "key": "ai_manga",
                "label": "AI 漫剧",
                "cost_display": f"每次成功生成扣 {manga_cost} 次",
                "online_required": True,
            },
        ],
        "quota_gain_actions": [
            {
                "key": "register_trial",
                "label": "新用户试用",
                "description": f"新用户首次注册可获得 {_get_default_user_quota_value()} 次体验次数，同一设备只发放一次",
            },
            {
                "key": "daily_checkin",
                "label": "每日签到",
                "description": f"每天签到可领取 {_get_daily_checkin_reward()} 次",
            },
            {
                "key": "license_activate_bonus",
                "label": "会员卡附赠次数",
                "description": "部分会员卡会附带额外次数，激活成功后自动到账",
            },
            {
                "key": "failed_task_refund",
                "label": "失败任务返还",
                "description": "已扣除但任务失败时，可返还对应次数",
            },
        ],
        "vip_gain_actions": [
            {
                "key": "license_activate_vip",
                "label": "CDK / 会员开卡",
                "description": "开卡成功后按卡时长延长 VIP 到期时间",
            },
            {
                "key": "invite_rewards",
                "label": "邀请奖励",
                "description": "被邀请人首次开卡后，邀请人与被邀请人按后台百分比加赠 VIP 天数",
            },
        ],
        "free_actions": [
            {"key": "resource_exchange", "label": "资源互换", "description": "免费功能，不扣次数"},
            {"key": "effects_and_duo", "label": "效果配置 / Duo 资源浏览", "description": "只浏览、搜索和配置时不扣次数"},
            {"key": "draft_tools", "label": "草稿读取 / 批量分割 / 片段微调", "description": "当前不扣次数"},
            {"key": "account_center", "label": "账户中心 / 邀请中心 / 使用教程", "description": "查看信息不扣次数"},
            {"key": "byok_ai_tools", "label": "AI 成片 / 文本 / 音频 / 视频生成", "description": "当前走 BYOK，不走平台次数"},
            {"key": "assistant", "label": "智能助手", "description": "当前只允许导航、创建素材目录、生成文字模板这类免费动作，不直接代执行扣次功能"},
        ],
        "online_required_actions": [
            {"key": "register", "label": "注册"},
            {"key": "login", "label": "登录"},
            {"key": "daily_checkin", "label": "每日签到"},
            {"key": "license_activate", "label": "授权激活"},
            {"key": "license_deactivate", "label": "授权解绑"},
            {"key": "generate_batch", "label": "批量混剪（按组精准替换 / 混剪裂变替换 / 分区混剪裂变 / 槽位拼接混剪）"},
            {"key": "export_drafts", "label": "批量导出"},
            {"key": "ai_manga", "label": "AI 漫剧"},
        ],
        "offline_policy": {
            "count_changing_actions_require_online": True,
            "authorization_actions_require_online": True,
            "message": "断网或无法连到验证服务时，扣次数、加次数、改授权状态这类服务端校验动作会直接拦截。",
        },
        "online_status": online_status,
    }


def _hash_trial_device_fingerprint(device_fingerprint: str) -> str:
    clean = (device_fingerprint or "").strip()
    if not clean:
        return ""
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def _claim_trial_device_quota(device_fingerprint: str, user_id: int) -> dict:
    fingerprint_hash = _hash_trial_device_fingerprint(device_fingerprint)
    if not fingerprint_hash:
        return {"granted": False, "reason": "missing_device_fingerprint"}
    claim_key = f"{_TRIAL_DEVICE_CLAIM_PREFIX}{fingerprint_hash}"
    existing = get_config(claim_key, "")
    if existing:
        return {"granted": False, "reason": "device_already_claimed"}
    set_config(claim_key, json.dumps({
        "user_id": int(user_id),
        "claimed_at": _now().isoformat(),
        "fingerprint_hash": fingerprint_hash,
    }, ensure_ascii=False))
    return {
        "granted": True,
        "reason": "first_device",
        "claim_key": claim_key,
        "log_key": f"trial:{fingerprint_hash[:24]}",
    }


def _get_json_config(key: str, default):
    raw = get_config(key, "")
    if not raw:
        return default
    try:
        data = json.loads(raw)
    except Exception:
        return default
    return data if isinstance(data, type(default)) else default


def _set_json_config(key: str, value) -> None:
    set_config(key, json.dumps(value, ensure_ascii=False))


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _resource_exchange_membership_value(user: User, quota_payload: Optional[dict] = None) -> int:
    payload = quota_payload or quota_to_dict(get_or_create_quota(user.id))
    if user.role == "admin":
        return 999999
    if payload.get("is_vip"):
        return 199
    return 0


def _resource_exchange_membership_label(user: User, quota_payload: Optional[dict] = None) -> str:
    payload = quota_payload or quota_to_dict(get_or_create_quota(user.id))
    if user.role == "admin":
        return "管理员"
    if payload.get("is_vip"):
        return "VIP会员"
    return "试用用户"


def _resource_exchange_sort_key(item: dict):
    status = str(item.get("status") or "pending")
    approved_at = _parse_iso_datetime(item.get("approved_at")) or _parse_iso_datetime(item.get("reviewed_at")) or _parse_iso_datetime(item.get("created_at")) or datetime.min
    created_at = _parse_iso_datetime(item.get("created_at")) or datetime.min
    return (
        int(item.get("membership_value") or 0),
        1 if status == "approved" else 0,
        approved_at.timestamp() if approved_at != datetime.min else 0,
        created_at.timestamp() if created_at != datetime.min else 0,
    )


def _paginate_items(items: list[dict], page: int = 1, per_page: int = _RESOURCE_EXCHANGE_PAGE_SIZE) -> dict:
    clean_per_page = max(1, min(int(per_page or _RESOURCE_EXCHANGE_PAGE_SIZE), 100))
    clean_page = max(1, int(page or 1))
    total = len(items)
    pages = max(1, (total + clean_per_page - 1) // clean_per_page)
    if clean_page > pages:
        clean_page = pages
    start = (clean_page - 1) * clean_per_page
    end = start + clean_per_page
    return {
        "items": items[start:end],
        "pagination": {
            "page": clean_page,
            "per_page": clean_per_page,
            "pages": pages,
            "total": total,
        },
    }


def _validate_resource_exchange_payload(data: dict) -> tuple[Optional[dict], Optional[str]]:
    payload = data if isinstance(data, dict) else {}
    project_name = (payload.get("project_name") or "").strip()
    project_intro = (payload.get("project_intro") or "").strip()
    contact = (payload.get("contact") or "").strip()
    if not project_name or not project_intro or not contact:
        return None, "所有字段都是必填项"
    if len(project_name) > _RESOURCE_EXCHANGE_PROJECT_LIMIT:
        return None, f"项目名称不能超过 {_RESOURCE_EXCHANGE_PROJECT_LIMIT} 个字"
    if len(project_intro) > _RESOURCE_EXCHANGE_INTRO_LIMIT:
        return None, f"项目介绍不能超过 {_RESOURCE_EXCHANGE_INTRO_LIMIT} 个字"
    return {
        "project_name": project_name,
        "project_intro": project_intro,
        "contact": contact,
    }, None


def _resource_exchange_post_to_dict(item: ResourceExchangePost | dict | None) -> dict:
    post = item if isinstance(item, dict) else {}
    if isinstance(item, ResourceExchangePost):
        post = {
            "id": item.id,
            "user_id": item.user_id,
            "username": item.username,
            "membership_label": item.membership_label,
            "membership_value": item.membership_value,
            "project_name": item.project_name,
            "project_intro": item.project_intro,
            "contact": item.contact,
            "status": item.status,
            "created_at": item.created_at.isoformat() if item.created_at else "",
            "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else "",
            "approved_at": item.approved_at.isoformat() if item.approved_at else "",
            "review_reason": item.review_reason or "",
            "reviewer_id": item.reviewer_id or 0,
            "reviewer_name": item.reviewer_name or "",
        }
    return {
        "id": str(post.get("id") or uuid.uuid4().hex[:12]),
        "user_id": int(post.get("user_id") or 0),
        "username": str(post.get("username") or "").strip(),
        "membership_label": str(post.get("membership_label") or "试用用户").strip() or "试用用户",
        "membership_value": int(post.get("membership_value") or 0),
        "project_name": str(post.get("project_name") or "").strip(),
        "project_intro": str(post.get("project_intro") or "").strip(),
        "contact": str(post.get("contact") or "").strip(),
        "status": str(post.get("status") or "pending").strip() or "pending",
        "created_at": str(post.get("created_at") or ""),
        "reviewed_at": str(post.get("reviewed_at") or ""),
        "approved_at": str(post.get("approved_at") or ""),
        "review_reason": str(post.get("review_reason") or "").strip(),
        "reviewer_id": int(post.get("reviewer_id") or 0),
        "reviewer_name": str(post.get("reviewer_name") or "").strip(),
    }


def _build_resource_exchange_public_item(item: dict) -> dict:
    post = _resource_exchange_post_to_dict(item)
    return {
        "id": post["id"],
        "membership_label": post["membership_label"],
        "membership_value": post["membership_value"],
        "project_name": post["project_name"],
        "project_intro": post["project_intro"],
        "contact": post["contact"],
        "published_at": post["approved_at"] or post["created_at"],
        "username": post["username"],
    }


def _manga_aspect_preset(aspect: str) -> tuple[int, int, str]:
    normalized = (aspect or "portrait").strip().lower()
    mapping = {
        "portrait": (1080, 1920, "竖屏 9:16"),
        "landscape": (1920, 1080, "横屏 16:9"),
        "square": (1080, 1080, "方屏 1:1"),
    }
    return mapping.get(normalized, mapping["portrait"])


def _clean_manga_scene_text(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^\s*(?:第\s*\d+\s*[幕场集话]|[\d一二三四五六七八九十]+)\s*[\.\-、:：)]*\s*", "", value)
    return value.strip()


def _parse_manga_script_scenes(script: str) -> list[str]:
    parts = []
    for raw in re.split(r"[\r\n]+", str(script or "")):
        text = _clean_manga_scene_text(raw)
        if text:
            parts.append(text)
    if not parts:
        single = _clean_manga_scene_text(script or "")
        if single:
            parts.append(single)
    return parts


def _normalize_manga_draft_scenes(data: dict) -> list[dict]:
    payload = data if isinstance(data, dict) else {}
    raw_scenes = payload.get("scenes") if isinstance(payload.get("scenes"), list) else []
    default_duration = payload.get("scene_duration")
    try:
        default_duration = max(1.0, min(float(default_duration or 3), 30.0))
    except Exception:
        default_duration = 3.0

    scenes: list[dict] = []
    for index, item in enumerate(raw_scenes, start=1):
        if isinstance(item, dict):
            text = _clean_manga_scene_text(item.get("text") or item.get("title") or "")
            duration_raw = item.get("duration")
        else:
            text = _clean_manga_scene_text(item)
            duration_raw = None
        if not text:
            continue
        try:
            duration = max(1.0, min(float(duration_raw or default_duration), 30.0))
        except Exception:
            duration = default_duration
        scenes.append({
            "index": index,
            "text": text,
            "duration": duration,
        })

    if scenes:
        return scenes[:50]

    parsed = _parse_manga_script_scenes(payload.get("script") or "")
    return [
        {
            "index": index,
            "text": text,
            "duration": default_duration,
        }
        for index, text in enumerate(parsed[:50], start=1)
    ]


def _manga_draft_asset_root(user_id: int) -> str:
    return os.path.join(get_user_data_dir(user_id), "manga_draft_assets")


def _manga_draft_cache_root(user_id: int) -> str:
    return os.path.join(get_user_data_dir(user_id), "manga_draft_cache")


def _ensure_manga_placeholder_video(user_id: int, width: int, height: int, duration: float) -> str:
    ffmpeg, _source = find_ffmpeg_with_source()
    if not ffmpeg:
        raise ValueError("未找到 ffmpeg，暂时无法为 AI 漫剧草稿生成占位片段。")

    asset_root = os.path.join(_manga_draft_asset_root(user_id), "placeholders")
    os.makedirs(asset_root, exist_ok=True)
    target_duration = max(1.0, float(duration or 1.0))
    render_duration = round(target_duration + 1.0, 3)
    duration_tag = str(int(round(render_duration * 10)))
    output_path = os.path.join(asset_root, f"placeholder_{width}x{height}_{duration_tag}.mp4")
    if os.path.exists(output_path):
        return output_path

    import subprocess

    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0xE2E8F0:s={width}x{height}:d={render_duration:.3f}",
        "-r",
        "30",
        "-pix_fmt",
        "yuv420p",
        output_path,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        raise ValueError(f"生成 AI 漫剧占位片段失败: {exc}") from exc
    return output_path


def _build_manga_material_workspace(user_id: int, project_id: str, project_name: str, scenes: list[dict]) -> dict:
    safe_project = _safe_folder_name(project_name, project_id)
    workspace_root = os.path.join(get_user_data_dir(user_id), "manga_projects", f"{safe_project}_{project_id}")
    materials_root = os.path.join(workspace_root, "scene_materials")
    os.makedirs(materials_root, exist_ok=True)

    folders = []
    notes = []
    for scene in scenes:
        index = int(scene.get("index") or len(folders) + 1)
        title = str(scene.get("text") or f"场景 {index}").strip()
        folder_name = _safe_folder_name(f"{index:02d}_{title[:12]}", f"{index:02d}_scene")
        folder_path = os.path.join(materials_root, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        folders.append({
            "index": index,
            "title": title,
            "path": folder_path,
        })
        notes.append(f"{index:02d}. {title} | 参考时长 {float(scene.get('duration') or 3):.1f}s")

    script_path = os.path.join(workspace_root, "scene_notes.txt")
    with open(script_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(notes) if notes else "暂无场景说明")

    return {
        "workspace_root": workspace_root,
        "materials_root": materials_root,
        "script_path": script_path,
        "folders": folders,
    }


def _get_invite_settings() -> dict:
    return {
        "referrer_reward": _clamp_int(_safe_int_config("invite_referrer_reward", 3), 3, 0, _MAX_INVITE_REWARD_PERCENT),
        "invitee_reward": _clamp_int(_safe_int_config("invite_invitee_reward", 2), 2, 0, _MAX_INVITE_REWARD_PERCENT),
    }


def _extend_vip_expire_at(quota: UserQuota, days: int, now: Optional[datetime] = None) -> Optional[datetime]:
    extra_days = int(days or 0)
    if extra_days <= 0:
        return quota.vip_expire_at
    current_time = now or _now()
    base = quota.vip_expire_at if quota.vip_expire_at and quota.vip_expire_at > current_time else current_time
    quota.vip_expire_at = base + timedelta(days=extra_days)
    return quota.vip_expire_at


def _assistant_log_path(user_id: int) -> str:
    return os.path.join(get_user_data_dir(user_id), "assistant.log")


def _append_assistant_log(user_id: int, stage: str, payload: dict) -> None:
    path = _assistant_log_path(user_id)
    record = {
        "id": uuid.uuid4().hex[:12],
        "stage": stage,
        "created_at": datetime.utcnow().isoformat(),
        "payload": payload or {},
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_assistant_logs(user_id: int, limit: int = 20) -> list[dict]:
    path = _assistant_log_path(user_id)
    if not os.path.exists(path):
        return []
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                if isinstance(data, dict):
                    items.append(data)
    except Exception:
        return []
    if limit and len(items) > limit:
        items = items[-limit:]
    return list(reversed(items))


def _safe_folder_name(name: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(name or "").strip()).strip(" .")
    return cleaned or fallback

def _generate_ref_code() -> str:
    import secrets
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _ensure_user_ref_code(user, commit: bool = False) -> bool:
    if not user or getattr(user, "ref_code", None):
        return False
    for _ in range(10):
        candidate = _generate_ref_code()
        if User.query.filter_by(ref_code=candidate).first():
            continue
        user.ref_code = candidate
        db.session.add(user)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return True
    fallback = uuid.uuid4().hex[:8].upper()
    user.ref_code = fallback
    db.session.add(user)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return True


def _build_user_profile_payload(user: User, quota: Optional[UserQuota] = None) -> dict:
    quota = quota or get_or_create_quota(user.id)
    quota_payload = quota_to_dict(quota)
    referrer = User.query.get(user.referrer_id) if getattr(user, "referrer_id", None) else None
    invite_overview = _build_user_invite_overview(user)
    membership_label = "管理员" if user.role == "admin" else ("VIP会员" if quota_payload["is_vip"] else "试用用户")
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "membership_label": membership_label,
        "ref_code": user.ref_code,
        "referrer_id": user.referrer_id,
        "referrer_username": referrer.username if referrer else None,
        "invite": invite_overview,
        **quota_payload,
    }


def _build_user_invite_overview(user: Union[User, int, None]) -> dict:
    user_id = user.id if isinstance(user, User) else int(user or 0)
    if user_id <= 0:
        settings = _get_invite_settings()
        return {
            "invited_count": 0,
            "referrer_reward_total": 0,
            "invitee_reward_total": 0,
            "recent_invited_users": [],
            "referrer_reward": settings["referrer_reward"],
            "invitee_reward": settings["invitee_reward"],
        }

    settings = _get_invite_settings()
    invitees = User.query.filter_by(referrer_id=user_id).order_by(User.created_at.desc(), User.id.desc()).limit(8).all()
    referrer_reward_total = db.session.query(func.coalesce(func.sum(UserQuotaLog.change), 0)).filter(
        UserQuotaLog.user_id == user_id,
        UserQuotaLog.reason == "invite_referrer_reward",
    ).scalar() or 0
    invitee_reward_total = db.session.query(func.coalesce(func.sum(UserQuotaLog.change), 0)).filter(
        UserQuotaLog.user_id == user_id,
        UserQuotaLog.reason == "invite_invitee_reward",
    ).scalar() or 0
    invited_count = db.session.query(func.count(User.id)).filter(User.referrer_id == user_id).scalar() or 0
    return {
        "invited_count": int(invited_count),
        "referrer_reward_total": int(referrer_reward_total),
        "invitee_reward_total": int(invitee_reward_total),
        "recent_invited_users": [
            {
                "id": item.id,
                "username": item.username,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in invitees
        ],
        "referrer_reward": settings["referrer_reward"],
        "invitee_reward": settings["invitee_reward"],
    }


def _build_vip_rules_summary() -> dict:
    settings = get_license_settings()
    invite_settings = _get_invite_settings()
    return {
        "default_user_quota": _get_default_user_quota_value(),
        "daily_checkin_reward": _get_daily_checkin_reward(),
        "license_points_ratio": int(settings.get("points_ratio", 1) or 1),
        "manga_generate_cost": int(get_config("manga_generate_cost", "1") or 1),
        "invite_referrer_reward": invite_settings["referrer_reward"],
        "invite_invitee_reward": invite_settings["invitee_reward"],
        "usage_policy": _build_usage_policy(),
    }


def _apply_invite_registration_rewards(user: User) -> dict:
    return {"ok": False, "awards": {}, "deferred": True}


def _invite_reward_days(duration_days: int, percent_value: int) -> int:
    if int(duration_days or 0) <= 0 or int(percent_value or 0) <= 0:
        return 0
    return max(1, int(math.ceil((float(duration_days) * float(percent_value)) / 100.0 - 1e-9)))


def _apply_invite_license_rewards(user: User, license_code: str, duration_days: int) -> dict:
    if not user or not user.referrer_id or user.referrer_id == user.id:
        return {"ok": False, "awards": {}}

    referrer = User.query.get(user.referrer_id)
    if not referrer:
        return {"ok": False, "awards": {}}

    settings = _get_invite_settings()
    project_id = f"invite_license:{license_code}"
    current_time = _now()
    awards = {}
    referrer_days = _invite_reward_days(duration_days, settings["referrer_reward"])
    invitee_days = _invite_reward_days(duration_days, settings["invitee_reward"])

    if referrer_days > 0:
        existing = UserQuotaLog.query.filter_by(
            user_id=referrer.id,
            reason="invite_referrer_reward",
            project_id=project_id,
        ).first()
        if not existing:
            quota = get_or_create_quota(referrer.id, auto_commit=False)
            _extend_vip_expire_at(quota, referrer_days, current_time)
            db.session.add(quota)
            db.session.add(UserQuotaLog(
                user_id=referrer.id,
                change=referrer_days,
                reason="invite_referrer_reward",
                project_id=project_id,
                remaining_after=quota.remaining,
            ))
            awards["referrer_reward"] = referrer_days

    if invitee_days > 0:
        existing = UserQuotaLog.query.filter_by(
            user_id=user.id,
            reason="invite_invitee_reward",
            project_id=project_id,
        ).first()
        if not existing:
            quota = get_or_create_quota(user.id, auto_commit=False)
            _extend_vip_expire_at(quota, invitee_days, current_time)
            db.session.add(quota)
            db.session.add(UserQuotaLog(
                user_id=user.id,
                change=invitee_days,
                reason="invite_invitee_reward",
                project_id=project_id,
                remaining_after=quota.remaining,
            ))
            awards["invitee_reward"] = invitee_days

    return {"ok": bool(awards), "awards": awards, "referrer": referrer.username}


def _build_material_layout(base_root: str, draft_name: str, strategy: str, slots: list[str]) -> dict:
    if not base_root:
        raise ValueError("请先选择素材根目录")
    if not draft_name:
        raise ValueError("缺少草稿名称")

    safe_draft_name = _safe_folder_name(draft_name, "draft")
    target_root = os.path.join(base_root, safe_draft_name)
    os.makedirs(target_root, exist_ok=True)

    normalized_slots = [item for item in (slots or []) if str(item or "").strip()]
    if strategy == "mix":
        normalized_slots = normalized_slots or ["素材池"]
    elif not normalized_slots:
        normalized_slots = ["槽位 1"]

    created = []
    for index, raw_name in enumerate(normalized_slots, start=1):
        label = str(raw_name or "").strip() or f"槽位 {index}"
        if strategy == "partition":
            folder_name = _safe_folder_name(label, f"part_{index:02d}")
        elif strategy == "mix":
            folder_name = _safe_folder_name(label, "素材池")
        else:
            folder_name = _safe_folder_name(f"{index:02d}_{label}", f"{index:02d}")
        folder_path = os.path.join(target_root, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        created.append({"label": label, "path": folder_path})

    return {
        "root": target_root,
        "folders": created,
        "draft_name": safe_draft_name,
        "strategy": strategy,
    }


def _assistant_route_preview(command: str, context: Optional[dict] = None) -> dict:
    text = (command or "").strip()
    lowered = text.lower()
    ctx = context if isinstance(context, dict) else {}
    draft_path = (ctx.get("draft_path") or "").strip()
    materials_root = (ctx.get("materials_root") or "").strip()
    slots = [str(item).strip() for item in (ctx.get("slots") or []) if str(item).strip()]
    text_count = int(ctx.get("text_count") or 0)
    strategy = (ctx.get("strategy") or "group").strip() or "group"

    if not text:
        return {
            "ok": False,
            "error": "请输入要执行的助手命令",
        }

    if ("分区" in text and "视频" in text) or "分区混剪" in text:
        return {
            "ok": True,
            "intent": "open_partition_mix",
            "summary": "打开批量混剪并切到“分区混剪裂变”。",
            "requires_confirmation": False,
            "impact": "仅导航，不会直接执行生成。",
            "client_action": {
                "type": "navigate",
                "panel_id": "panel-materials",
                "mix_target": "partition",
                "anchor": "mix-mode-partition-anchor",
            },
        }

    if ("按组" in text and "混剪" in text) or "精准替换" in text:
        return {
            "ok": True,
            "intent": "open_group_mix",
            "summary": "打开批量混剪并切到“按组精准替换”。",
            "requires_confirmation": False,
            "impact": "仅导航，不会直接执行生成。",
            "client_action": {
                "type": "navigate",
                "panel_id": "panel-materials",
                "mix_target": "group",
                "anchor": "mix-mode-group-anchor",
            },
        }

    if "导出" in text and "草稿" in text:
        return {
            "ok": True,
            "intent": "open_export",
            "summary": "打开批量导出页并准备导出当前已选草稿。",
            "requires_confirmation": False,
            "impact": "仅导航到导出页，真正导出仍需你确认执行。",
            "client_action": {
                "type": "navigate",
                "panel_id": "panel-export",
                "subtab_target": "export-settings",
            },
        }

    if ("检查" in text or "查看" in text) and "草稿" in text and ("槽位" in text or "结构" in text):
        return {
            "ok": True,
            "intent": "inspect_draft_slots",
            "summary": "打开草稿结构检查入口，方便核对槽位与文字位置。",
            "requires_confirmation": False,
            "impact": "仅导航，不会修改草稿。",
            "client_action": {
                "type": "navigate",
                "panel_id": "panel-split",
                "subtab_target": "split-draft",
            },
        }

    if "创建" in text and ("素材目录" in text or "素材文件夹" in text):
        missing = []
        if not draft_path:
            missing.append("draft_path")
        if not materials_root:
            missing.append("materials_root")
        if strategy != "mix" and not slots:
            missing.append("slots")
        return {
            "ok": True,
            "intent": "create_material_layout",
            "summary": "按当前草稿和模式创建素材目录结构。",
            "requires_confirmation": True,
            "impact": "会在你选择的素材根目录下创建新的草稿素材目录。",
            "missing": missing,
            "client_action": {
                "type": "create_material_layout",
                "draft_path": draft_path,
                "materials_root": materials_root,
                "strategy": strategy,
                "slots": slots,
            },
        }

    if "生成" in text and "文字" in text and ("模板" in text or "替换" in text):
        return {
            "ok": True,
            "intent": "build_text_template",
            "summary": "为当前草稿生成一份可直接填写的文字替换模板。",
            "requires_confirmation": False,
            "impact": "仅生成模板内容，不会直接改写草稿。",
            "client_action": {
                "type": "fill_text_template",
                "text_count": text_count,
                "strategy": strategy,
            },
        }

    if "助手" in text and ("日志" in text or "记录" in text):
        return {
            "ok": True,
            "intent": "open_assistant_logs",
            "summary": "打开助手日志面板。",
            "requires_confirmation": False,
            "impact": "仅导航。",
            "client_action": {
                "type": "navigate",
                "panel_id": "panel-assistant",
            },
        }

    return {
        "ok": False,
        "error": "暂未识别这条命令。当前优先支持：分区混剪、按组混剪、导出当前草稿、检查草稿槽位、创建素材目录、生成文字替换模板。",
        "received": text,
        "matched_hint": lowered,
    }

def _find_draft_content_files(template_path: str):
    if not template_path:
        return []
    candidates = [os.path.join(template_path, "draft_content.json")]
    timelines_root = os.path.join(template_path, "Timelines")
    if os.path.isdir(timelines_root):
        for root, _, files in os.walk(timelines_root):
            if "draft_content.json" in files:
                candidates.append(os.path.join(root, "draft_content.json"))
    return _dedupe_keep_order(candidates)

def _load_json_with_encodings(path: str):
    last_err = None
    raw_bytes = None
    for attempt in range(3):
        try:
            with open(path, "rb") as f:
                raw_bytes = f.read()
            break
        except Exception as e:
            last_err = e
            if attempt >= 2:
                return None, e
            time.sleep(0.15)
    if not raw_bytes:
        return None, ValueError("empty file")

    for enc in _DRAFT_CONTENT_ENCODINGS:
        try:
            raw = raw_bytes.decode(enc).lstrip()
            if not raw:
                continue
            if raw[0] in "{[":
                decoder = json.JSONDecoder()
                data, _end = decoder.raw_decode(raw)
                return data, None
        except Exception as e:
            last_err = e

    # try base64-wrapped JSON
    try:
        import base64
        b64_text = raw_bytes.decode("ascii", errors="ignore").strip()
        if b64_text:
            decoded = base64.b64decode(b64_text, validate=True)
            for enc in _DRAFT_CONTENT_ENCODINGS:
                try:
                    text = decoded.decode(enc).lstrip()
                    if not text or text[0] not in "{[":
                        continue
                    decoder = json.JSONDecoder()
                    data, _end = decoder.raw_decode(text)
                    return data, None
                except Exception as e:
                    last_err = e
    except Exception as e:
        last_err = e
    return None, ValueError("non-json or encrypted content")

def _guess_extension(url: str, content_type: str, fallback: str) -> str:
    if content_type:
        ct = content_type.lower()
        if "image/" in ct:
            return "." + ct.split("image/")[-1].split(";")[0].strip()
        if "video/" in ct:
            return "." + ct.split("video/")[-1].split(";")[0].strip()
    if url:
        parsed = url.split("?")[0]
        _, ext = os.path.splitext(parsed)
        if ext:
            return ext
    return fallback

def _collect_urls(obj, path=""):
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else k
            results.extend(_collect_urls(v, child_path))
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            child_path = f"{path}[{idx}]"
            results.extend(_collect_urls(v, child_path))
    elif isinstance(obj, str):
        if obj.startswith("http://") or obj.startswith("https://"):
            results.append((path, obj))
    return results

def _classify_urls(url_items):
    images = []
    videos = []
    for path, url in url_items:
        key = path.lower()
        if any(x in key for x in ["avatar", "icon", "logo", "profile", "head"]):
            continue
        if any(x in key for x in ["video", "play", "mp4", "stream"]):
            videos.append(url)
            continue
        if any(x in key for x in ["image", "img", "cover", "pic", "photo", "thumb"]):
            images.append(url)
            continue
    # fallback: if nothing classified, return all as images
    if not images and not videos:
        images = [u for _, u in url_items]
    return list(dict.fromkeys(images)), list(dict.fromkeys(videos))

def _download_urls(urls, save_path, prefix, fallback_ext):
    saved = []
    for idx, url in enumerate(urls, start=1):
        try:
            r = requests.get(url, stream=True, timeout=120)
            if r.status_code != 200:
                continue
            ext = _guess_extension(url, r.headers.get("Content-Type", ""), fallback_ext)
            filename = f"{prefix}_{idx}{ext}"
            path = os.path.join(save_path, filename)
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            saved.append(path)
        except Exception:
            continue
    return saved


def _extract_first_url(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"https?://[^\s]+", text)
    if not match:
        return ""
    return match.group(0).rstrip("'\"),;]>}")


def _resolve_douyin_creator_requests(raw_value: str):
    value = (raw_value or "").strip()
    if not value:
        return []

    share_text = value
    sec_user_id = ""
    source = _extract_first_url(value) or value

    try:
        parsed = urlparse(source)
        params = parse_qs(parsed.query)
        sec_user_values = params.get("sec_user_id") or params.get("sec_userid") or []
        if sec_user_values:
            sec_user_id = unquote(sec_user_values[0]).strip()
        if not sec_user_id:
            path_parts = [part for part in parsed.path.split("/") if part]
            if "user" in path_parts:
                index = path_parts.index("user")
                if index + 1 < len(path_parts):
                    sec_user_id = unquote(path_parts[index + 1]).strip()
    except Exception:
        sec_user_id = ""

    if not sec_user_id and "sec_user_id=" in value:
        sec_user_id = value.split("sec_user_id=", 1)[1].split("&", 1)[0].strip()
    if not sec_user_id and not _extract_first_url(value) and not any(ch.isspace() for ch in value):
        sec_user_id = value

    candidates = []
    seen = set()
    for payload in (
        {"sec_user_id": sec_user_id} if sec_user_id else None,
        {"share_text": share_text} if share_text else None,
    ):
        if not payload:
            continue
        marker = tuple(sorted(payload.items()))
        if marker in seen:
            continue
        seen.add(marker)
        candidates.append(("/api/douyin/fetch_user_video_list", payload))
    return candidates


def _extract_oneapi_items(data_obj):
    if isinstance(data_obj, list):
        return data_obj
    if not isinstance(data_obj, dict):
        return []
    for key in ("notes", "aweme_list", "items", "list", "videos", "data"):
        value = data_obj.get(key)
        if isinstance(value, list):
            return value
    if any(key in data_obj for key in ("id", "note_id", "aweme_id", "bvid", "photo_id")):
        return [data_obj]
    return []


def _should_retry_oneapi_error(error_message: str) -> bool:
    text = (error_message or "").lower()
    if "http 429" in text or "http 5" in text:
        return True
    retry_tokens = (
        "empty response body",
        "non-json content",
        "request error",
        "timeout",
        "connection aborted",
        "connection reset",
        "temporarily unavailable",
    )
    return any(token in text for token in retry_tokens)


def _parse_oneapi_response(resp):
    if resp.status_code != 200:
        raw = (resp.text or "").strip()
        detail = raw[:200] if raw else "empty body"
        return None, f"OneAPI HTTP {resp.status_code}: {detail}"

    raw = (resp.text or "").strip()
    if not raw:
        return None, "OneAPI returned an empty response body"

    try:
        body = resp.json()
    except ValueError:
        return None, f"OneAPI returned non-JSON content: {raw[:200]}"

    if isinstance(body, list):
        return {"list": body}, None
    if not isinstance(body, dict):
        return None, f"OneAPI returned unsupported JSON: {type(body).__name__}"

    code = body.get("code")
    success = body.get("success")
    message = body.get("message") or body.get("msg") or body.get("error")
    success_codes = {None, 0, 200, "0", "200"}
    success_values = {None, True, 1, "1", "true", "True", "ok", "OK"}

    if code not in success_codes:
        return None, message or f"OneAPI business error (code={code})"
    if success not in success_values:
        return None, message or "OneAPI business error"

    data_obj = body.get("data")
    if data_obj is None:
        if any(key in body for key in ("notes", "aweme_list", "items", "list", "videos")):
            data_obj = body
        elif code in success_codes and not message:
            data_obj = {}
    if isinstance(data_obj, list):
        data_obj = {"list": data_obj}
    if data_obj is None:
        return None, message or "OneAPI returned no usable data"
    return data_obj, None


def _decode_data_uri(data_str: str) -> bytes:
    if not data_str:
        return b""
    if data_str.startswith("data:"):
        try:
            header, b64 = data_str.split(",", 1)
        except ValueError:
            return b""
        return base64.b64decode(b64)
    return base64.b64decode(data_str)


def _download_to_path(url: str, path: str) -> None:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)


def _openclaw_log_path() -> str:
    return str(runtime_file_path("user_data", "logs", "openclaw_error.log"))


def _log_openclaw_error(user_id: int, params: dict, error: str) -> None:
    try:
        record = {
            'time': datetime.utcnow().isoformat(),
            'user_id': user_id,
            'params': params,
            'error': error,
        }
        path = _openclaw_log_path()
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception:
        pass

def _save_character_image(save_dir: str, data_uri: str) -> str:
    if not data_uri:
        return ''
    try:
        data = _decode_data_uri(data_uri)
        if not data:
            return ''
        path = os.path.join(save_dir, 'character.png')
        with open(path, 'wb') as f:
            f.write(data)
        return path
    except Exception:
        return ''


def _encode_file_to_data_uri(path: str) -> str:
    if not path or not os.path.exists(path):
        return ''
    try:
        import base64
        with open(path, 'rb') as f:
            data = f.read()
        b64 = base64.b64encode(data).decode('utf-8')
        return 'data:image/png;base64,' + b64
    except Exception:
        return ''

    try:
        record = {
            'time': datetime.utcnow().isoformat(),
            'user_id': user_id,
            'params': params,
            'error': error,
        }
        path = _openclaw_log_path()
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception:
        pass

def _load_draft_content(template_path):
    if not template_path:
        return None, '缺少草稿路径'
    candidates = _find_draft_content_files(template_path)
    draft_logger.info("draft_inspect: candidates=%s", candidates)
    for draft_content in candidates:
        if not os.path.exists(draft_content):
            continue
        data, err = _load_json_with_encodings(draft_content)
        if err is None:
            draft_logger.info("draft_inspect: loaded=%s", draft_content)
            return data, None
        draft_logger.warning("draft_inspect: load_failed path=%s err=%s", draft_content, err)
    if candidates and any(os.path.exists(p) for p in candidates):
        return None, '解析失败: draft_content.json 读取失败'
    return None, '未找到 draft_content.json'

def _extract_materials_from_meta(template_path: str):
    meta_path = os.path.join(template_path, "draft_meta_info.json")
    if not os.path.exists(meta_path):
        return [], None
    draft_logger.info("draft_inspect: meta_path=%s", meta_path)
    data, err = _load_json_with_encodings(meta_path)
    if err is not None or not isinstance(data, dict):
        return [], f'解析失败: draft_meta_info.json 读取失败 ({err})'
    materials = []
    for group in data.get("draft_materials", []) or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("value", []) or []:
            if not isinstance(item, dict):
                continue
            path = (
                item.get("file_Path")
                or item.get("file_path")
                or item.get("path")
                or ""
            )
            name = os.path.basename(path) if path else ""
            if not name:
                name = (
                    item.get("extra_info")
                    or item.get("name")
                    or item.get("file_name")
                    or ""
                )
                if name:
                    name = os.path.basename(name)
            if name and name not in materials:
                materials.append(name)
    return materials, None

def _scan_material_files(template_path: str):
    if not template_path:
        return []
    exts = set(_ALL_MEDIA_EXTS)
    skip_names = {
        "draft_cover.jpg",
        "cover.png",
        "cover.jpg"
    }
    results = []
    seen = set()
    search_dirs = [
        template_path,
        os.path.join(template_path, "materialResources"),
        os.path.join(template_path, "audio"),
        os.path.join(template_path, "video"),
    ]
    for base in search_dirs:
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for name in files:
                if name in skip_names:
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in exts and name not in seen:
                    seen.add(name)
                    results.append(name)
    return results


def _extract_template_material_entries(template_path: str) -> list[dict]:
    data, err = _load_draft_content(template_path)
    if err or not isinstance(data, dict):
        materials, _texts, _extract_err = _extract_template_info(template_path)
        return [{'name': name, 'source': None} for name in materials]

    entries = []
    seen = set()
    mats = data.get('materials', {})
    for media_type in ('videos', 'images', 'audios'):
        for item in mats.get(media_type, []) or []:
            if not isinstance(item, dict):
                continue
            path = (
                item.get('path')
                or item.get('file_path')
                or item.get('file_Path')
                or item.get('material_path')
                or ''
            )
            name = os.path.basename(path) if path else ''
            if not name:
                name = (
                    item.get('material_name')
                    or item.get('name')
                    or item.get('file_name')
                    or item.get('extra_info')
                    or ''
                )
                if name:
                    name = os.path.basename(name)
            if not name or name in seen:
                continue
            seen.add(name)
            entries.append({'name': name, 'source': media_type})
    return entries


def _template_material_matches_type(name: str, source: str | None, replace_type: str, replace_strategy: str | None = None) -> bool:
    ext = os.path.splitext(name or '')[1].lower()
    if replace_strategy == 'sequence':
        if source:
            return source == 'videos'
        return ext in _VIDEO_EXTS
    if replace_type == 'image':
        if source == 'audios':
            return False
        if source == 'images':
            return True
        return ext in _IMAGE_EXTS
    if replace_type == 'video':
        if source:
            return source == 'videos'
        return ext in _VIDEO_EXTS
    if replace_type == 'audio':
        if source:
            return source == 'audios'
        return ext in _AUDIO_EXTS
    if source in ('videos', 'images', 'audios'):
        return True
    return ext in _ALL_MEDIA_EXTS


def _filter_replaceable_template_materials(
    template_path: str,
    replace_materials: bool,
    replace_audios: bool,
    replace_type: str,
    replace_strategy: str,
) -> list[str]:
    items = []
    for entry in _extract_template_material_entries(template_path):
        name = entry.get('name') or ''
        source = entry.get('source')
        is_audio = source == 'audios'
        if is_audio and not replace_audios:
            continue
        if not is_audio and not replace_materials:
            continue
        if _template_material_matches_type(name, source, replace_type, replace_strategy):
            items.append(name)
    return items


def _extract_template_info(template_path):
    materials = []
    texts = []
    data, err = _load_draft_content(template_path)
    if err or not isinstance(data, dict):
        meta_materials, meta_err = _extract_materials_from_meta(template_path)
        if meta_err:
            draft_logger.warning("draft_inspect: meta_parse_failed err=%s", meta_err)
        if meta_materials:
            draft_logger.info(
                "draft_inspect: fallback_meta materials=%s sample=%s",
                len(meta_materials),
                meta_materials[:10]
            )
            return meta_materials, texts, None
        scan_materials = _scan_material_files(template_path)
        if scan_materials:
            draft_logger.info(
                "draft_inspect: fallback_scan materials=%s sample=%s",
                len(scan_materials),
                scan_materials[:10]
            )
            return scan_materials, texts, None
        return materials, texts, err

    mats = data.get('materials', {})
    for media_type in ('videos', 'images', 'audios'):
        for item in mats.get(media_type, []) or []:
            if not isinstance(item, dict):
                continue
            path = (
                item.get('path')
                or item.get('file_path')
                or item.get('file_Path')
                or item.get('material_path')
                or ''
            )
            name = os.path.basename(path) if path else ''
            if not name:
                name = (
                    item.get('material_name')
                    or item.get('name')
                    or item.get('file_name')
                    or item.get('extra_info')
                    or ''
                )
                if name:
                    name = os.path.basename(name)
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

    if not materials:
        meta_materials, meta_err = _extract_materials_from_meta(template_path)
        if meta_err:
            draft_logger.warning("draft_inspect: meta_parse_failed err=%s", meta_err)
        if meta_materials:
            materials = meta_materials

    sample = materials[:10]
    draft_logger.info(
        "draft_inspect: materials=%s texts=%s sample=%s",
        len(materials),
        len(texts),
        sample
    )
    return materials, texts, None


def _list_media_files_for_strategy(root_path, replace_type='both'):
    if not root_path or not os.path.exists(root_path):
        return []
    exts_img = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    exts_vid = ('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v')
    exts_aud = ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')
    files = []
    for walk_root, _dirs, filenames in os.walk(root_path):
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if replace_type == 'image' and ext not in exts_img:
                continue
            if replace_type == 'video' and ext not in exts_vid:
                continue
            if replace_type == 'audio' and ext not in exts_aud:
                continue
            if replace_type == 'both' and ext not in (exts_img + exts_vid + exts_aud):
                continue
            files.append(os.path.join(walk_root, filename))
    return files


def _list_strategy_subfolders(root_path):
    if not root_path or not os.path.exists(root_path):
        return []
    folders = []
    for name in os.listdir(root_path):
        full_path = os.path.join(root_path, name)
        if os.path.isdir(full_path):
            folders.append(full_path)
    folders.sort()
    return folders


def _normalize_strategy_name(name):
    return os.path.splitext(name or '')[0].strip().lower()


def _validate_mix_materials_root(materials_root, replace_strategy, replace_type, material_names):
    if not materials_root:
        return '请先选择素材目录。'
    if not os.path.exists(materials_root):
        return '当前素材目录不存在，请重新选择。'

    if replace_strategy == 'mix':
        if not _list_media_files_for_strategy(materials_root, replace_type):
            return '当前素材池里还没有可用素材，请先放入图片或视频后再生成。'
        return None

    subfolders = _list_strategy_subfolders(materials_root)
    if replace_strategy == 'group':
        if not subfolders:
            return '按组精准替换需要在总目录下准备子文件夹，例如 01、02、03。'
        if len(subfolders) < len(material_names):
            return f'按组精准替换至少需要 {len(material_names)} 个子文件夹，当前只有 {len(subfolders)} 个。'
        empty_folders = [
            os.path.basename(folder)
            for folder in subfolders[:len(material_names)]
            if not _list_media_files_for_strategy(folder, replace_type)
        ]
        if empty_folders:
            return f'这些分组目录里还没有可用素材：{", ".join(empty_folders)}。'
        return None

    if replace_strategy == 'partition':
        if not subfolders:
            return '分区混剪需要先建立分区子文件夹，再开始生成。'
        folder_map = {
            _normalize_strategy_name(os.path.basename(folder)): folder
            for folder in subfolders
        }
        required_names = [_normalize_strategy_name(name) for name in material_names]
        missing = [name for name in required_names if name not in folder_map]
        if missing:
            return f'分区目录名还没对上草稿槽位：缺少 {", ".join(missing)}。请直接使用槽位名建目录，通常去掉扩展名即可。'
        empty_folders = [
            name for name in required_names
            if not _list_media_files_for_strategy(folder_map[name], replace_type)
        ]
        if empty_folders:
            return f'这些分区目录里还没有可用素材：{", ".join(empty_folders)}。'
        return None

    return None


def _validate_mix_materials_root_v2(materials_root, replace_strategy, replace_type, material_names):
    if not materials_root:
        return '请先选择素材目录。'
    if not os.path.exists(materials_root):
        return '当前素材目录不存在，请重新选择。'

    if replace_strategy == 'mix':
        if not _list_media_files_for_strategy(materials_root, replace_type):
            return '当前素材池里还没有可用素材，请先放入图片或视频后再生成。'
        return None

    subfolders = _list_strategy_subfolders(materials_root)
    if replace_strategy == 'group':
        if not subfolders:
            return '按组精准替换需要在总目录下准备子文件夹，例如 01、02、03。'
        if len(subfolders) < len(material_names):
            return f'按组精准替换至少需要 {len(material_names)} 个子文件夹，当前只有 {len(subfolders)} 个。'
        empty_folders = [
            os.path.basename(folder)
            for folder in subfolders[:len(material_names)]
            if not _list_media_files_for_strategy(folder, replace_type)
        ]
        if empty_folders:
            return f'这些分组目录里还没有可用素材：{", ".join(empty_folders)}。'
        return None

    if replace_strategy == 'sequence':
        if not subfolders:
            return '槽位拼接混剪需要在总目录下按槽位准备子文件夹，例如 01、02、03。'
        if len(subfolders) < len(material_names):
            return f'槽位拼接混剪至少需要 {len(material_names)} 个槽位子文件夹，当前只有 {len(subfolders)} 个。'
        empty_folders = [
            os.path.basename(folder)
            for folder in subfolders[:len(material_names)]
            if not _list_media_files_for_strategy(folder, 'video')
        ]
        if empty_folders:
            return f'这些槽位目录里还没有可用视频素材：{", ".join(empty_folders)}。'
        return None

    if replace_strategy == 'partition':
        if not subfolders:
            return '分区混剪需要先建立分区子文件夹，再开始生成。'
        folder_map = {
            _normalize_strategy_name(os.path.basename(folder)): folder
            for folder in subfolders
        }
        required_names = [_normalize_strategy_name(name) for name in material_names]
        missing = [name for name in required_names if name not in folder_map]
        if missing:
            return f'分区目录名还没对上草稿槽位：缺少 {", ".join(missing)}。请直接使用槽位名建目录，通常去掉扩展名即可。'
        empty_folders = [
            name for name in required_names
            if not _list_media_files_for_strategy(folder_map[name], replace_type)
        ]
        if empty_folders:
            return f'这些分区目录里还没有可用素材：{", ".join(empty_folders)}。'
        return None

    return None

def _extract_template_tracks(template_path):
    data, err = _load_draft_content(template_path)
    if err or not isinstance(data, dict):
        return [], {}, err
    try:
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
        draft_logger.info("draft_inspect: tracks=%s", len(tracks))
        return tracks, seg_map, None
    except Exception:
        return [], {}, '解析失败'


def _auth_error(message, code=401):
    return jsonify({'ok': False, 'error': message}), code


def _deprecated_json(payload, status=200):
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers['X-VideoFactory-Deprecated'] = 'true'
    return resp


def _legacy_template_payload(**extra):
    payload = {
        "deprecated": True,
        "message": "template_id endpoints are legacy; prefer local draft_path flows",
    }
    payload.update(extra)
    return payload


def _legacy_template_endpoints_enabled() -> bool:
    return bool(current_app.config.get("LEGACY_TEMPLATE_ENDPOINTS_ENABLED", True))


def _legacy_template_endpoint_disabled_response():
    return _deprecated_json(
        _legacy_template_payload(
            ok=False,
            message="legacy template endpoints are disabled; use local draft_path flows",
        ),
        410,
    )


def _resolve_draft_path(draft_path=None, template_id=None):
    if draft_path:
        return draft_path, None, None
    if template_id:
        template = TemplateModel.query.get(template_id)
        if not template:
            return None, None, 'template_not_found'
        return template.template_path, template.id, None
    return None, None, 'missing'


def _ai_key_to_dict(key: UserApiKey):
    provider = key.provider
    return {
        "id": key.id,
        "provider_id": key.provider_id,
        "provider_code": provider.provider_code if provider else "",
        "provider_name": provider.provider_name if provider else "",
        "key_name": key.key_name,
        "endpoint": key.endpoint,
        "base_url": key.base_url,
        "is_active": bool(key.is_active),
        "masked_key": key.masked_key(),
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "usage_count": key.usage_count or 0,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "updated_at": key.updated_at.isoformat() if key.updated_at else None,
    }


def _parse_extra_body(value):
    if not value:
        return None
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def _load_task_progress_payload(task: Task) -> dict:
    if not task or not task.progress:
        return {}
    try:
        data = json.loads(task.progress)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _store_task_progress_payload(task: Task, payload: dict) -> None:
    task.progress = json.dumps(payload or {}, ensure_ascii=False)


def _cleanup_expired_desktop_claims(user_id: int) -> None:
    cutoff = _now() - timedelta(minutes=_DESKTOP_TASK_CLAIM_TTL_MINUTES)
    claimed_tasks = Task.query.filter(
        Task.user_id == user_id,
        Task.status == "claimed",
        Task.updated_at < cutoff,
    ).all()
    if not claimed_tasks:
        return
    quota = get_or_create_quota(user_id)
    changed = False
    for task in claimed_tasks:
        payload = _load_task_progress_payload(task)
        amount = _clamp_int(payload.get("quota_amount", 0), 0, 0, 9999)
        if amount > 0 and not payload.get("claim_released"):
            quota.remaining = (quota.remaining or 0) + amount
            changed = True
            db.session.add(UserQuotaLog(
                user_id=user_id,
                change=amount,
                reason="refund",
                project_id=str(task.id),
                remaining_after=quota.remaining,
            ))
        task.status = "failed"
        task.error_msg = "desktop claim expired"
        payload["claim_released"] = True
        payload["claim_release_reason"] = "expired"
        _store_task_progress_payload(task, payload)
        db.session.add(task)
    if changed:
        db.session.add(quota)
    db.session.commit()


def _finalize_desktop_task_claim(task: Task, user_id: int, success: bool, error_msg: str = "") -> dict:
    payload = _load_task_progress_payload(task)
    amount = _clamp_int(payload.get("quota_amount", 0), 0, 0, 9999)
    action_key = str(payload.get("action_key") or "generate_batch").strip() or "generate_batch"
    quota = get_or_create_quota(user_id)

    if success:
        if not payload.get("quota_applied") and amount > 0:
            quota.total_generated = (quota.total_generated or 0) + amount
            db.session.add(UserQuotaLog(
                user_id=user_id,
                change=-amount,
                reason=action_key,
                project_id=str(task.id),
                remaining_after=quota.remaining,
            ))
            payload["quota_applied"] = True
        task.status = "success"
        task.error_msg = None
    else:
        if not payload.get("claim_released") and amount > 0:
            quota.remaining = (quota.remaining or 0) + amount
            db.session.add(UserQuotaLog(
                user_id=user_id,
                change=amount,
                reason='refund',
                project_id=str(task.id),
                remaining_after=quota.remaining,
            ))
            payload["claim_released"] = True
        task.status = "failed"
        task.error_msg = error_msg or task.error_msg

    payload["completed_at"] = _now().isoformat()
    _store_task_progress_payload(task, payload)
    db.session.add(quota)
    db.session.add(task)
    db.session.commit()
    return quota_to_dict(quota)


def get_auth_user(require_admin=False):
    token = extract_bearer_token(request)
    if _should_use_remote_auth():
        if not token:
            return None, _auth_error('missing auth token', 401)
        try:
            user, error_msg, error_code = _fetch_remote_user_by_token(token)
        except Exception as exc:
            cached_user = _get_cached_remote_user(token)
            if cached_user:
                if require_admin and cached_user.role != 'admin':
                    return None, _auth_error('admin permission required', 403)
                return cached_user, None
            return None, _auth_error(f'remote auth unavailable: {exc}', 503)
        if error_msg:
            return None, _auth_error(error_msg, error_code or 401)
        _store_cached_remote_user(token, user)
        if require_admin and user.role != 'admin':
            return None, _auth_error('admin permission required', 403)
        return user, None
    user, _token_obj, err = validate_token(token)
    if err == 'missing':
        return None, _auth_error('missing auth token', 401)
    if err == 'invalid':
        return None, _auth_error('invalid token', 401)
    if err == 'expired':
        return None, _auth_error('token expired', 401)
    if err == 'user_missing':
        return None, _auth_error('user not found', 401)
    if require_admin and user.role != 'admin':
        return None, _auth_error('admin permission required', 403)
    return user, None


def _remote_desktop_task_claim(task_id: str, action_key: str, quota_amount: int = 1):
    token = extract_bearer_token(request)
    if not token:
        return None, _auth_error('missing auth token', 401)
    try:
        response = call_remote_api(
            "/api/desktop/task-claim",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
            json_data={
                "task_id": task_id,
                "action_key": action_key,
                "quota_amount": quota_amount,
            },
            timeout=15,
        )
        data = response.json()
    except Exception as exc:
        return None, jsonify({'ok': False, 'error': f'remote task claim failed: {exc}'}), 503
    if not response.ok or not isinstance(data, dict) or not data.get("ok"):
        status_code = response.status_code or 502
        return None, jsonify(data if isinstance(data, dict) else {'ok': False, 'error': 'remote task claim failed'}), status_code
    return token, None


def _remote_desktop_task_complete(task_id: str, token: str, success: bool, error_msg: str = ""):
    if not token:
        return
    try:
        call_remote_api(
            "/api/desktop/task-complete",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
            json_data={
                "task_id": task_id,
                "success": bool(success),
                "error_msg": error_msg or "",
            },
            timeout=15,
        )
    except Exception as exc:
        logging.warning("remote desktop task complete failed: %s", exc)

def browse_folder_thread():
    return _select_local_directory()

def browse_file_thread():
    return _select_local_file()

@api_bp.route('/browse-folder', methods=['POST'])
def browse_folder():
    result = {}
    def target():
        nonlocal result
        result['folder'] = browse_folder_thread()
    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if result.get('folder') is None:
        return _desktop_dialog_unavailable_response()
    return jsonify({'folder': result.get('folder', '')})


@api_bp.route('/path/exists', methods=['POST'])
def path_exists():
    data = request.get_json(silent=True) or {}
    path = (data.get('path') or '').strip()
    if not path:
        return jsonify({'ok': False, 'error': 'path is required'}), 400
    return jsonify({
        'ok': True,
        'exists': os.path.exists(path),
        'is_dir': os.path.isdir(path),
        'is_file': os.path.isfile(path),
    })

@api_bp.route('/browse-file', methods=['POST'])
def browse_file():
    result = {}
    def target():
        nonlocal result
        result['file'] = browse_file_thread()
    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if result.get('file') is None:
        return _desktop_dialog_unavailable_response()
    return jsonify({'file': result.get('file', '')})

@api_bp.route('/net-assets/start', methods=['POST'])
def net_assets_start():
    return jsonify({
        'ok': False,
        'error': '第三方平台素材采集已下线，不再对用户开放。'
    }), 410


@api_bp.route('/hotlist', methods=['GET'])
def hotlist():
    user, err = get_auth_user()
    if err:
        return err
    platform = (request.args.get('platform') or 'douyin').strip().lower()
    allowed_ids = {
        "weibo", "zhihu", "baidu", "douyin", "toutiao", "hupu", "tieba", "douban", "thepaper", "ifeng",
        "tencent-hot", "bilibili-hot-search", "iqiyi-hot-ranklist", "qqvideo-tv-hotsearch", "zaobao",
        "cankaoxiaoxi", "sputniknewscn", "kaopu", "cls-telegraph", "cls-hot", "wallstreetcn-news",
        "jin10", "gelonghui", "fastbull-express", "mktnews-flash", "36kr-quick", "ithome",
        "chongbuluo-latest", "juejin", "sspai", "coolapk", "v2ex-share", "chongbuluo-hot",
        "nowcoder", "freebuf", "solidot", "pcbeta-windows11", "github-trending-today", "hackernews",
        "producthunt", "steam", "xueqiu-hotstock"
    }
    if platform not in allowed_ids:
        return jsonify({'ok': False, 'error': '不支持的平台'}), 400
    base = "https://api.lolimi.cn/API/hot/entire"
    try:
        params = {"id": platform}
        res = requests.get(base, params=params, timeout=20)
        if res.status_code != 200:
            return jsonify({'ok': False, 'error': f"接口错误: {res.text[:200]}"})
        data = res.json()
        if data.get("status") in ("error", "fail"):
            return jsonify({'ok': False, 'error': '接口返回失败'}), 400
        items = data.get("items") or []
        updated_ts = data.get("updatedTime") or data.get("timestamp")
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            extra = item.get("extra") or {}
            hot_raw = item.get("hot") or item.get("heat") or item.get("score") or item.get("view") or extra.get("hot") or extra.get("heat") or extra.get("score") or extra.get("view") or "-"
            if isinstance(hot_raw, str):
                hot_raw = hot_raw.replace("热度", "").strip()
            time_raw = item.get("time") or item.get("date") or extra.get("time") or extra.get("date") or updated_ts or ""
            if isinstance(time_raw, (int, float)):
                ts = float(time_raw)
                if ts > 1e12:
                    ts = ts / 1000.0
                try:
                    time_raw = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    time_raw = str(time_raw)
            elif not isinstance(time_raw, str):
                time_raw = str(time_raw)
            normalized.append({
                "title": item.get("title") or item.get("name") or item.get("topic") or "-",
                "hot": hot_raw,
                "author": item.get("author") or item.get("user") or item.get("owner") or item.get("source") or extra.get("author") or extra.get("user") or extra.get("owner") or extra.get("source") or "-",
                "time": time_raw.replace(" 时间:", "").strip()
            })
        return jsonify({'ok': True, 'items': normalized})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@api_bp.route('/draft/inspect', methods=['POST'])
def draft_inspect_api():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json() or {}
    draft_path = data.get('draft_path')
    if not draft_path:
        return jsonify({'ok': False, 'error': '缺少草稿路径'}), 400
    draft_logger.info("draft_inspect: request path=%s", draft_path)
    materials, texts, err1 = _extract_template_info(draft_path)
    tracks, seg_map, err2 = _extract_template_tracks(draft_path)
    if err1 or err2:
        if materials or texts:
            draft_logger.warning("draft_inspect: partial_ok err=%s", err1 or err2)
        else:
            draft_logger.warning("draft_inspect: failed err=%s", err1 or err2)
            return jsonify({'ok': False, 'error': err1 or err2}), 400
    return jsonify({
        'ok': True,
        'materials': materials,
        'texts': texts,
        'tracks': tracks,
        'segment_counts': seg_map
    })


@api_bp.route('/draft/timeline-summary', methods=['POST'])
def draft_timeline_summary_api():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    draft_path = (data.get('draft_path') or '').strip()
    if not draft_path:
        return jsonify({'ok': False, 'error': '缺少草稿路径'}), 400

    draft_data, load_err = _load_draft_content(draft_path)
    if load_err or not isinstance(draft_data, dict):
        return jsonify({'ok': False, 'error': load_err or '草稿读取失败'}), 400

    tracks = draft_data.get('tracks', []) or []
    materials = draft_data.get('materials', {}) or {}
    video_map = {item.get('id'): item for item in (materials.get('videos') or []) if isinstance(item, dict)}
    text_map = {item.get('id'): item for item in (materials.get('texts') or []) if isinstance(item, dict)}

    def _us_to_sec(value):
        try:
            return round(float(value or 0) / 1_000_000.0, 3)
        except Exception:
            return 0.0

    video_tracks = []
    main_track_segments = []
    text_segments = []
    first_video_track = None

    for idx, track in enumerate(tracks):
        ttype = track.get('type')
        if ttype not in ('video', 'text'):
            continue
        name = track.get('name') or track.get('track_name') or f'{ttype}_{idx}'
        segments = track.get('segments') or []
        if ttype == 'video':
            total_duration = 0.0
            for seg_idx, seg in enumerate(segments, start=1):
                target = seg.get('target_timerange') or {}
                total_duration += _us_to_sec(target.get('duration'))
            video_tracks.append({
                'name': name,
                'segment_count': len(segments),
                'total_duration': round(total_duration, 3),
            })
            if first_video_track is None and segments:
                first_video_track = (name, segments)
        elif ttype == 'text':
            for seg_idx, seg in enumerate(segments, start=1):
                target = seg.get('target_timerange') or {}
                mat = text_map.get(seg.get('material_id')) or {}
                text_segments.append({
                    'index': seg_idx,
                    'track_name': name,
                    'start': _us_to_sec(target.get('start')),
                    'duration': _us_to_sec(target.get('duration')),
                    'text': (mat.get('recognize_text') or mat.get('content') or '')[:80],
                })

    if first_video_track:
        track_name, segments = first_video_track
        for seg_idx, seg in enumerate(segments, start=1):
            target = seg.get('target_timerange') or {}
            source = seg.get('source_timerange') or {}
            mat = video_map.get(seg.get('material_id')) or {}
            main_track_segments.append({
                'index': seg_idx,
                'track_name': track_name,
                'material_name': mat.get('material_name') or os.path.basename((mat.get('path') or '').strip()) or '',
                'source_path': mat.get('path') or mat.get('file_path') or '',
                'timeline_start': _us_to_sec(target.get('start')),
                'timeline_duration': _us_to_sec(target.get('duration')),
                'source_start': _us_to_sec(source.get('start')),
                'source_duration': _us_to_sec(source.get('duration')),
            })

    return jsonify({
        'ok': True,
        'draft_name': os.path.basename(draft_path.rstrip("\\/")) or draft_path,
        'video_tracks': video_tracks,
        'main_track_segments': main_track_segments,
        'text_segments': text_segments,
    })


@api_bp.route('/drafts/timeline-summary', methods=['POST'])
def drafts_timeline_summary_api():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    draft_paths = data.get('draft_paths') or []
    if not isinstance(draft_paths, list) or not draft_paths:
        return jsonify({'ok': False, 'error': '缺少草稿列表'}), 400

    items = []
    for raw in draft_paths:
        draft_path = (raw or '').strip()
        if not draft_path:
            continue
        entry = {
            'draft_path': draft_path,
            'draft_name': os.path.basename(draft_path.rstrip("\\/")) or draft_path,
        }
        draft_data, load_err = _load_draft_content(draft_path)
        if load_err or not isinstance(draft_data, dict):
            entry['ok'] = False
            entry['error'] = load_err or '草稿读取失败'
            items.append(entry)
            continue

        video_tracks = [track for track in (draft_data.get('tracks') or []) if isinstance(track, dict) and track.get('type') == 'video']
        text_tracks = [track for track in (draft_data.get('tracks') or []) if isinstance(track, dict) and track.get('type') == 'text']
        entry['ok'] = True
        entry['video_track_count'] = len(video_tracks)
        entry['text_track_count'] = len(text_tracks)
        entry['main_track_segments'] = len((video_tracks[0].get('segments') or [])) if video_tracks else 0
        items.append(entry)

    return jsonify({'ok': True, 'items': items})


@api_bp.route('/draft/split-main-track', methods=['POST'])
def draft_split_main_track_api():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    draft_path = (data.get('draft_path') or '').strip()
    output_dir = (data.get('output_dir') or '').strip() or (get_drafts_folder() or '').strip()
    track_name = (data.get('track_name') or '').strip()
    save_path = output_dir or 'skip'
    if False and not save_path:
        return jsonify({'ok': False, 'error': '请先设置采集保存目录，或在当前页面手动填写保存目录'}), 400

    try:
        segment_seconds = float(data.get('segment_seconds') or 0)
    except Exception:
        segment_seconds = 0

    if not draft_path:
        return jsonify({'ok': False, 'error': '缺少草稿路径'}), 400
    if segment_seconds <= 0:
        return jsonify({'ok': False, 'error': '请输入有效的分割时长'}), 400
    if not output_dir:
        return jsonify({'ok': False, 'error': '未找到导出目录'}), 400

    draft_data, load_err = _load_draft_content(draft_path)
    if load_err or not isinstance(draft_data, dict):
        return jsonify({'ok': False, 'error': load_err or '草稿读取失败'}), 400

    tracks = draft_data.get('tracks', []) or []
    target_track = None
    for track in tracks:
        if not isinstance(track, dict) or track.get('type') != 'video':
            continue
        name = (track.get('name') or track.get('track_name') or '').strip()
        if track_name and name == track_name:
            target_track = track
            break
        if not track_name and target_track is None:
            target_track = track
    if not target_track:
        return jsonify({'ok': False, 'error': '未找到可分割的主轨道'}), 400

    video_materials = {}
    for item in (draft_data.get('materials', {}) or {}).get('videos', []) or []:
        if isinstance(item, dict) and item.get('id'):
            video_materials[item['id']] = item

    def _us_to_seconds(value, default=0.0):
        try:
            return max(0.0, float(value or 0) / 1_000_000.0)
        except Exception:
            return default

    def _resp_ok(resp):
        if resp is None:
            return False
        if hasattr(resp, 'ok'):
            try:
                return bool(resp.ok)
            except Exception:
                return False
        if hasattr(resp, 'success'):
            try:
                return bool(resp.success)
            except Exception:
                return False
        return False

    def _resp_message(resp, fallback=''):
        if resp is None:
            return fallback
        return getattr(resp, 'message', None) or fallback

    canvas = draft_data.get('canvas_config') or {}
    width = int(canvas.get('width') or draft_data.get('width') or 1080)
    height = int(canvas.get('height') or draft_data.get('height') or 1920)
    fps = int(draft_data.get('fps') or 30)

    from app.services.jianying_service import JianYingService

    save_path = str(runtime_path("user_data", "mcp_cache_split"))
    os.makedirs(save_path, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    svc = JianYingService(save_path=save_path, output_path=output_dir)
    ffmpeg, _ffmpeg_source = find_ffmpeg_with_source()
    image_clip_cache = {}
    draft_basename = os.path.basename(draft_path.rstrip('/\\')) or uuid.uuid4().hex[:8]
    draft_name = f"split_main_{draft_basename}"
    create_resp = svc.create_draft(draft_name=draft_name, width=width, height=height, fps=fps)
    if not create_resp.ok:
        return jsonify({'ok': False, 'error': create_resp.message or '创建新草稿失败'}), 500
    draft_id = ((create_resp.data or {}).get('draft_id') or '').strip()
    if not draft_id:
        return jsonify({'ok': False, 'error': '创建新草稿后未返回 draft_id'}), 500

    create_track_resp = svc.create_track(draft_id, 'video', track_name or 'main')
    if create_track_resp.ok and create_track_resp.data and create_track_resp.data.get('track_name'):
        export_track_name = create_track_resp.data.get('track_name')
    else:
        export_track_name = track_name or 'main'

    generated = 0
    results = []
    timeline_cursor = 0.0

    for segment_index, segment in enumerate(target_track.get('segments', []) or [], start=1):
        if not isinstance(segment, dict):
            continue
        material = video_materials.get(segment.get('material_id')) or {}
        src = (material.get('path') or material.get('file_path') or '').strip()
        if not src or not os.path.exists(src):
            results.append({
                'segment_index': segment_index,
                'ok': False,
                'error': '素材文件不存在',
                'source': src,
            })
            continue

        source_timerange = segment.get('source_timerange') or {}
        target_timerange = segment.get('target_timerange') or {}
        source_start = _us_to_seconds(source_timerange.get('start'))
        source_duration = _us_to_seconds(source_timerange.get('duration'))
        target_duration = _us_to_seconds(target_timerange.get('duration'))
        total_duration = source_duration or target_duration
        if total_duration <= 0:
            total_duration = segment_seconds

        ext = os.path.splitext(src)[1].lower()
        is_image = ext in _IMAGE_EXTS
        prepared_src = src
        if is_image:
            if not ffmpeg:
                results.append({
                    'segment_index': segment_index,
                    'ok': False,
                    'error': '未找到 ffmpeg，无法处理图片片段',
                    'source': src,
                })
                continue
            cache_key = (src, round(total_duration, 3))
            prepared_src = image_clip_cache.get(cache_key) or ''
            if not prepared_src or not os.path.exists(prepared_src):
                prepared_src = os.path.join(
                    save_path,
                    "material",
                    f"{os.path.splitext(os.path.basename(src))[0]}_{uuid.uuid4().hex[:8]}.mp4",
                )
                os.makedirs(os.path.dirname(prepared_src), exist_ok=True)
                try:
                    import subprocess
                    subprocess.run(
                        [
                            ffmpeg, '-y',
                            '-loop', '1',
                            '-t', f'{total_duration:.3f}',
                            '-i', src,
                            '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p',
                            prepared_src,
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    image_clip_cache[cache_key] = prepared_src
                except Exception as exc:
                    results.append({
                        'segment_index': segment_index,
                        'ok': False,
                        'error': f'图片片段转视频失败: {exc}',
                        'source': src,
                    })
                    continue

        speed = segment.get('speed')
        volume = segment.get('volume', 1.0)
        change_pitch = bool(segment.get('change_pitch', False))
        clip_settings = segment.get('clip_settings') or segment.get('clip')
        if not isinstance(clip_settings, dict):
            clip_settings = None

        piece_offset = 0.0
        piece_index = 0
        while piece_offset < total_duration - 1e-6:
            piece_duration = min(segment_seconds, total_duration - piece_offset)
            piece_index += 1
            target_range = f"{timeline_cursor:.3f}s-{piece_duration:.3f}s"
            source_range = None
            if source_duration > 0:
                source_range = f"{source_start + piece_offset:.3f}s-{piece_duration:.3f}s"
            elif is_image:
                source_range = f"{piece_offset:.3f}s-{piece_duration:.3f}s"

            add_resp = svc.add_video_segment(
                draft_id,
                prepared_src,
                target_range,
                source_timerange=source_range,
                speed=speed,
                volume=volume,
                change_pitch=change_pitch,
                clip_settings=clip_settings,
                track_name=export_track_name,
            )
            if _resp_ok(add_resp):
                generated += 1
                results.append({
                    'segment_index': segment_index,
                    'piece_index': piece_index,
                    'ok': True,
                    'target_range': target_range,
                    'source_range': source_range or '',
                })
            else:
                results.append({
                    'segment_index': segment_index,
                    'piece_index': piece_index,
                    'ok': False,
                    'error': _resp_message(add_resp, '添加片段失败'),
                })
            piece_offset += piece_duration
            timeline_cursor += piece_duration

    export_resp = svc.export_draft(draft_id, jianying_draft_path=output_dir)
    if not export_resp.ok:
        return jsonify({
            'ok': False,
            'error': export_resp.message or '导出新草稿失败',
            'generated': generated,
            'results': results,
        }), 500

    export_data = export_resp.data or {}
    return jsonify({
        'ok': True,
        'draft_name': export_data.get('draft_name') or draft_name,
        'output': export_data.get('output') or output_dir,
        'generated': generated,
        'track_name': export_track_name,
        'segment_seconds': segment_seconds,
        'results': results,
    })

@api_bp.route('/site-settings', methods=['GET', 'POST'])
def site_settings():
    field_aliases = {
        'site_name': ('site_name',),
        'site_title': ('site_title', 'title'),
        'site_keywords': ('site_keywords', 'keywords'),
        'site_description': ('site_description', 'description'),
        'official_site_url': ('official_site_url', 'site_url'),
        'download_url': ('download_url',),
        'official_logo_url': ('official_logo_url', 'logo_url'),
        'workspace_title': ('workspace_title',),
        'workspace_subtitle': ('workspace_subtitle',),
        'login_title': ('login_title',),
        'login_subtitle': ('login_subtitle',),
        'locked_title': ('locked_title',),
        'locked_subtitle': ('locked_subtitle',),
        'admin_title': ('admin_title',),
        'user_agreement_title': ('user_agreement_title',),
        'user_agreement_content': ('user_agreement_content',),
        'privacy_agreement_title': ('privacy_agreement_title',),
        'privacy_agreement_content': ('privacy_agreement_content',),
        'contact_entries': ('contact_entries',),
    }
    if request.method == 'POST':
        user, err = get_auth_user(require_admin=True)
        if err:
            return err

        _ = user
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = request.form.to_dict(flat=True)

        updates = {}
        for target_key, aliases in field_aliases.items():
            value = None
            for alias in aliases:
                if alias in payload:
                    value = payload.get(alias)
                    break
            if value is None:
                continue
            if target_key == 'contact_entries':
                if isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                        value = parsed if isinstance(parsed, list) else [value]
                    except Exception:
                        value = [item.strip() for item in value.splitlines() if item.strip()]
                elif isinstance(value, list):
                    value = [str(item or '').strip() for item in value if str(item or '').strip()]
                else:
                    value = []
                value = json.dumps(value, ensure_ascii=False)
            updates[target_key] = value

        if updates:
            set_configs(updates)
        settings = get_site_settings()
        return jsonify({'ok': True, 'success': True, 'settings': settings, **settings})
    return jsonify(get_site_settings())


@api_bp.route('/runtime/online-status', methods=['GET'])
def runtime_online_status():
    return jsonify({
        'ok': True,
        'server_time': _now().isoformat(),
        'official_origin': _get_official_site_origin(),
    })


@api_bp.route('/runtime/usage-policy', methods=['GET'])
def runtime_usage_policy():
    return jsonify({
        'ok': True,
        'policy': _build_usage_policy(),
    })


@api_bp.route('/runtime/device-fingerprint', methods=['GET'])
def runtime_device_fingerprint():
    if not _is_local_runtime_request():
        return jsonify({'ok': False, 'error': 'not available'}), 404
    payload = _get_native_device_fingerprint_payload()
    return jsonify({
        'ok': True,
        **payload,
    })


@api_bp.route('/runtime/local-state', methods=['GET', 'POST', 'DELETE'])
def runtime_local_state():
    guard = _require_local_runtime_same_origin()
    if guard:
        return guard

    if request.method == 'GET':
        key = request.args.get('key', '')
        try:
            value = get_runtime_local_state_value(key)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        return jsonify({'ok': True, 'key': key, 'value': value})

    if request.method == 'DELETE':
        key = request.args.get('key', '')
        try:
            remove_runtime_local_state_value(key)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        return jsonify({'ok': True, 'key': key, 'removed': True})

    data = request.get_json(silent=True) or {}
    key = data.get('key', '')
    try:
        set_runtime_local_state_value(key, data.get('value', ''))
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'key': key})


@api_bp.route('/desktop/task-claim', methods=['POST'])
def desktop_task_claim():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    task_id = str(data.get('task_id') or '').strip()
    action_key = str(data.get('action_key') or 'generate_batch').strip() or 'generate_batch'
    quota_amount = _clamp_int(data.get('quota_amount', 1), 1, 1, 9999)
    if not task_id:
        return jsonify({'ok': False, 'error': 'task_id required'}), 400

    _cleanup_expired_desktop_claims(user.id)

    existing = Task.query.get(task_id)
    if existing:
        if existing.user_id != user.id:
            return jsonify({'ok': False, 'error': 'task_id already exists'}), 409
        if existing.status == 'claimed':
            quota = get_or_create_quota(user.id)
            return jsonify({'ok': True, 'task_id': task_id, 'claimed': True, **quota_to_dict(quota)})
        return jsonify({'ok': False, 'error': 'task claim already finished'}), 409

    quota = get_or_create_quota(user.id)
    if (quota.remaining or 0) < quota_amount:
        return jsonify({'ok': False, 'error': 'quota exhausted', **quota_to_dict(quota)}), 403

    quota.remaining = max(0, (quota.remaining or 0) - quota_amount)
    task = Task(
        id=task_id,
        user_id=user.id,
        template_id=None,
        status='claimed',
    )
    _store_task_progress_payload(task, {
        'action_key': action_key,
        'quota_amount': quota_amount,
        'claimed_at': _now().isoformat(),
        'quota_applied': False,
        'claim_released': False,
    })
    db.session.add(task)
    db.session.add(quota)
    db.session.commit()
    return jsonify({'ok': True, 'task_id': task_id, 'claimed': True, **quota_to_dict(quota)})


@api_bp.route('/desktop/task-complete', methods=['POST'])
def desktop_task_complete():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    task_id = str(data.get('task_id') or '').strip()
    if not task_id:
        return jsonify({'ok': False, 'error': 'task_id required'}), 400
    task = Task.query.get(task_id)
    if not task or task.user_id != user.id:
        return jsonify({'ok': False, 'error': 'task not found'}), 404

    if task.status in {'success', 'finished'}:
        quota = get_or_create_quota(user.id)
        return jsonify({'ok': True, 'task_id': task_id, 'status': task.status, **quota_to_dict(quota)})

    success = bool(data.get('success', True))
    quota_payload = _finalize_desktop_task_claim(
        task=task,
        user_id=user.id,
        success=success,
        error_msg=str(data.get('error_msg') or ''),
    )
    return jsonify({'ok': True, 'task_id': task_id, 'status': task.status, **quota_payload})


@api_bp.route('/runtime-features', methods=['GET'])
def runtime_features():
    raw_flags = _raw_runtime_flags()
    features = _effective_runtime_features()
    return jsonify({
        'ok': True,
        'features': features,
        'raw_flags': raw_flags,
        'flags': {key: meta["flag"] for key, meta in _FEATURE_FLAG_META.items()},
        'labels': {key: meta["label"] for key, meta in _FEATURE_FLAG_META.items()},
        'requirements': {
            'duo': ['DUO_FEATURES_ENABLED'],
            'openclaw': ['OPENCLAW_FEATURES_ENABLED'],
            'manga': ['MANGA_FEATURES_ENABLED'],
        },
    })


@api_bp.route('/workspace/settings', methods=['GET', 'POST'])
def workspace_settings():
    user, err = get_auth_user()
    if err:
        return err

    def _build_workspace_settings_payload(user_config: dict) -> dict:
        workspace = user_config.get('workspace') or {}
        services = user_config.get('services') or {}
        legacy_openclaw = user_config.get('openclaw') or {}
        export_cfg = user_config.get('export') or {}
        paths_cfg = user_config.get('paths') or {}
        openclaw_cfg = services.get('openclaw') or legacy_openclaw
        return {
            'workspace': {
                'strategy': workspace.get('strategy') or 'simple',
                'auto_discover': workspace.get('auto_discover', True),
                'auto_load_last_draft': workspace.get('auto_load_last_draft', False),
            },
            'paths': {
                'material_folder': get_material_folder() or '',
                'drafts_folder': get_drafts_folder() or '',
                'default_export_dir': export_cfg.get('default_dir') or '',
                'audio_folder': paths_cfg.get('audio_folder') or '',
            },
            'services': {
                'openclaw': {
                    'base_url': openclaw_cfg.get('base_url') or '',
                    'token': openclaw_cfg.get('token') or '',
                },
            },
        }

    if request.method == 'GET':
        user_config = load_user_config(user.id)
        return jsonify({
            'ok': True,
            'settings': _build_workspace_settings_payload(user_config)
        })

    data = request.get_json(silent=True) or {}
    user_config_patch = {}

    workspace = data.get('workspace') or {}
    if workspace:
        user_config_patch['workspace'] = {
            'strategy': (workspace.get('strategy') or 'simple').strip() or 'simple',
            'auto_discover': bool(workspace.get('auto_discover', True)),
            'auto_load_last_draft': bool(workspace.get('auto_load_last_draft', False)),
        }

    paths = data.get('paths') or {}
    if paths:
        material_folder = (paths.get('material_folder') or '').strip()
        drafts_folder = (paths.get('drafts_folder') or '').strip()
        default_export_dir = (paths.get('default_export_dir') or '').strip()
        audio_folder = (paths.get('audio_folder') or '').strip()
        if 'material_folder' in paths:
            set_config('material_folder', material_folder)
        if 'drafts_folder' in paths:
            set_config('drafts_folder', drafts_folder)
        if 'default_export_dir' in paths:
            user_config_patch['export'] = {'default_dir': default_export_dir}
        if 'audio_folder' in paths:
            user_config_patch['paths'] = {}
            if 'audio_folder' in paths:
                user_config_patch['paths']['audio_folder'] = audio_folder

    services = data.get('services') or {}
    if services:
        services_patch = {}
        openclaw_cfg = services.get('openclaw') or {}
        if openclaw_cfg:
            try:
                normalized_openclaw_base = _normalize_http_service_url(
                    openclaw_cfg.get('base_url') or '',
                    allow_localhost=True,
                )
            except ValueError as exc:
                return jsonify({'ok': False, 'error': str(exc)}), 400
            openclaw_payload = {
                'base_url': normalized_openclaw_base,
                'token': (openclaw_cfg.get('token') or '').strip(),
            }
            services_patch['openclaw'] = openclaw_payload
            # Keep legacy top-level key for existing AI manga logic during migration.
            user_config_patch['openclaw'] = openclaw_payload
        if services_patch:
            user_config_patch['services'] = services_patch

    config = save_user_config(user.id, user_config_patch, merge=True) if user_config_patch else load_user_config(user.id)
    return jsonify({'ok': True, 'config': config, 'settings': _build_workspace_settings_payload(config)})

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
        return jsonify({'folder': get_material_folder()})


@api_bp.route('/drafts-folder', methods=['GET', 'POST'])
def drafts_folder():
    if request.method == 'POST':
        folder = request.form.get('folder', '')
        set_config('drafts_folder', folder)
        return jsonify({'success': True})
    else:
        return jsonify({'folder': get_drafts_folder()})


@api_bp.route('/drafts/discover', methods=['GET'])
def discover_drafts_api():
    user, err = get_auth_user()
    if err:
        return err
    limit = int(request.args.get('limit') or 30)
    limit = max(1, min(limit, 100))
    return jsonify({
        'ok': True,
        'roots': discover_draft_roots(),
        'drafts': list_local_drafts(limit=limit),
        'configured_root': get_drafts_folder() or '',
    })


@api_bp.route('/split', methods=['POST'])
def split_videos_api():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json() or {}
    source_path = data.get('source_path')
    output_dir = data.get('output_dir')
    mode = data.get('mode', 'fixed')  # fixed | scene | count | silence | subtitle
    segment_seconds = float(data.get('segment_seconds') or 0)
    split_count = int(data.get('split_count') or 0)
    threshold = float(data.get('threshold') or 30.0)
    min_scene_len = int(data.get('min_scene_len') or 15)
    silence_db = float(data.get('silence_db') or -35.0)
    min_silence = float(data.get('min_silence') or 0.4)
    subtitle_path = data.get('subtitle_path')
    build_draft = bool(data.get('build_draft'))
    draft_output = data.get('draft_output')

    if not source_path or not output_dir:
        return jsonify({'ok': False, 'error': '\u0073ource_path \u548c output_dir \u4e0d\u80fd\u4e3a\u7a7a'}), 400

    files = list_video_files(source_path)
    if not files:
        return jsonify({'ok': False, 'error': '\u672a\u627e\u5230\u53ef\u5206\u5272\u7684\u89c6\u9891\u6587\u4ef6'}), 400

    def _calc_split_stats(parts: List[str]):
        durations = []
        for seg_path in parts:
            info = probe_video_info(seg_path)
            dur = info.get("duration")
            if dur and dur > 0:
                durations.append(float(dur))
        if not durations:
            return {"count": len(parts), "min_duration": None, "max_duration": None}
        return {
            "count": len(parts),
            "min_duration": min(durations),
            "max_duration": max(durations),
        }

    results = []
    for fpath in files:
        base = os.path.splitext(os.path.basename(fpath))[0]
        out_dir = os.path.join(output_dir, base)
        try:
            if mode == 'scene':
                scenes = detect_scenes(fpath, threshold=threshold, min_scene_len=min_scene_len)
                parts = split_by_scenes(fpath, out_dir, scenes)
            elif mode == 'count':
                if split_count <= 0:
                    return jsonify({'ok': False, 'error': '\u0063ount \u6a21\u5f0f\u9700\u8981 split_count'}), 400
                parts = split_by_count(fpath, out_dir, split_count)
            elif mode == 'silence':
                silences = detect_silences(fpath, silence_db=silence_db, min_silence=min_silence)
                if not silences:
                    return jsonify({'ok': False, 'error': '\u672a\u68c0\u6d4b\u5230\u53ef\u7528\u7684\u9759\u97f3\u533a\u95f4'}), 400
                parts = split_by_silence(fpath, out_dir, silences)
            elif mode == 'subtitle':
                if not subtitle_path:
                    return jsonify({'ok': False, 'error': '\u0073ubtitle \u6a21\u5f0f\u9700\u8981 subtitle_path'}), 400
                parts = split_by_subtitles(fpath, out_dir, subtitle_path)
            else:
                if segment_seconds <= 0:
                    return jsonify({'ok': False, 'error': '\u0066ixed \u6a21\u5f0f\u9700\u8981 segment_seconds'}), 400
                parts = split_fixed_duration(fpath, out_dir, segment_seconds)

            draft_name = None
            if build_draft and parts:
                try:
                    from app.services.jianying_service import JianYingService
                    from app.utils.helpers import get_drafts_folder

                    svc = JianYingService()
                    info = probe_video_info(parts[0])
                    width = info.get('width') or 1080
                    height = info.get('height') or 1920
                    fps = info.get('fps') or 30
                    draft_id = uuid.uuid4().hex
                    svc.create_draft(draft_name=f"split_{draft_id}", width=width, height=height, fps=fps)
                    track = svc.create_track(draft_id, 'video', 'main')  # type: ignore
                    track_name = track.data.get('track_name') if track and getattr(track, 'ok', False) else 'main'
                    current = 0.0
                    for seg in parts:
                        seg_info = probe_video_info(seg)
                        dur = seg_info.get('duration') or segment_seconds or 1.0
                        timerange = f"{current}s-{dur}s"
                        svc.add_video_segment(draft_id, seg, timerange, track_name=track_name)
                        current += float(dur)
                    output_path = draft_output or get_drafts_folder()
                    if output_path:
                        export = svc.export_draft(draft_id, jianying_draft_path=output_path)
                        if export.ok and export.data:
                            draft_name = export.data.get('draft_name')
                except Exception as e:
                    draft_name = None
                    results.append({'file': fpath, 'error': f'draft build failed: {e}'})

            stats = _calc_split_stats(parts or [])
            results.append({'file': fpath, 'parts': parts, 'draft_name': draft_name, 'stats': stats})
        except Exception as e:
            results.append({'file': fpath, 'error': str(e)})

    return jsonify({'ok': True, 'results': results})

def _now():
    return datetime.utcnow()


def _china_now():
    return datetime.utcnow() + timedelta(hours=8)


def _china_day_bounds(now=None):
    local_now = now or _china_now()
    start_local = datetime(local_now.year, local_now.month, local_now.day)
    end_local = start_local + timedelta(days=1)
    offset = timedelta(hours=8)
    return start_local - offset, end_local - offset, start_local.strftime("%Y-%m-%d")


def _get_daily_checkin_reward():
    try:
        settings = get_license_settings()
        return max(1, int(settings.get("daily_checkin_reward", 1) or 1))
    except Exception:
        return 1


def _quota_reason_label(reason: str) -> str:
    return _QUOTA_REASON_LABELS.get(reason or "", reason or "积分变动")


def _serialize_quota_log(item: UserQuotaLog):
    return {
        "id": item.id,
        "change": item.change,
        "reason": item.reason,
        "reason_label": _quota_reason_label(item.reason),
        "project_id": item.project_id,
        "remaining_after": item.remaining_after,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _build_user_points_overview(user_id: int):
    quota = get_or_create_quota(user_id)
    start_utc, end_utc, local_day = _china_day_bounds()
    today_checkin = UserQuotaLog.query.filter(
        UserQuotaLog.user_id == user_id,
        UserQuotaLog.reason == "daily_checkin",
        UserQuotaLog.project_id == local_day,
    ).order_by(UserQuotaLog.id.desc()).first()
    if not today_checkin:
        today_checkin = UserQuotaLog.query.filter(
            UserQuotaLog.user_id == user_id,
            UserQuotaLog.reason == "daily_checkin",
            UserQuotaLog.created_at >= start_utc,
            UserQuotaLog.created_at < end_utc,
        ).order_by(UserQuotaLog.id.desc()).first()

    today_gain = db.session.query(func.sum(UserQuotaLog.change)).filter(
        UserQuotaLog.user_id == user_id,
        UserQuotaLog.created_at >= start_utc,
        UserQuotaLog.created_at < end_utc,
        UserQuotaLog.change > 0,
    ).scalar() or 0
    today_cost = db.session.query(func.sum(UserQuotaLog.change)).filter(
        UserQuotaLog.user_id == user_id,
        UserQuotaLog.created_at >= start_utc,
        UserQuotaLog.created_at < end_utc,
        UserQuotaLog.change < 0,
    ).scalar() or 0

    checkin_logs = UserQuotaLog.query.filter(
        UserQuotaLog.user_id == user_id,
        UserQuotaLog.reason == "daily_checkin",
    ).order_by(UserQuotaLog.created_at.desc(), UserQuotaLog.id.desc()).limit(30).all()
    unique_days = []
    seen_days = set()
    for item in checkin_logs:
        if item.project_id:
            day_key = item.project_id
        else:
            created_at = item.created_at or _now()
            day_key = (created_at + timedelta(hours=8)).strftime("%Y-%m-%d")
        if day_key in seen_days:
            continue
        seen_days.add(day_key)
        unique_days.append(day_key)

    streak_days = 0
    cursor = datetime.strptime(local_day, "%Y-%m-%d")
    unique_day_set = set(unique_days)
    while cursor.strftime("%Y-%m-%d") in unique_day_set:
        streak_days += 1
        cursor -= timedelta(days=1)

    recent_logs = UserQuotaLog.query.filter_by(user_id=user_id).order_by(
        UserQuotaLog.created_at.desc(),
        UserQuotaLog.id.desc(),
    ).limit(8).all()
    settings = get_license_settings()
    user = User.query.get(user_id)
    return {
        "quota": quota_to_dict(quota),
        "checked_in_today": bool(today_checkin),
        "today_gain": int(today_gain),
        "today_cost": abs(int(today_cost)),
        "checkin_reward": _get_daily_checkin_reward(),
        "streak_days": streak_days,
        "points_ratio": int(settings.get("points_ratio", 1) or 1),
        "recent_logs": [_serialize_quota_log(item) for item in recent_logs],
        "server_day": local_day,
        "invite": _build_user_invite_overview(user),
        "vip_rules": _build_vip_rules_summary(),
    }


def _bind_device_to_code(
    user: User,
    cdk: CdkCode,
    device_fingerprint: str,
    device_label: str = None,
    device_info: dict = None,
    auto_commit: bool = True,
):
    settings = get_license_settings()
    cooldown_hours = settings["transfer_cooldown_hours"]
    now = _now()
    active_bindings = LicenseBinding.query.filter_by(code_id=cdk.id, active=True).all()

    def _fingerprint_match(a: str, b: str) -> bool:
        if not a or not b:
            return False
        if a == b:
            return True
        if "|" in a and "|" in b:
            pa = set([x for x in a.split("|") if x])
            pb = set([x for x in b.split("|") if x])
            if len(pa) >= 2 and len(pb) >= 2:
                return len(pa & pb) >= 2
        return False

    for b in active_bindings:
        if _fingerprint_match(b.device_fingerprint, device_fingerprint):
            b.last_seen_at = now
            db.session.add(b)
            if auto_commit:
                db.session.commit()
            return True, None

    if len(active_bindings) >= (cdk.device_limit or 1):
        if (cdk.transfer_times_left or 0) <= 0:
            return False, "设备数量已达上限"
        if cdk.last_transfer_at:
            elapsed = (now - cdk.last_transfer_at).total_seconds() / 3600
            if elapsed < cooldown_hours:
                return False, f"请等待 {int(cooldown_hours - elapsed)} 小时"
        oldest = sorted(active_bindings, key=lambda x: x.bound_at or x.last_seen_at)[0]
        oldest.active = False
        oldest.unbound_at = now
        db.session.add(oldest)
        cdk.transfer_times_left = max(0, (cdk.transfer_times_left or 0) - 1)
        cdk.last_transfer_at = now
        db.session.add(cdk)

    binding = LicenseBinding(
        code_id=cdk.id,
        user_id=user.id,
        device_fingerprint=device_fingerprint,
        device_label=device_label,
        device_info=json.dumps(device_info, ensure_ascii=False) if isinstance(device_info, dict) else None,
        active=True,
        bound_at=now,
        last_seen_at=now,
    )
    db.session.add(binding)
    if auto_commit:
        db.session.commit()
    return True, None


@api_bp.route('/license/activate', methods=['POST'])
def license_activate():
    user, err = get_auth_user()
    if err:
        return err
    online_err = _require_remote_online('license_activate')
    if online_err:
        return online_err
    data = request.get_json() or {}
    code = (data.get('code') or '').strip().upper()
    device_fingerprint = (data.get('device_fingerprint') or '').strip()
    device_label = (data.get('device_label') or '').strip() or None
    device_info = data.get('device_info')
    limit_err = _enforce_rate_limit(
        "license_activate",
        limit=8,
        window_seconds=1800,
        identity_parts=[user.id, get_request_ip(request), code, device_fingerprint],
        user_id=user.id,
        details={"code": code},
    )
    if limit_err:
        return limit_err

    if not code or not device_fingerprint:
        audit_security_event("license_activate_invalid_payload", level="warning", request_obj=request, user_id=user.id, details={"code": code})
        return jsonify({'ok': False, 'error': '\u7f3a\u5c11\u8bbe\u5907\u6307\u7eb9'}), 400

    cdk = CdkCode.query.filter_by(code=code).first()
    if not cdk:
        audit_security_event("license_activate_missing_code", level="warning", request_obj=request, user_id=user.id, details={"code": code})
        return jsonify({'ok': False, 'error': '\u5361\u5bc6\u4e0d\u5b58\u5728'}), 404
    if cdk.status == 3:
        audit_security_event("license_activate_disabled_code", level="warning", request_obj=request, user_id=user.id, details={"code": code})
        return jsonify({'ok': False, 'error': '\u5361\u5bc6\u5df2\u7981\u7528'}), 400
    now = _now()
    if cdk.redeem_deadline and now > cdk.redeem_deadline:
        cdk.status = 2
        db.session.add(cdk)
        db.session.commit()
        return jsonify({'ok': False, 'error': '\u5df2\u8fc7\u671f'}), 400

    if cdk.activated_by and cdk.activated_by != user.id:
        audit_security_event("license_activate_conflict", level="warning", request_obj=request, user_id=user.id, details={"code": code, "activated_by": cdk.activated_by})
        return jsonify({'ok': False, 'error': '\u5df2\u88ab\u5176\u4ed6\u8d26\u53f7\u6fc0\u6d3b'}), 400

    settings = get_license_settings()

    try:
        if not cdk.activated_by:
            cdk.activated_by = user.id
            cdk.activated_at = now
            cdk.expire_at = now + timedelta(days=int(cdk.duration_days))
            cdk.status = 1
            cdk.transfer_times_left = cdk.transfer_times or 0
            db.session.add(cdk)

            quota = get_or_create_quota(user.id, auto_commit=False)
            if cdk.duration_days:
                _extend_vip_expire_at(quota, int(cdk.duration_days), now)
            if cdk.bonus_points:
                ratio = max(1, int(settings["points_ratio"] or 1))
                add_times = int(cdk.bonus_points or 0) * ratio
                if add_times:
                    quota.remaining = (quota.remaining or 0) + add_times
                    db.session.add(UserQuotaLog(
                        user_id=user.id,
                        change=add_times,
                        reason='license_activate',
                        project_id=code,
                        remaining_after=quota.remaining,
                    ))
            invite_rewards = _apply_invite_license_rewards(user, code, int(cdk.duration_days or 0))
            db.session.add(quota)
        else:
            invite_rewards = {"ok": False, "awards": {}}
            if cdk.expire_at and now > cdk.expire_at:
                cdk.status = 2
                db.session.add(cdk)
                db.session.commit()
                return jsonify({'ok': False, 'error': '\u5df2\u8fc7\u671f'}), 400

        ok, msg = _bind_device_to_code(
            user,
            cdk,
            device_fingerprint,
            device_label,
            device_info,
            auto_commit=False,
        )
        if not ok:
            db.session.rollback()
            audit_security_event("license_activate_bind_failed", level="warning", request_obj=request, user_id=user.id, details={"code": code, "reason": msg})
            return jsonify({'ok': False, 'error': msg}), 400

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    audit_security_event("license_activate_success", request_obj=request, user_id=user.id, details={"code": code})
    return jsonify({
        'ok': True,
        'code': code,
        'expire_at': cdk.expire_at.isoformat() if cdk.expire_at else None,
        'transfer_times_left': cdk.transfer_times_left or 0,
        'offline_hours': settings["offline_hours"],
        'invite_rewards': invite_rewards.get("awards") or {},
    })


@api_bp.route('/license/verify', methods=['POST'])
def license_verify():
    data = request.get_json() or {}
    code = (data.get('code') or '').strip().upper()
    device_fingerprint = (data.get('device_fingerprint') or '').strip()
    limit_err = _enforce_rate_limit(
        "license_verify",
        limit=20,
        window_seconds=1800,
        identity_parts=[get_request_ip(request), code, device_fingerprint],
        details={"code": code},
    )
    if limit_err:
        return limit_err
    if not code or not device_fingerprint:
        audit_security_event("license_verify_invalid_payload", level="warning", request_obj=request, details={"code": code})
        return jsonify({'ok': False, 'error': '缺少设备指纹'}), 400
    cdk = CdkCode.query.filter_by(code=code).first()
    if not cdk or cdk.status != 1:
        audit_security_event("license_verify_invalid_code", level="warning", request_obj=request, details={"code": code})
        return jsonify({'ok': False, 'error': '无效或未激活'}), 400
    now = _now()
    if cdk.expire_at and now > cdk.expire_at:
        cdk.status = 2
        db.session.add(cdk)
        db.session.commit()
        return jsonify({'ok': False, 'error': '已过期'}), 400
    binding = LicenseBinding.query.filter_by(code_id=cdk.id, device_fingerprint=device_fingerprint, active=True).first()
    if not binding:
        audit_security_event("license_verify_unbound_device", level="warning", request_obj=request, details={"code": code})
        return jsonify({'ok': False, 'error': '设备未绑定'}), 400
    binding.last_seen_at = now
    db.session.add(binding)
    db.session.commit()
    settings = get_license_settings()
    expires_at = now + timedelta(hours=settings["offline_hours"])
    payload = {
        "code": cdk.code,
        "user_id": cdk.activated_by,
        "device_fingerprint": device_fingerprint,
        "expire_at": cdk.expire_at.isoformat() if cdk.expire_at else None,
        "issued_at": now.isoformat(),
        "offline_hours": settings["offline_hours"],
        "transfer_times_left": cdk.transfer_times_left or 0,
    }
    token = sign_payload(payload)
    audit_security_event("license_verify_success", request_obj=request, user_id=cdk.activated_by, details={"code": code})
    return jsonify({
        "ok": True,
        "token": token,
        "expires_at": expires_at.isoformat(),
        "server_time": now.isoformat()
    })


@api_bp.route('/license/deactivate', methods=['POST'])
def license_deactivate():
    user, err = get_auth_user()
    if err:
        return err
    online_err = _require_remote_online('license_deactivate')
    if online_err:
        return online_err
    data = request.get_json() or {}
    code = (data.get('code') or '').strip().upper()
    device_fingerprint = (data.get('device_fingerprint') or '').strip()
    limit_err = _enforce_rate_limit(
        "license_deactivate",
        limit=6,
        window_seconds=1800,
        identity_parts=[user.id, get_request_ip(request), code, device_fingerprint],
        user_id=user.id,
        details={"code": code},
    )
    if limit_err:
        return limit_err
    if not code or not device_fingerprint:
        audit_security_event("license_deactivate_invalid_payload", level="warning", request_obj=request, user_id=user.id, details={"code": code})
        return jsonify({'ok': False, 'error': '缺少设备指纹'}), 400
    cdk = CdkCode.query.filter_by(code=code).first()
    if not cdk or cdk.activated_by != user.id:
        audit_security_event("license_deactivate_forbidden", level="warning", request_obj=request, user_id=user.id, details={"code": code})
        return jsonify({'ok': False, 'error': '无权限'}), 403
    binding = LicenseBinding.query.filter_by(code_id=cdk.id, device_fingerprint=device_fingerprint, active=True).first()
    if not binding:
        audit_security_event("license_deactivate_unbound_device", level="warning", request_obj=request, user_id=user.id, details={"code": code})
        return jsonify({'ok': False, 'error': '设备未绑定'}), 400
    binding.active = False
    binding.unbound_at = _now()
    db.session.add(binding)
    db.session.commit()
    audit_security_event("license_deactivate_success", request_obj=request, user_id=user.id, details={"code": code})
    return jsonify({'ok': True})


@api_bp.route('/license/status', methods=['GET'])
def license_status():
    user, err = get_auth_user()
    if err:
        return err
    codes = CdkCode.query.filter_by(activated_by=user.id).order_by(CdkCode.activated_at.desc()).all()
    items = []
    for c in codes:
        bindings = LicenseBinding.query.filter_by(code_id=c.id, active=True).all()
        items.append({
            "code": c.code,
            "card_type": c.card_type,
            "expire_at": c.expire_at.isoformat() if c.expire_at else None,
            "status": c.status,
            "transfer_times_left": c.transfer_times_left or 0,
            "device_limit": c.device_limit or 1,
            "devices": [{"fingerprint": b.device_fingerprint, "label": b.device_label} for b in bindings]
        })
    return jsonify({"ok": True, "items": items})


@api_bp.route('/admin/manga/stats', methods=['GET'])
def admin_manga_stats():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    from sqlalchemy import func
    total = MangaGenerationLog.query.count()
    active_users = db.session.query(func.count(func.distinct(MangaGenerationLog.user_id))).scalar() or 0
    total_cost = db.session.query(func.sum(UserQuotaLog.change)).filter(UserQuotaLog.reason == 'manga_generate').scalar() or 0
    total_cost = abs(int(total_cost))

    # trend last 14 days
    cutoff = datetime.utcnow() - timedelta(days=13)
    rows = db.session.query(func.date(MangaGenerationLog.created_at), func.count(MangaGenerationLog.id))         .filter(MangaGenerationLog.created_at >= cutoff)         .group_by(func.date(MangaGenerationLog.created_at))         .order_by(func.date(MangaGenerationLog.created_at)).all()
    trend = []
    for d, c in rows:
        trend.append({'date': str(d), 'count': c})

    return jsonify({
        'ok': True,
        'total_generate': total,
        'active_users': active_users,
        'total_cost': total_cost,
        'trend': trend,
    })


@api_bp.route('/admin/quota-summary', methods=['GET'])
def admin_quota_summary():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err

    total_remaining = db.session.query(func.coalesce(func.sum(UserQuota.remaining), 0)).scalar() or 0
    total_generated = db.session.query(func.coalesce(func.sum(UserQuota.total_generated), 0)).scalar() or 0
    quota_users = db.session.query(func.count(UserQuota.user_id)).scalar() or 0
    active_trial_users = db.session.query(func.count(UserQuota.user_id)).filter(UserQuota.remaining > 0).scalar() or 0
    total_users = db.session.query(func.count(User.id)).scalar() or 0
    total_invited_users = db.session.query(func.count(User.id)).filter(User.referrer_id.isnot(None)).scalar() or 0
    invite_reward_rows = db.session.query(
        UserQuotaLog.reason,
        func.coalesce(func.sum(UserQuotaLog.change), 0),
    ).filter(
        UserQuotaLog.reason.in_(('invite_referrer_reward', 'invite_invitee_reward'))
    ).group_by(UserQuotaLog.reason).all()
    total_invite_referrer_reward = 0
    total_invite_invitee_reward = 0
    for reason, total in invite_reward_rows:
        if reason == 'invite_referrer_reward':
            total_invite_referrer_reward = int(total or 0)
        elif reason == 'invite_invitee_reward':
            total_invite_invitee_reward = int(total or 0)
    total_invite_reward = total_invite_referrer_reward + total_invite_invitee_reward
    invite_settings = _get_invite_settings()

    return jsonify({
        'ok': True,
        'total_remaining': int(total_remaining),
        'total_generated': int(total_generated),
        'quota_users': int(quota_users),
        'active_trial_users': int(active_trial_users),
        'total_users': int(total_users),
        'total_invited_users': int(total_invited_users),
        'total_invite_reward': int(total_invite_reward),
        'total_invite_referrer_reward': int(total_invite_referrer_reward),
        'total_invite_invitee_reward': int(total_invite_invitee_reward),
        'default_user_quota': _get_default_user_quota_value(),
        'invite_referrer_reward': invite_settings['referrer_reward'],
        'invite_invitee_reward': invite_settings['invitee_reward'],
    })


@api_bp.route('/admin/license-settings', methods=['GET', 'POST'])
def admin_license_settings():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    if request.method == 'POST':
        data = request.get_json() or {}
        for key in (
            "license_offline_hours",
            "license_transfer_cooldown_hours",
            "license_code_length",
            "license_points_ratio",
            "manga_generate_cost",
            "daily_checkin_reward",
            "default_user_quota",
            "invite_referrer_reward",
            "invite_invitee_reward",
        ):
            if key in data:
                raw_value = data.get(key)
                if key == "default_user_quota":
                    raw_value = _clamp_int(raw_value, _get_default_user_quota_value(), 0, None)
                elif key in ("invite_referrer_reward", "invite_invitee_reward"):
                    raw_value = _clamp_int(raw_value, 0, 0, _MAX_INVITE_REWARD_PERCENT)
                set_config(key, str(raw_value))
    settings = get_license_settings()
    settings['manga_generate_cost'] = int(get_config('manga_generate_cost', '1') or 1)
    settings['default_user_quota'] = _get_default_user_quota_value()
    settings['invite_referrer_reward'] = _clamp_int(_safe_int_config('invite_referrer_reward', 3), 3, 0, _MAX_INVITE_REWARD_PERCENT)
    settings['invite_invitee_reward'] = _clamp_int(_safe_int_config('invite_invitee_reward', 2), 2, 0, _MAX_INVITE_REWARD_PERCENT)
    return jsonify({"ok": True, "settings": settings})


@api_bp.route('/license/card-types', methods=['GET'])
def license_card_types():
    rows = (
        db.session.query(
            CdkCode.card_type,
            func.max(CdkCode.duration_days).label('duration_days'),
            func.max(CdkCode.device_limit).label('device_limit'),
            func.max(CdkCode.transfer_times).label('transfer_times'),
            func.max(CdkCode.bonus_points).label('bonus_points'),
        )
        .filter(CdkCode.card_type.isnot(None))
        .group_by(CdkCode.card_type)
        .order_by(func.max(CdkCode.duration_days).asc(), CdkCode.card_type.asc())
        .all()
    )
    items = [
        {
            'card_type': row.card_type or '',
            'duration_days': int(row.duration_days or 0),
            'device_limit': int(row.device_limit or 1),
            'transfer_times': int(row.transfer_times or 0),
            'bonus_points': int(row.bonus_points or 0),
        }
        for row in rows
        if (row.card_type or '').strip()
    ]
    return jsonify({'ok': True, 'items': items})


@api_bp.route('/admin/cdk/batch', methods=['POST'])
def admin_cdk_batch():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    data = request.get_json() or {}
    card_type = (data.get("card_type") or "").strip()
    duration_days = int(data.get("duration_days") or 0)
    quantity = int(data.get("quantity") or 0)
    if not card_type or duration_days <= 0 or quantity <= 0:
        return jsonify({"ok": False, "error": "card_type、duration_days、quantity 不能为空且必须大于 0"}), 400
    bonus_points = int(data.get("bonus_points") or 0)
    device_limit = int(data.get("device_limit") or 1)
    transfer_times = int(data.get("transfer_times") or 0)
    redeem_days = int(data.get("redeem_days") or 0)
    template = CdkTemplate.query.filter_by(name=card_type).first()
    if template:
        template.duration_days = duration_days
        template.bonus_points = bonus_points
        template.device_limit = device_limit
        template.transfer_times = transfer_times
        template.redeem_days = redeem_days
    else:
        db.session.add(CdkTemplate(
            name=card_type,
            duration_days=duration_days,
            bonus_points=bonus_points,
            device_limit=device_limit,
            transfer_times=transfer_times,
            redeem_days=redeem_days,
        ))
    settings = get_license_settings()
    length = settings["code_length"]
    batch_id = uuid.uuid4().hex
    now = _now()
    redeem_deadline = (now + timedelta(days=redeem_days)) if redeem_days > 0 else None
    codes = []
    for _ in range(quantity):
        code = generate_cdk_code(length)
        cdk = CdkCode(
            code=code,
            card_type=card_type,
            duration_days=duration_days,
            bonus_points=bonus_points,
            device_limit=device_limit,
            transfer_times=transfer_times,
            transfer_times_left=transfer_times,
            status=0,
            created_by=user.id,
            batch_id=batch_id,
            redeem_deadline=redeem_deadline,
        )
        db.session.add(cdk)
        codes.append(code)
    db.session.commit()
    return jsonify({"ok": True, "batch_id": batch_id, "codes": codes})


@api_bp.route('/admin/cdk/templates', methods=['GET'])
def admin_cdk_templates():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    items = []
    for item in CdkTemplate.query.order_by(CdkTemplate.updated_at.desc(), CdkTemplate.id.desc()).all():
        items.append({
            "id": item.id,
            "name": item.name,
            "duration_days": item.duration_days,
            "bonus_points": item.bonus_points,
            "device_limit": item.device_limit,
            "transfer_times": item.transfer_times,
            "redeem_days": item.redeem_days,
        })
    return jsonify({"ok": True, "items": items})


@api_bp.route('/admin/cdk/list', methods=['GET'])
def admin_cdk_list():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    status = request.args.get("status")
    batch_id = request.args.get("batch_id")
    card_type = request.args.get("card_type")
    query = CdkCode.query
    if status is not None:
        try:
            query = query.filter_by(status=int(status))
        except Exception:
            pass
    if batch_id:
        query = query.filter_by(batch_id=batch_id)
    if card_type:
        query = query.filter_by(card_type=card_type)
    items = []
    for c in query.order_by(CdkCode.id.desc()).limit(500).all():
        items.append({
            "code": c.code,
            "card_type": c.card_type,
            "duration_days": c.duration_days,
            "bonus_points": c.bonus_points,
            "device_limit": c.device_limit,
            "transfer_times": c.transfer_times,
            "transfer_times_left": c.transfer_times_left,
            "status": c.status,
            "activated_by": c.activated_by,
            "activated_at": c.activated_at.isoformat() if c.activated_at else None,
            "expire_at": c.expire_at.isoformat() if c.expire_at else None,
            "batch_id": c.batch_id
        })
    return jsonify({"ok": True, "items": items})


@api_bp.route('/admin/cdk/extract', methods=['POST'])
def admin_cdk_extract():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    card_type = (data.get("card_type") or "").strip()
    quantity = _clamp_int(data.get("quantity") or 0, 0, 1, 500)
    if not card_type or quantity <= 0:
        return jsonify({"ok": False, "error": "请选择卡类型并填写提取数量"}), 400

    items = (
        CdkCode.query
        .filter(CdkCode.card_type == card_type, CdkCode.status == 0)
        .order_by(CdkCode.id.asc())
        .limit(quantity)
        .all()
    )
    return jsonify({
        "ok": True,
        "card_type": card_type,
        "requested": quantity,
        "count": len(items),
        "codes": [item.code for item in items],
    })


@api_bp.route('/admin/cdk/export', methods=['GET'])
def admin_cdk_export():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    status = request.args.get("status")
    batch_id = request.args.get("batch_id")
    card_type = request.args.get("card_type")
    query = CdkCode.query
    if status is not None:
        try:
            query = query.filter_by(status=int(status))
        except Exception:
            pass
    if batch_id:
        query = query.filter_by(batch_id=batch_id)
    if card_type:
        query = query.filter_by(card_type=card_type)

    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "code", "card_type", "duration_days", "bonus_points", "device_limit",
        "transfer_times", "transfer_times_left", "status", "activated_by",
        "activated_at", "expire_at", "batch_id"
    ])
    for c in query.order_by(CdkCode.id.desc()).all():
        writer.writerow([
            c.code,
            c.card_type,
            c.duration_days,
            c.bonus_points,
            c.device_limit,
            c.transfer_times,
            c.transfer_times_left,
            c.status,
            c.activated_by or "",
            c.activated_at.isoformat() if c.activated_at else "",
            c.expire_at.isoformat() if c.expire_at else "",
            c.batch_id or "",
        ])

    from flask import Response
    resp = Response(output.getvalue(), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = "attachment; filename=cdk_codes.csv"
    return resp


@api_bp.route('/admin/license/bindings', methods=['GET'])
def admin_license_bindings():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    code = request.args.get("code")
    user_id = request.args.get("user_id")
    query = LicenseBinding.query
    if code:
        cdk = CdkCode.query.filter_by(code=code).first()
        if cdk:
            query = query.filter_by(code_id=cdk.id)
        else:
            return jsonify({"ok": True, "items": []})
    if user_id:
        try:
            query = query.filter_by(user_id=int(user_id))
        except Exception:
            pass
    rows = query.order_by(LicenseBinding.id.desc()).limit(500).all()
    code_ids = {b.code_id for b in rows}
    code_map = {}
    if code_ids:
        for c in CdkCode.query.filter(CdkCode.id.in_(list(code_ids))).all():
            code_map[c.id] = c.code
    items = []
    for b in rows:
        items.append({
            "id": b.id,
            "code_id": b.code_id,
            "code": code_map.get(b.code_id),
            "user_id": b.user_id,
            "device_fingerprint": b.device_fingerprint,
            "device_label": b.device_label,
            "active": bool(b.active),
            "bound_at": b.bound_at.isoformat() if b.bound_at else None,
            "last_seen_at": b.last_seen_at.isoformat() if b.last_seen_at else None,
        })
    return jsonify({"ok": True, "items": items})


@api_bp.route('/admin/license/bindings/export', methods=['GET'])
def admin_license_bindings_export():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    code = request.args.get("code")
    user_id = request.args.get("user_id")
    query = LicenseBinding.query
    if code:
        cdk = CdkCode.query.filter_by(code=code).first()
        if cdk:
            query = query.filter_by(code_id=cdk.id)
        else:
            query = query.filter_by(code_id=-1)
    if user_id:
        try:
            query = query.filter_by(user_id=int(user_id))
        except Exception:
            pass
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    rows = query.order_by(LicenseBinding.id.desc()).all()
    code_ids = {b.code_id for b in rows}
    code_map = {}
    if code_ids:
        for c in CdkCode.query.filter(CdkCode.id.in_(list(code_ids))).all():
            code_map[c.id] = c.code
    writer.writerow(["id", "code_id", "code", "user_id", "device_fingerprint", "device_label", "active", "bound_at", "last_seen_at"])
    for b in rows:
        writer.writerow([
            b.id,
            b.code_id,
            code_map.get(b.code_id, ""),
            b.user_id,
            b.device_fingerprint,
            b.device_label or "",
            1 if b.active else 0,
            b.bound_at.isoformat() if b.bound_at else "",
            b.last_seen_at.isoformat() if b.last_seen_at else "",
        ])
    from flask import Response
    resp = Response(output.getvalue(), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = "attachment; filename=license_bindings.csv"
    return resp


@api_bp.route('/admin/users/search', methods=['GET'])
def admin_users_search():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    kw = (request.args.get("kw") or "").strip()
    try:
        page = max(1, int(request.args.get("page") or 1))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get("per_page") or get_config("admin_user_page_size", "20") or 20)
    except Exception:
        per_page = 20
    per_page = max(1, min(per_page, 50))
    if not kw:
        query = User.query
    else:
        query = User.query
        if kw.isdigit():
            query = query.filter(User.id == int(kw))
        else:
            like = f"%{kw}%"
            query = query.filter(or_(User.username.like(like), User.email.like(like)))
    total = query.count()
    pages = max(1, (total + per_page - 1) // per_page)
    if page > pages:
        page = pages
    users = query.order_by(User.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    user_ids = [item.id for item in users]
    quotas = {}
    referrer_map = {}
    invite_count_map = defaultdict(int)
    invite_reward_map = defaultdict(int)
    invitee_reward_map = defaultdict(int)
    if user_ids:
        quotas = {
            item.user_id: item
            for item in UserQuota.query.filter(UserQuota.user_id.in_(user_ids)).all()
        }
        for referrer_id, count in db.session.query(User.referrer_id, func.count(User.id)).filter(
            User.referrer_id.in_(user_ids)
        ).group_by(User.referrer_id).all():
            if referrer_id:
                invite_count_map[referrer_id] = int(count or 0)
        reward_rows = db.session.query(
            UserQuotaLog.user_id,
            UserQuotaLog.reason,
            func.coalesce(func.sum(UserQuotaLog.change), 0),
        ).filter(
            UserQuotaLog.user_id.in_(user_ids),
            UserQuotaLog.reason.in_(("invite_referrer_reward", "invite_invitee_reward")),
        ).group_by(UserQuotaLog.user_id, UserQuotaLog.reason).all()
        for user_id, reason, total in reward_rows:
            if reason == "invite_referrer_reward":
                invite_reward_map[user_id] = int(total or 0)
            elif reason == "invite_invitee_reward":
                invitee_reward_map[user_id] = int(total or 0)
        referrer_ids = [item.referrer_id for item in users if item.referrer_id]
        if referrer_ids:
            referrer_map = {
                item.id: item.username
                for item in User.query.filter(User.id.in_(list(set(referrer_ids)))).all()
            }
    items = []
    for u in users:
        quota = quotas.get(u.id)
        quota_data = quota_to_dict(quota) if quota else {
            "total_generated": 0,
            "remaining": 0,
            "vip_expire_at": None,
            "is_vip": False,
        }
        membership_label = "管理员" if u.role == "admin" else ("VIP会员" if quota_data["is_vip"] else "试用用户")
        items.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "ref_code": u.ref_code,
            "role": u.role,
            "remaining": quota_data["remaining"],
            "total_generated": quota_data["total_generated"],
            "vip_expire_at": quota_data["vip_expire_at"],
            "is_vip": quota_data["is_vip"],
            "membership_label": membership_label,
            "referrer_id": u.referrer_id,
            "referrer_username": referrer_map.get(u.referrer_id),
            "invite_count": invite_count_map.get(u.id, 0),
            "invite_reward_total": invite_reward_map.get(u.id, 0),
            "invitee_reward_total": invitee_reward_map.get(u.id, 0),
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })
    return jsonify({
        "ok": True,
        "items": items,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "pages": pages,
            "total": total,
        }
    })


@api_bp.route('/admin/logs', methods=['GET'])
def admin_logs_api():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    logs = read_generate_logs(limit=500)
    logs = list(reversed(logs))
    return jsonify({"ok": True, "items": logs})


@api_bp.route('/admin/security/overview', methods=['GET'])
def admin_security_overview():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err

    audit_items = []
    audit_path = _audit_log_path()
    if audit_path.exists():
        try:
            with open(audit_path, "r", encoding="utf-8") as handle:
                for line in handle.readlines()[-200:]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        if isinstance(payload, dict):
                            audit_items.append(payload)
                    except Exception:
                        continue
        except Exception:
            audit_items = []

    rate_limit_buckets = 0
    rate_limit_path = _rate_limit_path()
    if rate_limit_path.exists():
        try:
            with open(rate_limit_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
                if isinstance(payload, dict):
                    rate_limit_buckets = len(payload)
        except Exception:
            rate_limit_buckets = 0

    return jsonify({
        "ok": True,
        "audit_events": audit_items[-100:],
        "rate_limit_buckets": int(rate_limit_buckets),
        "audit_log_path": str(audit_path),
        "rate_limit_path": str(rate_limit_path),
    })


@api_bp.route('/admin/server/ops', methods=['GET'])
def admin_server_ops_overview():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err

    project_root = os.path.abspath(os.path.join(current_app.root_path, ".."))
    backup_root = os.path.join(project_root, "backups", "server")
    backup_items = []
    if os.path.isdir(backup_root):
        for name in sorted(os.listdir(backup_root), reverse=True):
            path = os.path.join(backup_root, name)
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
                backup_items.append({
                    "name": name,
                    "path": path,
                    "size": int(stat.st_size or 0),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except Exception:
                continue

    deploy_steps = [
        "1. 先创建服务端备份",
        "2. 同步变更文件到 current 目录",
        "3. 重启 videofactory-auth.service",
        "4. 验证 /api/runtime-features 返回 200",
        "5. 验证 /user 与 /admin 页面可打开",
    ]
    rollback_steps = [
        "1. 回退到上一份备份或上一版文件",
        "2. 重启 videofactory-auth.service",
        "3. 确认 systemctl is-active 为 active",
        "4. 再验域名与核心接口",
    ]

    return jsonify({
        "ok": True,
        "project_root": project_root,
        "backup_root": backup_root,
        "backups": backup_items[:20],
        "deploy_steps": deploy_steps,
        "rollback_steps": rollback_steps,
        "security": {
            "audit_log_path": str(_audit_log_path()),
            "rate_limit_path": str(_rate_limit_path()),
        },
    })


@api_bp.route('/admin/server/backup/create', methods=['POST'])
def admin_server_backup_create():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err

    project_root = os.path.abspath(os.path.join(current_app.root_path, ".."))
    script_path = os.path.join(project_root, "scripts", "server_backup.py")
    if not os.path.isfile(script_path):
        return jsonify({"ok": False, "error": "server_backup.py not found"}), 404

    include_env = bool((request.get_json(silent=True) or {}).get("include_env"))
    command = [sys.executable, script_path]
    if include_env:
        command.append("--include-env")
    try:
        result = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        return jsonify({
            "ok": False,
            "error": "backup script failed",
            "detail": (exc.stderr or exc.stdout or "").strip()[:800],
        }), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    archive_path = (result.stdout or "").strip().splitlines()
    archive_value = archive_path[-1].strip() if archive_path else ""
    return jsonify({
        "ok": True,
        "archive_path": archive_value,
        "include_env": include_env,
    })


@api_bp.route('/admin/license/binding/<int:binding_id>/disable', methods=['POST'])
def admin_license_binding_disable(binding_id):
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    b = LicenseBinding.query.get(binding_id)
    if not b:
        return jsonify({"ok": False, "error": "binding not found"}), 404
    b.active = False
    b.unbound_at = _now()
    db.session.add(b)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.route('/admin/license/binding/<int:binding_id>/unbind', methods=['POST'])
def admin_license_binding_unbind(binding_id):
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    b = LicenseBinding.query.get(binding_id)
    if not b:
        return jsonify({"ok": False, "error": "binding not found"}), 404
    b.active = False
    b.unbound_at = _now()
    db.session.add(b)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.route('/admin/cdk/<code>/disable', methods=['POST'])
def admin_cdk_disable(code):
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    cdk = CdkCode.query.filter_by(code=code).first()
    if not cdk:
        return jsonify({"ok": False, "error": "code not found"}), 404
    cdk.status = 3
    db.session.add(cdk)
    now = _now()
    for b in LicenseBinding.query.filter_by(code_id=cdk.id, active=True).all():
        b.active = False
        b.unbound_at = now
        db.session.add(b)
    db.session.commit()
    return jsonify({"ok": True})

@api_bp.route('/micro-adjust', methods=['POST'])
def micro_adjust_api():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json() or {}
    draft_path = (data.get('draft_path') or '').strip()
    export_path = (data.get('export_path') or '').strip() or None
    export_format = (data.get('export_format') or '').strip().lower() or None
    micro_adjust = data.get('micro_adjust') or {}

    if not draft_path:
        return jsonify({'ok': False, 'error': '缺少草稿路径'}), 400
    if not os.path.exists(draft_path):
        return jsonify({'ok': False, 'error': '草稿路径不存在'}), 400
    if not isinstance(micro_adjust, dict) or not micro_adjust:
        return jsonify({'ok': False, 'error': '缺少微调配置'}), 400
    if export_format not in (None, 'mp4', 'mov'):
        return jsonify({'ok': False, 'error': '不支持的导出格式'}), 400

    output_path = export_path or get_drafts_folder() or draft_path
    if output_path:
        os.environ["OUTPUT_PATH"] = output_path

    try:
        from app.services.jianying_service import JianYingService
        from app.tasks import _apply_mcp_effects
        svc = JianYingService()
        effects_config = {"video": {"micro_adjust": micro_adjust}}
        summary = _apply_mcp_effects(draft_path, effects_config, svc, None, export_format=export_format)
        return jsonify({
            'ok': True,
            'summary': summary,
            'draft_name': summary.get('draft_name'),
            'draft_id': summary.get('draft_id')
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': f'微调失败: {e}'}), 500


def _user_ai_root(user_id: int):
    base = get_material_folder()
    if not base:
        return None
    return os.path.join(base, f"user_{user_id}", "ai_generated")


def _guess_material_type(name: str):
    ext = os.path.splitext(name or '')[1].lower()
    if ext in ('.mp4', '.mov', '.m4v', '.avi', '.mkv'):
        return 'video'
    if ext in ('.mp3', '.wav', '.aac', '.m4a', '.ogg'):
        return 'audio'
    if ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'):
        return 'image'
    if ext in ('.txt',):
        return 'text'
    return 'file'


@api_bp.route('/materials/list', methods=['GET'])
def materials_list():
    user, err = get_auth_user()
    if err:
        return err
    folder = get_material_folder()
    if not folder or not os.path.exists(folder):
        return jsonify({'ok': True, 'folder': folder or '', 'items': []})
    items = []
    for name in os.listdir(folder):
        if name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov', '.mp3', '.wav', '.m4a', '.aac', '.txt')):
            items.append(name)
    items.sort()
    return jsonify({'ok': True, 'folder': folder, 'items': items})


@api_bp.route('/user/materials', methods=['GET'])
def user_materials():
    user, err = get_auth_user()
    if err:
        return err
    file_type = request.args.get('type')
    query = UserMaterial.query.filter_by(user_id=user.id)
    if file_type:
        query = query.filter_by(file_type=file_type)
    items = query.order_by(UserMaterial.id.desc()).limit(200).all()
    data = []
    for m in items:
        tags = []
        meta = {}
        if m.tags:
            try:
                tags = json.loads(m.tags)
            except Exception:
                tags = []
        if m.metadata_json:
            try:
                meta = json.loads(m.metadata_json)
            except Exception:
                meta = {}
        data.append({
            "id": m.id,
            "file_path": m.file_path,
            "file_type": m.file_type,
            "source": m.source,
            "tags": tags,
            "metadata": meta,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
    return jsonify({'ok': True, 'items': data})


@api_bp.route('/resource-exchange/list', methods=['GET'])
def resource_exchange_list():
    try:
        page = int(request.args.get('page') or 1)
    except Exception:
        page = 1
    approved_items = [
        _resource_exchange_post_to_dict(item)
        for item in ResourceExchangePost.query.filter_by(status='approved').all()
    ]
    approved_items.sort(key=_resource_exchange_sort_key, reverse=True)
    items = [_build_resource_exchange_public_item(item) for item in approved_items]
    payload = _paginate_items(items, page=page, per_page=_RESOURCE_EXCHANGE_PAGE_SIZE)
    return jsonify({'ok': True, 'items': payload['items'], 'pagination': payload['pagination']})


@api_bp.route('/resource-exchange/my-posts', methods=['GET'])
def resource_exchange_my_posts():
    user, err = get_auth_user()
    if err:
        return err
    items = [
        _resource_exchange_post_to_dict(item)
        for item in ResourceExchangePost.query.filter_by(user_id=user.id).all()
    ]
    items.sort(key=_resource_exchange_sort_key, reverse=True)
    return jsonify({'ok': True, 'items': items})


@api_bp.route('/resource-exchange/publish', methods=['POST'])
def resource_exchange_publish():
    user, err = get_auth_user()
    if err:
        return err
    payload, validation_error = _validate_resource_exchange_payload(request.get_json(silent=True) or {})
    if validation_error:
        return jsonify({'ok': False, 'error': validation_error}), 400

    start_utc, end_utc, _server_day = _china_day_bounds()
    today_posts = ResourceExchangePost.query.filter(
        ResourceExchangePost.user_id == user.id,
        ResourceExchangePost.created_at >= start_utc,
        ResourceExchangePost.created_at < end_utc,
    ).count()
    if today_posts:
        return jsonify({'ok': False, 'error': '每个用户每天只能发布一条资源互换信息'}), 400

    quota_payload = quota_to_dict(get_or_create_quota(user.id))
    now = _now()
    post = ResourceExchangePost(
        id=uuid.uuid4().hex[:12],
        user_id=user.id,
        username=user.username,
        membership_label=_resource_exchange_membership_label(user, quota_payload),
        membership_value=_resource_exchange_membership_value(user, quota_payload),
        project_name=payload['project_name'],
        project_intro=payload['project_intro'],
        contact=payload['contact'],
        status='pending',
        created_at=now,
        updated_at=now,
        review_reason='',
        reviewer_name='',
    )
    db.session.add(post)
    db.session.commit()
    return jsonify({'ok': True, 'item': _resource_exchange_post_to_dict(post)})


@api_bp.route('/admin/resource-exchange/posts', methods=['GET'])
def admin_resource_exchange_posts():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    try:
        page = int(request.args.get('page') or 1)
    except Exception:
        page = 1
    status = (request.args.get('status') or 'pending').strip().lower()
    keyword = (request.args.get('kw') or '').strip().lower()
    items = [_resource_exchange_post_to_dict(item) for item in ResourceExchangePost.query.all()]
    if status and status != 'all':
        items = [item for item in items if item['status'] == status]
    if keyword:
        items = [
            item for item in items
            if keyword in (item['username'] or '').lower()
            or keyword in (item['project_name'] or '').lower()
            or keyword in (item['project_intro'] or '').lower()
            or keyword in (item['contact'] or '').lower()
        ]
    items.sort(key=_resource_exchange_sort_key, reverse=True)
    payload = _paginate_items(items, page=page, per_page=_RESOURCE_EXCHANGE_PAGE_SIZE)
    return jsonify({'ok': True, 'items': payload['items'], 'pagination': payload['pagination']})


@api_bp.route('/admin/resource-exchange/<post_id>/review', methods=['POST'])
def admin_resource_exchange_review(post_id):
    admin, err = get_auth_user(require_admin=True)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip().lower()
    reason = (data.get('reason') or '').strip()
    if action not in ('approve', 'reject'):
        return jsonify({'ok': False, 'error': '审核动作无效'}), 400
    if action == 'reject' and not reason:
        return jsonify({'ok': False, 'error': '拒绝时必须填写原因'}), 400

    target = ResourceExchangePost.query.filter_by(id=str(post_id)).first()
    if not target:
        return jsonify({'ok': False, 'error': '发布记录不存在'}), 404

    reviewed_at = _now()
    target.status = 'approved' if action == 'approve' else 'rejected'
    target.reviewed_at = reviewed_at
    target.approved_at = reviewed_at if action == 'approve' else None
    target.review_reason = '' if action == 'approve' else reason
    target.reviewer_id = admin.id
    target.reviewer_name = admin.username
    target.updated_at = reviewed_at
    db.session.add(target)
    db.session.commit()
    return jsonify({'ok': True, 'item': _resource_exchange_post_to_dict(target)})


@api_bp.route('/materials/create-layout', methods=['POST'])
def materials_create_layout():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    draft_path = (data.get('draft_path') or '').strip()
    materials_root = (data.get('materials_root') or '').strip()
    strategy = (data.get('strategy') or 'group').strip() or 'group'
    slots = [str(item).strip() for item in (data.get('slots') or []) if str(item).strip()]

    if not draft_path:
        return jsonify({'ok': False, 'error': '缺少草稿路径'}), 400
    if not materials_root:
        return jsonify({'ok': False, 'error': '缺少素材根目录'}), 400

    draft_name = os.path.basename(os.path.normpath(draft_path))
    try:
        layout = _build_material_layout(materials_root, draft_name, strategy, slots)
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

    _append_assistant_log(user.id, 'materials_layout', {
        'draft_path': draft_path,
        'materials_root': materials_root,
        'strategy': strategy,
        'folders': layout.get('folders', []),
    })
    return jsonify({'ok': True, 'layout': layout})


@api_bp.route('/assistant/logs', methods=['GET'])
def assistant_logs():
    user, err = get_auth_user()
    if err:
        return err
    try:
        limit = max(1, min(int(request.args.get('limit') or 20), 100))
    except Exception:
        limit = 20
    return jsonify({'ok': True, 'items': _read_assistant_logs(user.id, limit=limit)})


@api_bp.route('/assistant/command/preview', methods=['POST'])
def assistant_command_preview():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    command = (data.get('command') or '').strip()
    context = data.get('context') or {}
    preview = _assistant_route_preview(command, context)
    _append_assistant_log(user.id, 'preview', {
        'command': command,
        'context': context,
        'preview': preview,
    })
    return jsonify(preview)


@api_bp.route('/assistant/command/execute', methods=['POST'])
def assistant_command_execute():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    command = (data.get('command') or '').strip()
    context = data.get('context') or {}
    confirmed = bool(data.get('confirmed', False))
    preview = _assistant_route_preview(command, context)
    if not preview.get('ok'):
        return jsonify(preview), 400
    if preview.get('requires_confirmation') and not confirmed:
        return jsonify({'ok': False, 'error': '该命令需要确认后才能执行', 'preview': preview}), 400

    action = (preview.get('client_action') or {}).get('type')
    if action and action not in _ASSISTANT_FREE_ACTIONS:
        return jsonify({
            'ok': False,
            'error': '当前智能助手只允许执行免费白名单动作，不能直接代执行扣次数功能。',
            'action': action,
            'preview': preview,
        }), 400
    response_payload = {
        'ok': True,
        'summary': preview.get('summary'),
        'client_action': preview.get('client_action'),
        'impact': preview.get('impact'),
    }

    if action == 'create_material_layout':
        client_action = preview.get('client_action') or {}
        draft_path = (client_action.get('draft_path') or '').strip()
        materials_root = (client_action.get('materials_root') or '').strip()
        strategy = (client_action.get('strategy') or 'group').strip() or 'group'
        slots = [str(item).strip() for item in (client_action.get('slots') or []) if str(item).strip()]
        if not draft_path or not materials_root:
            return jsonify({'ok': False, 'error': '创建素材目录前请先选草稿并指定素材目录', 'preview': preview}), 400
        draft_name = os.path.basename(os.path.normpath(draft_path))
        try:
            layout = _build_material_layout(materials_root, draft_name, strategy, slots)
        except Exception as exc:
            return jsonify({'ok': False, 'error': str(exc), 'preview': preview}), 400
        response_payload['layout'] = layout
        response_payload['client_action'] = {
            'type': 'material_layout_created',
            'layout': layout,
        }
    elif action == 'fill_text_template':
        text_count = int(((preview.get('client_action') or {}).get('text_count') or 0))
        total = max(1, min(text_count or 6, 20))
        template_lines = [f'第 {index} 段文字示例' for index in range(1, total + 1)]
        response_payload['template_lines'] = template_lines
        response_payload['client_action'] = {
            'type': 'fill_text_template',
            'lines': template_lines,
        }

    _append_assistant_log(user.id, 'execute', {
        'command': command,
        'context': context,
        'response': response_payload,
    })
    return jsonify(response_payload)


@api_bp.route('/manga/batch/set-duration', methods=['POST'])
def manga_batch_set_duration():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    material_ids = data.get('material_ids') or []
    duration = data.get('duration')
    if not material_ids or duration is None:
        return jsonify({'ok': False, 'error': '缺少素材ID或时长'}), 400
    items = UserMaterial.query.filter(UserMaterial.user_id == user.id, UserMaterial.id.in_(material_ids)).all()
    for item in items:
        meta = {}
        if item.metadata_json:
            try:
                meta = json.loads(item.metadata_json)
            except Exception:
                meta = {}
        meta['clip_duration'] = duration
        item.metadata_json = json.dumps(meta, ensure_ascii=False)
        db.session.add(item)
    db.session.commit()
    return jsonify({'ok': True, 'updated': len(items)})


@api_bp.route('/manga/batch/apply-effects', methods=['POST'])
def manga_batch_apply_effects():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    material_ids = data.get('material_ids') or []
    effects = data.get('effects') or {}
    if not material_ids:
        return jsonify({'ok': False, 'error': '缺少素材ID'}), 400
    items = UserMaterial.query.filter(UserMaterial.user_id == user.id, UserMaterial.id.in_(material_ids)).all()
    for item in items:
        meta = {}
        if item.metadata_json:
            try:
                meta = json.loads(item.metadata_json)
            except Exception:
                meta = {}
        meta['effects'] = effects
        item.metadata_json = json.dumps(meta, ensure_ascii=False)
        db.session.add(item)
    db.session.commit()
    return jsonify({'ok': True, 'updated': len(items)})


@api_bp.route('/manga/batch/export', methods=['POST'])
def manga_batch_export():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    material_ids = data.get('material_ids') or []
    duration = float(data.get('duration') or 3)
    if not material_ids:
        return jsonify({'ok': False, 'error': '缺少素材ID'}), 400

    ffmpeg, _ffmpeg_source = find_ffmpeg_with_source()
    if not ffmpeg:
        return jsonify({'ok': False, 'error': '未找到 ffmpeg 可执行文件'}), 400

    items = UserMaterial.query.filter(UserMaterial.user_id == user.id, UserMaterial.id.in_(material_ids)).all()
    out_root = os.path.join(get_user_material_dir(user.id), 'manga_exports')
    os.makedirs(out_root, exist_ok=True)
    added = 0
    for item in items:
        src = item.file_path
        if not src or not os.path.exists(src):
            continue
        name = os.path.splitext(os.path.basename(src))[0]
        out_path = os.path.join(out_root, f"{name}.mp4")
        if item.file_type == 'image':
            cmd = [ffmpeg, '-y', '-loop', '1', '-t', str(duration), '-i', src, '-vf', 'format=yuv420p', out_path]
        else:
            cmd = [ffmpeg, '-y', '-i', src, '-c', 'copy', out_path]
        try:
            import subprocess
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            mid = add_user_material(user.id, out_path, 'video', tags=['manga', 'batch_export'], source='openclaw', metadata_json={
                'exported_from': item.id,
                'exported_at': datetime.utcnow().isoformat(),
            })
            added += 1
        except Exception:
            continue
    return jsonify({'ok': True, 'added': added})


@api_bp.route('/export/drafts', methods=['POST'])
def export_drafts_api():
    user, err = get_auth_user()
    if err:
        return err
    quota = get_or_create_quota(user.id)
    if (quota.remaining or 0) < 1:
        return jsonify({'ok': False, 'error': '额度不足，无法继续批量导出。', **quota_to_dict(quota)}), 403
    data = request.get_json(silent=True) or {}
    draft_paths = data.get('draft_paths') or []
    output_dir = (data.get('output_dir') or '').strip() or get_drafts_folder()
    export_format = (data.get('export_format') or '').strip().lower() or None
    export_resolution = (data.get('export_resolution') or '').strip().lower() or None
    export_fps = data.get('export_fps')

    if not isinstance(draft_paths, list) or not draft_paths:
        return jsonify({'ok': False, 'error': '缺少草稿列表'}), 400
    if export_format not in (None, 'mp4', 'mov'):
        return jsonify({'ok': False, 'error': '不支持的导出格式'}), 400
    if export_resolution not in (None, '720p', '1080p', '4k'):
        return jsonify({'ok': False, 'error': '不支持的导出分辨率'}), 400
    if export_fps not in (None, ''):
        try:
            export_fps = int(export_fps)
        except Exception:
            return jsonify({'ok': False, 'error': '导出帧率无效'}), 400
        if export_fps <= 0 or export_fps > 240:
            return jsonify({'ok': False, 'error': '导出帧率超出范围'}), 400
    else:
        export_fps = None

    if not output_dir:
        return jsonify({'ok': False, 'error': '缺少导出目录'}), 400
    os.makedirs(output_dir, exist_ok=True)

    from app.services.jianying_service import JianYingService
    from app.tasks import _apply_mcp_effects

    svc = JianYingService(output_path=output_dir)
    os.environ["OUTPUT_PATH"] = output_dir
    results = []
    success_count = 0

    for raw_path in draft_paths:
        draft_path = (raw_path or '').strip()
        if not draft_path:
            continue
        item = {
            'draft_path': draft_path,
            'draft_name': os.path.basename(draft_path.rstrip("\\/")) or draft_path,
        }
        if not os.path.exists(draft_path):
            item['ok'] = False
            item['error'] = '草稿路径不存在'
            results.append(item)
            continue
        try:
            summary = None
            warnings = []
            exported_name = None
            try:
                summary = _apply_mcp_effects(
                    draft_path,
                    {},
                    svc,
                    None,
                    export_format=export_format,
                    export_resolution=export_resolution,
                    export_fps=export_fps,
                )
                exported_name = summary.get('draft_name')
                warnings = summary.get('warnings') or []
            except Exception as inner_exc:
                warnings.append(f'MCP 导出兼容失败，已回退为草稿复制导出: {inner_exc}')

            if not exported_name:
                safe_name = item['draft_name'] or f'draft_{uuid.uuid4().hex[:8]}'
                exported_name = f"{safe_name}_export_{uuid.uuid4().hex[:6]}"
                target_path = os.path.join(output_dir, exported_name)
                if os.path.exists(target_path):
                    shutil.rmtree(target_path)
                shutil.copytree(draft_path, target_path)

            item['ok'] = True
            item['exported_draft_name'] = exported_name
            item['warnings'] = warnings
            success_count += 1
        except Exception as exc:
            item['ok'] = False
            item['error'] = str(exc)
        results.append(item)

    if success_count > 0:
        quota.remaining = max(0, int(quota.remaining or 0) - 1)
        db.session.add(quota)
        db.session.add(UserQuotaLog(
            user_id=user.id,
            change=-1,
            reason='export_drafts',
            remaining_after=quota.remaining,
        ))
        db.session.commit()

    return jsonify({
        'ok': True,
        'output_dir': output_dir,
        'total': len(results),
        'success_count': success_count,
        'quota': quota_to_dict(quota),
        'results': results,
    })


@api_bp.route('/export/main-track', methods=['POST'])
def export_main_track_api():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    draft_path = (data.get('draft_path') or '').strip()
    output_dir = (data.get('output_dir') or '').strip()
    track_name = (data.get('track_name') or '').strip()

    if not draft_path or not output_dir:
        return jsonify({'ok': False, 'error': '缺少草稿路径或导出目录'}), 400
    if not os.path.exists(draft_path):
        return jsonify({'ok': False, 'error': '草稿路径不存在'}), 400

    ffmpeg, _source = find_ffmpeg_with_source()
    if not ffmpeg:
        return jsonify({'ok': False, 'error': '未找到 ffmpeg'}), 400

    draft_data, load_err = _load_draft_content(draft_path)
    if load_err or not isinstance(draft_data, dict):
        return jsonify({'ok': False, 'error': load_err or '草稿读取失败'}), 400

    os.makedirs(output_dir, exist_ok=True)
    tracks = draft_data.get('tracks', []) or []
    target_track = None
    for track in tracks:
        if track.get('type') != 'video':
            continue
        name = (track.get('name') or track.get('track_name') or '').strip()
        if track_name and name == track_name:
            target_track = track
            break
        if not track_name and not target_track:
            target_track = track
    if not target_track:
        return jsonify({'ok': False, 'error': '未找到可导出的主轨道'}), 400

    video_materials = {}
    for item in (draft_data.get('materials', {}) or {}).get('videos', []) or []:
        if isinstance(item, dict) and item.get('id'):
            video_materials[item['id']] = item

    def _us_to_seconds(value, default=0.0):
        try:
            return max(0.0, float(value or 0) / 1_000_000.0)
        except Exception:
            return default

    import subprocess
    results = []
    exported = 0
    base_name = os.path.basename(draft_path.rstrip("\\/")) or 'draft'

    for idx, segment in enumerate(target_track.get('segments', []) or [], start=1):
        if not isinstance(segment, dict):
            continue
        material = video_materials.get(segment.get('material_id'))
        src = (
            (material or {}).get('path')
            or (material or {}).get('file_path')
            or ''
        )
        if not src or not os.path.exists(src):
            results.append({'index': idx, 'ok': False, 'error': '素材文件不存在', 'source': src})
            continue

        source_timerange = segment.get('source_timerange') or {}
        target_timerange = segment.get('target_timerange') or {}
        start_sec = _us_to_seconds(source_timerange.get('start'))
        duration_sec = _us_to_seconds(source_timerange.get('duration')) or _us_to_seconds(target_timerange.get('duration'))
        if duration_sec <= 0:
            duration_sec = 1.0

        source_name = os.path.splitext(os.path.basename(src))[0]
        out_path = os.path.join(output_dir, f"{base_name}_main_{idx:03d}_{source_name}.mp4")
        ext = os.path.splitext(src)[1].lower()
        is_image = ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif')

        if is_image:
            cmd = [
                ffmpeg, '-y',
                '-loop', '1',
                '-t', f'{duration_sec:.3f}',
                '-i', src,
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                out_path,
            ]
        else:
            cmd = [
                ffmpeg, '-y',
                '-ss', f'{start_sec:.3f}',
                '-t', f'{duration_sec:.3f}',
                '-i', src,
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '18',
                '-c:a', 'aac',
                '-movflags', '+faststart',
                out_path,
            ]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            exported += 1
            results.append({
                'index': idx,
                'ok': True,
                'output': out_path,
                'duration': duration_sec,
                'source': src,
            })
        except Exception as exc:
            results.append({'index': idx, 'ok': False, 'error': str(exc), 'source': src})

    return jsonify({
        'ok': True,
        'track_name': target_track.get('name') or target_track.get('track_name') or 'video',
        'output_dir': output_dir,
        'exported': exported,
        'results': results,
    })


@api_bp.route('/manga/history', methods=['GET'])
def manga_history():
    user, err = get_auth_user()
    if err:
        return err
    limit = int(request.args.get('limit') or 50)
    logs = MangaGenerationLog.query.filter_by(user_id=user.id).order_by(MangaGenerationLog.id.desc()).limit(limit).all()
    items = []
    for log in logs:
        params = {}
        if log.params_json:
            try:
                params = json.loads(log.params_json)
            except Exception:
                params = {}
        items.append({
            'id': log.id,
            'project_id': log.project_id,
            'project_name': log.project_name,
            'mode': params.get('mode') or 'openclaw',
            'params': params,
            'draft_name': params.get('draft_name') or '',
            'draft_path': params.get('draft_path') or '',
            'workspace_root': params.get('workspace_root') or '',
            'scene_count': len(params.get('scenes') or []) if isinstance(params.get('scenes'), list) else 0,
            'first_material_id': log.first_material_id,
            'status': log.status,
            'error_msg': log.error_msg,
            'created_at': log.created_at.isoformat() if log.created_at else None,
        })
    return jsonify({'ok': True, 'items': items})


@api_bp.route('/manga/history/<int:log_id>/regenerate', methods=['POST'])
def manga_history_regenerate(log_id):
    user, err = get_auth_user()
    if err:
        return err
    log = MangaGenerationLog.query.get(log_id)
    if not log or log.user_id != user.id:
        return jsonify({'ok': False, 'error': '记录不存在'}), 404
    params = {}
    if log.params_json:
        try:
            params = json.loads(log.params_json)
        except Exception:
            params = {}
    if params.get('mode') == 'draft_builder':
        data = {
            'project_name': params.get('project_name') or log.project_name or '',
            'script': params.get('script') or '',
            'aspect': params.get('aspect') or 'portrait',
            'scene_duration': params.get('scene_duration') or 3,
            'scenes': params.get('scenes') or [],
            'output_dir': params.get('output_dir') or '',
        }
        try:
            with current_app.test_request_context(json=data, headers={'Authorization': request.headers.get('Authorization', '')}):
                return ai_manga_generate_draft()
        except Exception as e:
            return jsonify({'ok': False, 'error': f'重新生成草稿失败: {e}'}), 500
    character_path = params.get('character_image_path') or ''
    if character_path:
        params['character_image'] = _encode_file_to_data_uri(character_path)
    try:
        data = {
            'script': params.get('script') or '',
            'style': params.get('style') or '',
            'shot_types': params.get('shot_types') or ['intro', 'action', 'emotion', 'interaction', 'final'],
            'frame_count': params.get('frame_count'),
            'image_resolution': params.get('image_resolution'),
            'video_bitrate': params.get('video_bitrate'),
            'character_image': params.get('character_image') or '',
        }
        request_ctx = request
        # reuse the same generate path by calling ai_manga_generate logic
        with current_app.test_request_context(json=data, headers={'Authorization': request.headers.get('Authorization', '')}):
            return ai_manga_generate()
    except Exception as e:
        _log_openclaw_error(user.id, params, str(e))
        return jsonify({'ok': False, 'error': f'重新生成失败: {e}'}), 500


@api_bp.route('/manga/history/<int:log_id>/redownload', methods=['POST'])
def manga_history_redownload(log_id):
    # OpenClaw does not provide a standard re-download API, fallback to regenerate
    return manga_history_regenerate(log_id)


@api_bp.route('/manga/templates', methods=['GET', 'POST'])
def manga_templates():
    user, err = get_auth_user()
    if err:
        return err
    if request.method == 'GET':
        items = MangaTemplate.query.filter_by(user_id=user.id).order_by(MangaTemplate.id.desc()).all()
        data = []
        for item in items:
            params = {}
            if item.params_json:
                try:
                    params = json.loads(item.params_json)
                except Exception:
                    params = {}
            data.append({
                'id': item.id,
                'name': item.name,
                'params': params,
                'preview_material_id': item.preview_material_id,
                'usage_count': item.usage_count or 0,
                'created_at': item.created_at.isoformat() if item.created_at else None,
            })
        return jsonify({'ok': True, 'items': data})

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    params = data.get('params') or {}
    preview_material_id = data.get('preview_material_id')
    if not name:
        return jsonify({'ok': False, 'error': '模板名称不能为空'}), 400
    item = MangaTemplate(
        user_id=user.id,
        name=name,
        params_json=json.dumps(params or {}, ensure_ascii=False),
        preview_material_id=preview_material_id,
        usage_count=0,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'ok': True, 'id': item.id})


@api_bp.route('/manga/templates/<int:template_id>/use', methods=['POST'])
def manga_template_use(template_id):
    user, err = get_auth_user()
    if err:
        return err
    item = MangaTemplate.query.get(template_id)
    if not item or item.user_id != user.id:
        return jsonify({'ok': False, 'error': '模板不存在'}), 404
    item.usage_count = (item.usage_count or 0) + 1
    db.session.add(item)
    db.session.commit()
    params = {}
    if item.params_json:
        try:
            params = json.loads(item.params_json)
        except Exception:
            params = {}
    return jsonify({'ok': True, 'params': params})


@api_bp.route('/user/materials/project/rename', methods=['POST'])
def user_materials_project_rename():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    project_id = (data.get('project_id') or '').strip()
    project_name = (data.get('project_name') or '').strip()
    if not project_id or not project_name:
        return jsonify({'ok': False, 'error': '缺少项目ID或名称'}), 400
    items = UserMaterial.query.filter_by(user_id=user.id).all()
    updated = 0
    for item in items:
        tags = []
        if item.tags:
            try:
                tags = json.loads(item.tags)
            except Exception:
                tags = []
        if f'project:{project_id}' not in tags:
            continue
        meta = {}
        if item.metadata_json:
            try:
                meta = json.loads(item.metadata_json)
            except Exception:
                meta = {}
        meta['project_name'] = project_name
        item.metadata_json = json.dumps(meta, ensure_ascii=False)
        db.session.add(item)
        updated += 1
    if updated:
        db.session.commit()
    return jsonify({'ok': True, 'updated': updated})


def _ensure_default_ai_providers():
    defaults = [
        {
            'provider_code': 'jimeng',
            'provider_name': '即梦 AI',
            'description': '图像和视频生成',
            'docs_url': '',
        },
        {
            'provider_code': 'volc',
            'provider_name': '火山引擎',
            'description': '语音合成与相关能力',
            'docs_url': 'https://www.volcengine.com/docs/6561/79816',
        },
        {
            'provider_code': 'openai',
            'provider_name': 'OpenAI',
            'description': '文本、图片、音频和视频生成',
            'docs_url': 'https://platform.openai.com/docs/api-reference/introduction',
        },
    ]
    changed = False
    for item in defaults:
        existing = AIProvider.query.filter_by(provider_code=item['provider_code']).first()
        if existing:
            if not existing.provider_name:
                existing.provider_name = item['provider_name']
                changed = True
            if not existing.description:
                existing.description = item['description']
                changed = True
            if not existing.docs_url and item['docs_url']:
                existing.docs_url = item['docs_url']
                changed = True
            if existing.is_active is None:
                existing.is_active = True
                changed = True
            continue
        db.session.add(AIProvider(
            provider_code=item['provider_code'],
            provider_name=item['provider_name'],
            description=item['description'],
            docs_url=item['docs_url'],
            is_active=True,
        ))
        changed = True
    if changed:
        db.session.commit()


@api_bp.route('/user/materials/refresh', methods=['POST'])
def user_materials_refresh():
    user, err = get_auth_user()
    if err:
        return err
    root = _user_ai_root(user.id)
    if not root or not os.path.exists(root):
        return jsonify({'ok': True, 'items': []})

    known = {m.file_path for m in UserMaterial.query.filter_by(user_id=user.id).all()}
    new_items = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            if path in known:
                continue
            ftype = _guess_material_type(name)
            new_items.append(UserMaterial(
                user_id=user.id,
                file_path=path,
                file_type=ftype,
                source="ai",
            ))
    if new_items:
        db.session.add_all(new_items)
        db.session.commit()
    return jsonify({'ok': True, 'added': len(new_items)})


@api_bp.route('/ai/providers', methods=['GET'])
def ai_providers():
    user, err = get_auth_user()
    if err:
        return err
    _ensure_default_ai_providers()
    providers = AIProvider.query.order_by(AIProvider.id.asc()).all()
    keys = UserApiKey.query.filter_by(user_id=user.id).all()
    key_map = {}
    for k in keys:
        key_map.setdefault(k.provider_id, 0)
        key_map[k.provider_id] += 1
    data = []
    docs_fallback = {
        "openai": "https://platform.openai.com/docs/api-reference/introduction",
        "volc": "https://www.volcengine.com/docs/6561/79816",
        "jimeng": "",
    }
    for p in providers:
        docs_url = p.docs_url or docs_fallback.get(p.provider_code, "")
        data.append({
            "id": p.id,
            "provider_code": p.provider_code,
            "provider_name": p.provider_name,
            "description": p.description,
            "logo_url": p.logo_url,
            "docs_url": docs_url,
            "is_active": bool(p.is_active),
            "has_keys": key_map.get(p.id, 0),
        })
    return jsonify({'ok': True, 'items': data})


@api_bp.route('/ai/providers/<provider_code>/guide', methods=['GET'])
def ai_provider_guide(provider_code):
    user, err = get_auth_user()
    if err:
        return err
    code = (provider_code or '').strip().lower()
    guide_map = {
        "openai": (
            "# OpenAI 指南\n\n"
            "1. 获取 API Key\n"
            "2. Base URL 使用官方地址 `https://api.openai.com/v1`\n"
            "3. 在 OpenAI 平台填写 Base URL\n\n"
            "示例（兼容 OpenAI 协议的服务）：\n"
            "- `https://dashscope.aliyuncs.com/compatible-mode/v1`\n"
            "- `https://api.deepseek.com`\n"
            "- `https://open.bigmodel.cn/api/paas/v4`\n"
            "- `https://openrouter.ai/api/v1`\n"
        ),
        "jimeng": (
            "# 即梦 AI 指南\n\n"
            "1. 在控制台开通服务\n"
            "2. 获取 AK/SK\n"
            "3. 填写 API Key=AK，API Secret=SK，Endpoint=地址\n\n"
            "签名参数：Region=cn-north-1，Service=cv\n"
            "需要填写 Action/Version\n"
        ),
        "volc": (
            "# 火山 TTS 指南\n\n"
            "1. 开通 TTS 服务\n"
            "2. 获取 access_token / appid / cluster\n"
            "3. 填写 API Key=access_token，API Secret=appid，Endpoint=cluster\n\n"
            "接口：`https://openspeech.bytedance.com/api/v1/tts`\n\n"
            "注意：需要提供 voice_type\n"
        ),
    }
    content = guide_map.get(code, "# 指南\n\n暂无说明")
    return jsonify({"ok": True, "content": content})


@api_bp.route('/ai/keys', methods=['GET', 'POST'])
def ai_keys():
    user, err = get_auth_user()
    if err:
        return err
    if request.method == 'GET':
        keys = UserApiKey.query.filter_by(user_id=user.id).order_by(UserApiKey.id.desc()).all()
        return jsonify({'ok': True, 'items': [_ai_key_to_dict(k) for k in keys]})

    data = request.get_json() or {}
    provider_id = data.get('provider_id')
    provider_code = data.get('provider_code')
    key_name = (data.get('key_name') or '').strip()
    api_key = (data.get('api_key') or '').strip()
    api_secret = (data.get('api_secret') or '').strip()
    endpoint = (data.get('endpoint') or '').strip()
    try:
        base_url = _normalize_http_service_url(data.get('base_url') or '', allow_localhost=False)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    is_active = data.get('is_active', True)

    provider = None
    if provider_id:
        provider = AIProvider.query.get(provider_id)
    elif provider_code:
        provider = AIProvider.query.filter_by(provider_code=provider_code).first()
    if not provider:
        return jsonify({'ok': False, 'error': '未找到供应商'}), 404
    if not key_name or not api_key:
        return jsonify({'ok': False, 'error': 'Key 名称或 API Key 不能为空'}), 400

    item = UserApiKey(
        user_id=user.id,
        provider_id=provider.id,
        key_name=key_name,
        endpoint=endpoint or None,
        base_url=base_url or None,
        is_active=bool(is_active),
    )
    item.set_api_key(api_key)
    if api_secret:
        item.set_api_secret(api_secret)
    db.session.add(item)
    db.session.commit()
    return jsonify({'ok': True, 'item': _ai_key_to_dict(item)})


@api_bp.route('/user/keys', methods=['GET', 'POST'])
def user_keys():
    user, err = get_auth_user()
    if err:
        return err
    if request.method == 'GET':
        keys = UserApiKey.query.filter_by(user_id=user.id).order_by(UserApiKey.id.desc()).all()
        return jsonify({'ok': True, 'items': [_ai_key_to_dict(k) for k in keys]})

    data = request.get_json() or {}
    provider_code = (data.get('provider_code') or '').strip()
    provider = AIProvider.query.filter_by(provider_code=provider_code).first()
    if not provider:
        return jsonify({'ok': False, 'error': '未找到供应商'}), 404
    key_name = (data.get('key_name') or '').strip()
    api_key = (data.get('api_key') or '').strip()
    api_secret = (data.get('api_secret') or '').strip()
    endpoint = (data.get('endpoint') or '').strip()
    try:
        base_url = _normalize_http_service_url(data.get('base_url') or '', allow_localhost=False)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    if not key_name or not api_key:
        return jsonify({'ok': False, 'error': 'Key 名称或 API Key 不能为空'}), 400

    item = UserApiKey(
        user_id=user.id,
        provider_id=provider.id,
        key_name=key_name,
        endpoint=endpoint or None,
        base_url=base_url or None,
        is_active=True,
    )
    item.set_api_key(api_key)
    if api_secret:
        item.set_api_secret(api_secret)
    db.session.add(item)
    db.session.commit()
    return jsonify({'ok': True, 'item': _ai_key_to_dict(item)})


@api_bp.route('/ai/keys/<int:key_id>', methods=['PUT', 'DELETE'])
def ai_key_update_delete(key_id):
    user, err = get_auth_user()
    if err:
        return err
    key = UserApiKey.query.filter_by(id=key_id, user_id=user.id).first()
    if not key:
        return jsonify({'ok': False, 'error': 'Key 不存在'}), 404

    if request.method == 'DELETE':
        db.session.delete(key)
        db.session.commit()
        return jsonify({'ok': True})

    data = request.get_json() or {}
    key_name = data.get('key_name')
    api_key = data.get('api_key')
    api_secret = data.get('api_secret')
    endpoint = data.get('endpoint')
    base_url = data.get('base_url')
    is_active = data.get('is_active')

    if key_name is not None:
        key.key_name = key_name.strip() or key.key_name
    if api_key:
        key.set_api_key(api_key)
    if api_secret is not None:
        if api_secret:
            key.set_api_secret(api_secret)
        else:
            key.api_secret = None
    if endpoint is not None:
        key.endpoint = endpoint.strip() or None
    if base_url is not None:
        try:
            key.base_url = _normalize_http_service_url(base_url, allow_localhost=False) or None
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
    if is_active is not None:
        key.is_active = bool(is_active)

    db.session.add(key)
    db.session.commit()
    return jsonify({'ok': True, 'item': _ai_key_to_dict(key)})


@api_bp.route('/user/keys/<int:key_id>', methods=['PUT', 'DELETE'])
def user_key_update_delete(key_id):
    return ai_key_update_delete(key_id)


def _normalize_base_url(value: str) -> str:
    if not value:
        return "https://api.openai.com/v1"
    base = value.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base


def _test_key_request(provider_code: str, api_key: str, endpoint: str, base_url: str = None):
    if provider_code == "openai":
        base = _normalize_base_url(base_url)
        url = base + "/models"
        try:
            res = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
            if res.status_code == 200:
                return True, "ok"
            return False, res.text[:200]
        except Exception as e:
            return False, str(e)
    if provider_code == "volc":
        return False, "请提供 voice_type / app_id / cluster"
    else:
        url = (endpoint or "").rstrip("/") + "/v1/models"
    if not url or url.startswith("/v1"):
        return False, "未设置 Endpoint"
    try:
        res = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
        if res.status_code == 200:
            return True, "ok"
        return False, res.text[:200]
    except Exception as e:
        return False, str(e)


@api_bp.route('/user/keys/<int:key_id>/test', methods=['POST'])
def user_key_test(key_id):
    user, err = get_auth_user()
    if err:
        return err
    key = UserApiKey.query.filter_by(id=key_id, user_id=user.id).first()
    if not key:
        return jsonify({'ok': False, 'error': 'Key 不存在'}), 404
    provider = key.provider
    provider_code = provider.provider_code if provider else ""
    if provider_code == "volc":
        data = request.get_json(silent=True) or {}
        from app.services.ai_service import _volc_tts_http
        try:
            app_id = data.get("app_id") or key.get_api_secret()
            cluster = data.get("cluster") or key.endpoint
            voice_type = data.get("voice_type")
            if not voice_type:
                return jsonify({'ok': False, 'message': '缺少 voice_type'}), 400
            payload = {
                "prompt": data.get("text") or "测试",
                "voice": voice_type,
                "format": data.get("format") or "mp3",
            }
            _volc_tts_http(key.get_api_key(), app_id, cluster, payload)
            return jsonify({'ok': True, 'message': 'ok'})
        except Exception as e:
            return jsonify({'ok': False, 'message': str(e)}), 400
    if provider_code == "jimeng":
        data = request.get_json(silent=True) or {}
        action = data.get("action")
        version = data.get("version")
        if not action or not version:
            return jsonify({'ok': False, 'message': '缺少 Action/Version'}), 400
        from app.services.ai_service import _jimeng_signed_request
        try:
            payload = {"prompt": "test", "extra_body": {"action": action, "version": version}}
            _jimeng_signed_request(key.get_api_key(), key.get_api_secret(), key.endpoint, payload)
            return jsonify({'ok': True, 'message': 'ok'})
        except Exception as e:
            return jsonify({'ok': False, 'message': str(e)}), 400
    ok, msg = _test_key_request(provider_code, key.get_api_key(), key.endpoint, key.base_url)
    return jsonify({'ok': ok, 'message': msg})


@api_bp.route('/ai/generate', methods=['POST'])
def ai_generate():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json() or {}
    key_id = data.get('key_id')
    task_type = (data.get('task_type') or '').strip()
    prompt = (data.get('prompt') or '').strip()
    if not key_id:
        return jsonify({'ok': False, 'error': '请选择 Key'}), 400
    if not task_type:
        return jsonify({'ok': False, 'error': '请选择任务类型'}), 400
    if not prompt:
        return jsonify({'ok': False, 'error': '请输入提示词'}), 400

    key = UserApiKey.query.filter_by(id=key_id, user_id=user.id).first()
    if not key or not key.is_active:
        return jsonify({'ok': False, 'error': 'Key 不存在或未启用'}), 400

    payload = {
        "prompt": prompt,
        "model": data.get('model'),
        "temperature": data.get('temperature'),
        "max_tokens": data.get('max_tokens'),
        "size": data.get('size'),
        "seconds": data.get('seconds'),
        "voice": data.get('voice'),
        "format": data.get('format'),
        "custom_path": data.get('custom_path'),
    }
    extra_body = data.get('extra_body')
    if extra_body:
        if isinstance(extra_body, dict):
            payload["extra_body"] = extra_body
        else:
            try:
                payload["extra_body"] = json.loads(extra_body)
            except Exception:
                return jsonify({'ok': False, 'error': 'extra_body JSON 解析失败'}), 400

    result = generate_with_key(key, task_type, payload)
    return jsonify(result)


def _enqueue_ai_task(user, key, task_type, payload, save_text_file=False):
    task_id = uuid.uuid4().hex
    task = AITask(
        id=task_id,
        user_id=user.id,
        key_id=key.id,
        provider_code=key.provider.provider_code if key.provider else "",
        task_type=task_type,
        status="pending",
        prompt=payload.get("prompt") or payload.get("text"),
    )
    db.session.add(task)
    db.session.commit()
    app = current_app._get_current_object()
    _run_background(app, generate_ai_task, task_id, user.id, key.id, task_type, payload, save_text_file)
    return task_id


def _build_manga_draft_result(user: User, data: dict) -> dict:
    payload = data if isinstance(data, dict) else {}
    project_name = (payload.get("project_name") or "").strip() or f"AI漫剧草稿_{_china_now().strftime('%m%d_%H%M')}"
    aspect = (payload.get("aspect") or "portrait").strip().lower() or "portrait"
    width, height, aspect_label = _manga_aspect_preset(aspect)
    scenes = _normalize_manga_draft_scenes(payload)
    if not scenes:
        raise ValueError("请先填写脚本，至少准备 1 个场景。")

    output_dir = (payload.get("output_dir") or "").strip() or (get_drafts_folder() or "").strip()
    if not output_dir:
        output_dir = os.path.join(get_user_data_dir(user.id), "manga_exports")
    os.makedirs(output_dir, exist_ok=True)

    default_duration = max(float(scene.get("duration") or 3.0) for scene in scenes)
    placeholder_path = _ensure_manga_placeholder_video(user.id, width, height, default_duration)
    project_id = f"manga_draft_{_china_now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    workspace = _build_manga_material_workspace(user.id, project_id, project_name, scenes)

    from app.services.jianying_service import JianYingService

    save_path = _manga_draft_cache_root(user.id)
    os.makedirs(save_path, exist_ok=True)
    svc = JianYingService(save_path=save_path, output_path=output_dir)
    draft_name = _safe_folder_name(project_name, project_id)
    create_resp = svc.create_draft(draft_name=draft_name, width=width, height=height, fps=30)
    if not create_resp.ok:
        raise ValueError(create_resp.message or "创建 AI 漫剧草稿失败")

    draft_id = str((create_resp.data or {}).get("draft_id") or "").strip()
    if not draft_id:
        raise ValueError("创建 AI 漫剧草稿后未返回 draft_id")

    video_track_resp = svc.create_track(draft_id, "video", "main")
    if not video_track_resp.ok:
        raise ValueError(video_track_resp.message or "创建 AI 漫剧视频轨道失败")
    video_track_name = ((video_track_resp.data or {}).get("track_name") or "main").strip() or "main"

    text_track_resp = svc.create_track(draft_id, "text", "scene_notes")
    text_track_name = ((text_track_resp.data or {}).get("track_name") or "scene_notes").strip() or "scene_notes"

    cursor = 0.0
    scene_items = []
    for scene in scenes:
        duration = max(1.0, min(float(scene.get("duration") or default_duration), 30.0))
        scene_text = str(scene.get("text") or "").strip()
        target_timerange = f"{cursor:.3f}s-{duration:.3f}s"
        segment_resp = svc.add_video_segment(
            draft_id,
            placeholder_path,
            target_timerange,
            source_timerange=f"0.000s-{duration:.3f}s",
            track_name=video_track_name,
        )
        if not segment_resp.ok:
            raise ValueError(segment_resp.message or f"创建场景 {scene.get('index')} 占位片段失败")

        if scene_text:
            text_resp = svc.add_text_segment(
                draft_id,
                f"{int(scene.get('index') or 0):02d}. {scene_text}",
                target_timerange,
                track_name=text_track_name,
            )
            if not text_resp.ok:
                raise ValueError(text_resp.message or f"创建场景 {scene.get('index')} 说明文字失败")

        scene_items.append({
            "index": int(scene.get("index") or len(scene_items) + 1),
            "text": scene_text,
            "duration": duration,
            "folder_path": next(
                (item["path"] for item in workspace["folders"] if int(item.get("index") or 0) == int(scene.get("index") or 0)),
                "",
            ),
        })
        cursor += duration

    export_resp = svc.export_draft(draft_id, jianying_draft_path=output_dir)
    if not export_resp.ok:
        raise ValueError(export_resp.message or "导出 AI 漫剧草稿失败")

    export_data = export_resp.data or {}
    draft_path = str(export_data.get("output") or "").strip()
    exported_name = str(export_data.get("draft_name") or draft_name).strip() or draft_name
    return {
        "project_id": project_id,
        "project_name": project_name,
        "draft_id": draft_id,
        "draft_name": exported_name,
        "draft_path": draft_path,
        "output_dir": output_dir,
        "aspect": aspect,
        "aspect_label": aspect_label,
        "scene_count": len(scene_items),
        "scene_duration": default_duration,
        "total_duration": round(cursor, 3),
        "workspace": workspace,
        "scenes": scene_items,
        "placeholder_path": placeholder_path,
        "script": "\n".join(scene["text"] for scene in scene_items if scene.get("text")),
    }



@api_bp.route('/openclaw/logs', methods=['GET'])
def openclaw_logs():
    user, err = get_auth_user()
    if err:
        return err
    path = _openclaw_log_path()
    if not os.path.exists(path):
        return jsonify({'ok': True, 'path': path, 'content': ''})
    limit = int(request.args.get('limit') or 200)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        content = ''.join(lines[-limit:])
        return jsonify({'ok': True, 'path': path, 'content': content})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@api_bp.route('/openclaw/test', methods=['POST'])
def openclaw_test():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        base_url = _normalize_http_service_url(data.get('base_url') or '', allow_localhost=True)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    token = (data.get('token') or '').strip()
    if not base_url:
        return jsonify({'ok': False, 'error': 'Missing service base_url'}), 400
    client = OpenClawClient(base_url, token)
    ok = client.test_connection()
    if ok:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Connection failed'}), 400


@api_bp.route('/ai/manga/generate-draft', methods=['POST'])
def ai_manga_generate_draft():
    user, err = get_auth_user()
    if err:
        return err
    online_err = _require_remote_online('ai_manga')
    if online_err:
        return online_err
    if not _effective_runtime_features().get("manga"):
        return jsonify({'ok': False, 'error': 'AI manga feature is disabled in this build'}), 404

    cost = int(get_config('manga_generate_cost', '1') or 1)
    remote_task_id = f"manga_draft_{uuid.uuid4().hex}"
    remote_task_token = None
    quota = None
    if _should_use_remote_auth():
        remote_task_token, remote_claim_error = _remote_desktop_task_claim(remote_task_id, 'manga_generate', cost)
        if remote_claim_error:
            return remote_claim_error
    else:
        quota = get_or_create_quota(user.id)
        if quota.remaining < cost:
            return jsonify({'ok': False, 'error': '额度不足，无法继续生成 AI 漫剧草稿。', **quota_to_dict(quota)}), 403

    data = request.get_json(silent=True) or {}
    try:
        result = _build_manga_draft_result(user, data)
        params_for_log = {
            'mode': 'draft_builder',
            'project_name': result['project_name'],
            'script': result['script'],
            'aspect': result['aspect'],
            'aspect_label': result['aspect_label'],
            'scene_duration': result['scene_duration'],
            'scene_count': result['scene_count'],
            'total_duration': result['total_duration'],
            'draft_name': result['draft_name'],
            'draft_path': result['draft_path'],
            'output_dir': result['output_dir'],
            'workspace_root': result['workspace']['workspace_root'],
            'materials_root': result['workspace']['materials_root'],
            'script_path': result['workspace']['script_path'],
            'scenes': result['scenes'],
        }
        log = MangaGenerationLog(
            user_id=user.id,
            project_id=result['project_id'],
            project_name=result['project_name'],
            params_json=json.dumps(params_for_log, ensure_ascii=False),
            first_material_id=None,
            status='success',
            created_at=datetime.utcnow(),
        )
        db.session.add(log)

        if quota is not None:
            quota.remaining = max(0, (quota.remaining or 0) - cost)
            quota.total_generated = (quota.total_generated or 0) + cost
            db.session.add(quota)
            db.session.add(UserQuotaLog(
                user_id=user.id,
                change=-cost,
                reason='manga_generate',
                project_id=result['project_id'],
                remaining_after=quota.remaining,
            ))
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        if remote_task_token:
            _remote_desktop_task_complete(remote_task_id, remote_task_token, False, str(exc))
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        if remote_task_token:
            _remote_desktop_task_complete(remote_task_id, remote_task_token, False, str(exc))
        return jsonify({'ok': False, 'error': f'生成 AI 漫剧草稿失败: {exc}'}), 500

    if remote_task_token:
        _remote_desktop_task_complete(remote_task_id, remote_task_token, True, "")

    return jsonify({
        'ok': True,
        'mode': 'draft_builder',
        'project_id': result['project_id'],
        'project_name': result['project_name'],
        'draft_id': result['draft_id'],
        'draft_name': result['draft_name'],
        'draft_path': result['draft_path'],
        'output_dir': result['output_dir'],
        'aspect': result['aspect'],
        'aspect_label': result['aspect_label'],
        'scene_count': result['scene_count'],
        'total_duration': result['total_duration'],
        'workspace': result['workspace'],
        'scenes': result['scenes'],
        'quota': quota_to_dict(quota) if quota is not None else None,
        'message': f"已生成 {result['scene_count']} 个场景的剪映草稿，可继续往场景目录里放素材。",
    })


@api_bp.route('/ai/manga/generate', methods=['POST'])
def ai_manga_generate():
    user, err = get_auth_user()
    if err:
        return err
    online_err = _require_remote_online('ai_manga')
    if online_err:
        return online_err
    if not _effective_runtime_features().get("manga"):
        return jsonify({'ok': False, 'error': 'AI manga feature is disabled in this build'}), 404
    data = request.get_json(silent=True) or {}
    config = load_user_config(user.id) or {}
    openclaw_cfg = config.get('openclaw') or {}
    base_url = (openclaw_cfg.get('base_url') or '').strip()
    token = (openclaw_cfg.get('token') or '').strip()
    if not base_url:
        return jsonify({'ok': False, 'error': 'OpenClaw base_url not configured'}), 400

    user_material_dir = get_user_material_dir(user.id)
    if not user_material_dir:
        return jsonify({'ok': False, 'error': 'Material folder not configured'}), 400

    cost = int(get_config('manga_generate_cost', '1') or 1)
    remote_task_id = f"manga_ai_{uuid.uuid4().hex}"
    remote_task_token = None
    quota = None
    if _should_use_remote_auth():
        remote_task_token, remote_claim_error = _remote_desktop_task_claim(remote_task_id, 'manga_generate', cost)
        if remote_claim_error:
            return remote_claim_error
    else:
        quota = get_or_create_quota(user.id)
        if quota.remaining < cost:
            return jsonify({'ok': False, 'error': '额度不足，无法生成', **quota_to_dict(quota)}), 403

    client = OpenClawClient(base_url, token)
    script = (data.get('script') or '').strip()
    style = (data.get('style') or '').strip()
    shot_types = data.get('shot_types') or ['intro', 'action', 'emotion', 'interaction', 'final']
    frame_count = data.get('frame_count')
    image_resolution = data.get('image_resolution')
    video_bitrate = data.get('video_bitrate')
    character_image = data.get('character_image')
    params = {
        "character_image": character_image,
        "script": script,
        "style": style,
        "shot_types": shot_types,
        "frame_count": frame_count,
        "image_resolution": image_resolution,
        "video_bitrate": video_bitrate,
    }

    try:
        result = client.generate_manga(params)
        date_str = datetime.utcnow().strftime('%Y%m%d')
        manga_root = os.path.join(user_material_dir, 'manga')
        os.makedirs(manga_root, exist_ok=True)

        def _next_seq(root_dir, prefix):
            max_idx = 0
            if os.path.isdir(root_dir):
                for name in os.listdir(root_dir):
                    if not name.startswith(prefix):
                        continue
                    suffix = name.replace(prefix, '')
                    if suffix.isdigit():
                        max_idx = max(max_idx, int(suffix))
            return max_idx + 1

        prefix = f"manga_{date_str}_"
        seq = _next_seq(manga_root, prefix)
        project_id = f"manga_{date_str}_{seq:03d}"
        project_name = f"漫剧_{date_str}_{seq:03d}"

        save_dir = os.path.join(manga_root, project_id)
        os.makedirs(save_dir, exist_ok=True)

        character_path = _save_character_image(save_dir, character_image)

        script_summary = script[:100]
        created_at = datetime.utcnow().isoformat()
        base_meta = {
            'project_id': project_id,
            'project_name': project_name,
            'script_summary': script_summary,
            'style': style,
            'shot_types': shot_types,
            'created_at': created_at,
            'frame_count': frame_count,
            'image_resolution': image_resolution,
            'video_bitrate': video_bitrate,
            'character_image_path': character_path,
        }
        tags = ['manga', f'project:{project_id}']

        saved_frames = []
        material_ids = []
        frames = result.get('frames') or []
        for idx, frame in enumerate(frames, start=1):
            url = ''
            data_b64 = ''
            if isinstance(frame, dict):
                url = frame.get('url') or ''
                data_b64 = frame.get('data') or frame.get('base64') or ''
            elif isinstance(frame, str):
                url = frame
            ext = '.png'
            if url:
                resp = requests.get(url, timeout=120)
                resp.raise_for_status()
                ext = _guess_extension(url, resp.headers.get('Content-Type', ''), '.png')
                path = os.path.join(save_dir, f"frame_{idx:03d}{ext}")
                with open(path, 'wb') as f:
                    f.write(resp.content)
            elif data_b64:
                path = os.path.join(save_dir, f"frame_{idx:03d}{ext}")
                with open(path, 'wb') as f:
                    f.write(_decode_data_uri(data_b64))
            else:
                continue
            meta = dict(base_meta)
            meta['frame_index'] = idx
            mid = add_user_material(user.id, path, 'image', tags=tags, source='openclaw', metadata_json=meta)
            material_ids.append(mid)
            saved_frames.append({
                'id': mid,
                'path': path,
                'preview_url': f"/api/user/materials/file/{mid}",
            })

        video_info = result.get('video') or result.get('preview') or None
        video_payload = None
        video_path = None
        if isinstance(video_info, str):
            video_info = {'url': video_info}
        if isinstance(video_info, dict):
            v_url = video_info.get('url') or ''
            v_b64 = video_info.get('data') or video_info.get('base64') or ''
            if v_url:
                resp = requests.get(v_url, timeout=180)
                resp.raise_for_status()
                ext = _guess_extension(v_url, resp.headers.get('Content-Type', ''), '.mp4')
                video_path = os.path.join(save_dir, f"preview{ext}")
                with open(video_path, 'wb') as f:
                    f.write(resp.content)
            elif v_b64:
                video_path = os.path.join(save_dir, 'preview.mp4')
                with open(video_path, 'wb') as f:
                    f.write(_decode_data_uri(v_b64))

        if video_path:
            meta = dict(base_meta)
            meta['type'] = 'video'
            mid = add_user_material(user.id, video_path, 'video', tags=tags, source='openclaw', metadata_json=meta)
            material_ids.append(mid)
            video_payload = {
                'id': mid,
                'path': video_path,
                'preview_url': f"/api/user/materials/file/{mid}",
            }

        params_for_log = {
            'script': script,
            'style': style,
            'shot_types': shot_types,
            'frame_count': frame_count,
            'image_resolution': image_resolution,
            'video_bitrate': video_bitrate,
            'character_image_path': character_path,
        }
        first_material_id = saved_frames[0]['id'] if saved_frames else None
        log = MangaGenerationLog(
            user_id=user.id,
            project_id=project_id,
            project_name=project_name,
            params_json=json.dumps(params_for_log, ensure_ascii=False),
            first_material_id=first_material_id,
            status='success',
            created_at=datetime.utcnow(),
        )
        db.session.add(log)

        if quota is not None:
            quota.remaining = max(0, (quota.remaining or 0) - cost)
            quota.total_generated = (quota.total_generated or 0) + cost
            db.session.add(quota)
            db.session.add(UserQuotaLog(
                user_id=user.id,
                change=-cost,
                reason='manga_generate',
                project_id=project_id,
                remaining_after=quota.remaining,
            ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        _log_openclaw_error(user.id, params, str(e))
        if remote_task_token:
            _remote_desktop_task_complete(remote_task_id, remote_task_token, False, str(e))
        return jsonify({'ok': False, 'error': f'OpenClaw call failed: {e}'}), 500

    if remote_task_token:
        _remote_desktop_task_complete(remote_task_id, remote_task_token, True, "")

    return jsonify({
        'ok': True,
        'project_id': project_id,
        'project_name': project_name,
        'material_ids': material_ids,
        'frames': saved_frames,
        'video': video_payload,
        'quota': quota_to_dict(quota) if quota is not None else None,
        'message': f"Generated {len(saved_frames)} frames" + (" and 1 preview video" if video_payload else '')
    })


@api_bp.route('/user/materials/file/<int:material_id>', methods=['GET'])
@api_bp.route('/user/materials/file/<int:material_id>', methods=['GET'])
@api_bp.route('/user/materials/file/<int:material_id>', methods=['GET'])
@api_bp.route('/user/materials/file/<int:material_id>', methods=['GET'])
@api_bp.route('/user/materials/file/<int:material_id>', methods=['GET'])
def user_material_file(material_id):
    token = extract_bearer_token(request) or (request.args.get('token') or '').strip()
    user, _token_obj, err = validate_token(token)
    if err:
        return _auth_error('Unauthorized', 401)
    item = UserMaterial.query.get(material_id)
    if not item or item.user_id != user.id:
        return jsonify({'ok': False, 'error': 'Material not found'}), 404
    if not item.file_path or not os.path.exists(item.file_path):
        return jsonify({'ok': False, 'error': 'Material file missing'}), 404
    return send_file(item.file_path, as_attachment=False)

@api_bp.route('/ai/generate/video', methods=['POST'])
def ai_generate_video():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json() or {}
    key_id = data.get('key_id')
    prompt = (data.get('prompt') or '').strip()
    if not key_id or not prompt:
        return jsonify({'ok': False, 'error': '缺少 Key 或提示词'}), 400
    key = UserApiKey.query.filter_by(id=key_id, user_id=user.id).first()
    if not key:
        return jsonify({'ok': False, 'error': 'Key 不存在'}), 404
    payload = {
        "prompt": prompt,
        "model": data.get("model"),
        "size": data.get("size"),
        "seconds": data.get("seconds"),
        "custom_path": data.get("custom_path"),
        "extra_body": _parse_extra_body(data.get("extra_body")),
    }
    style = data.get("style")
    if style:
        payload.setdefault("extra_body", {})
        if isinstance(payload["extra_body"], dict):
            payload["extra_body"]["style"] = style
    task_id = _enqueue_ai_task(user, key, "video", payload, save_text_file=False)
    return jsonify({'ok': True, 'task_id': task_id})


@api_bp.route('/ai/generate/audio', methods=['POST'])
def ai_generate_audio():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json() or {}
    key_id = data.get('key_id')
    text = (data.get('text') or '').strip()
    if not key_id or not text:
        return jsonify({'ok': False, 'error': '缺少 Key 或文本'}), 400
    key = UserApiKey.query.filter_by(id=key_id, user_id=user.id).first()
    if not key:
        return jsonify({'ok': False, 'error': 'Key 不存在'}), 404
    payload = {
        "prompt": text,
        "model": data.get("model"),
        "voice": data.get("voice_type") or data.get("voice"),
        "format": data.get("format"),
        "custom_path": data.get("custom_path"),
        "extra_body": _parse_extra_body(data.get("extra_body")),
    }
    task_id = _enqueue_ai_task(user, key, "audio", payload, save_text_file=False)
    return jsonify({'ok': True, 'task_id': task_id})


@api_bp.route('/ai/generate/text', methods=['POST'])
def ai_generate_text():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json() or {}
    key_id = data.get('key_id')
    prompt = (data.get('prompt') or '').strip()
    if not key_id or not prompt:
        return jsonify({'ok': False, 'error': '缺少 Key 或提示词'}), 400
    key = UserApiKey.query.filter_by(id=key_id, user_id=user.id).first()
    if not key:
        return jsonify({'ok': False, 'error': 'Key 不存在'}), 404
    payload = {
        "prompt": prompt,
        "model": data.get("model"),
        "temperature": data.get("temperature"),
        "max_tokens": data.get("max_tokens"),
        "extra_body": _parse_extra_body(data.get("extra_body")),
    }
    task_id = _enqueue_ai_task(user, key, "text", payload, save_text_file=False)
    return jsonify({'ok': True, 'task_id': task_id})


@api_bp.route('/ai/task/<task_id>', methods=['GET'])
def ai_task_status(task_id):
    user, err = get_auth_user()
    if err:
        return err
    task = AITask.query.get(task_id)
    if not task or task.user_id != user.id:
        return jsonify({'ok': False, 'error': '任务不存在'}), 404
    return jsonify({
        'ok': True,
        'task': {
            'id': task.id,
            'status': task.status,
            'task_type': task.task_type,
            'result_path': task.result_path,
            'result_text': task.result_text,
            'error_msg': task.error_msg,
            'created_at': task.created_at.isoformat() if task.created_at else None,
            'updated_at': task.updated_at.isoformat() if task.updated_at else None,
        }
    })


@api_bp.route('/ai/logs', methods=['GET'])
def ai_logs():
    user, err = get_auth_user()
    if err:
        return err
    logs = AIGenerationLog.query.filter_by(user_id=user.id).order_by(AIGenerationLog.id.desc()).limit(50).all()
    data = []
    for r in logs:
        data.append({
            "id": r.id,
            "provider_code": r.provider_code,
            "task_type": r.task_type,
            "prompt": r.prompt,
            "result_path": r.result_path,
            "status": r.status,
            "error_msg": r.error_msg,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return jsonify({'ok': True, 'items': data})

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


@api_bp.route('/apply-effect', methods=['POST'])
def apply_effect():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}

    def _as_str(value):
        return str(value).strip() if value is not None else ''

    segment_id = _as_str(data.get('segment_id') or data.get('video_segment_id') or data.get('text_segment_id') or data.get('audio_segment_id'))
    segment_type = _as_str(data.get('segment_type')).lower()
    draft_id = _as_str(data.get('draft_id'))
    track_name = _as_str(data.get('track_name')) or None

    if not segment_type:
        if data.get('video_segment_id'):
            segment_type = 'video'
        elif data.get('text_segment_id'):
            segment_type = 'text'
        elif data.get('audio_segment_id'):
            segment_type = 'audio'

    if not segment_id:
        return jsonify({'ok': False, 'error': 'segment_id required'}), 400

    if not draft_id:
        if segment_type == 'video':
            draft_id = index_manager.get_draft_id_by_video_segment_id(segment_id) or ''
        elif segment_type == 'text':
            draft_id = index_manager.get_draft_id_by_text_segment_id(segment_id) or ''
        elif segment_type == 'audio':
            draft_id = index_manager.get_draft_id_by_audio_segment_id(segment_id) or ''
        else:
            draft_id = index_manager.get_draft_id_by_video_segment_id(segment_id) or \
                index_manager.get_draft_id_by_text_segment_id(segment_id) or \
                index_manager.get_draft_id_by_audio_segment_id(segment_id) or ''
    if not draft_id:
        return jsonify({'ok': False, 'error': 'draft_id not found for segment'}), 400

    if not track_name:
        if segment_type == 'video':
            info = index_manager.get_track_info_by_video_segment_id(segment_id)
            track_name = info.get('track_name') if info else None
        elif segment_type == 'text':
            info = index_manager.get_track_info_by_text_segment_id(segment_id)
            track_name = info.get('track_name') if info else None
        elif segment_type == 'audio':
            info = index_manager.get_track_info_by_audio_segment_id(segment_id)
            track_name = info.get('track_name') if info else None

    effect_kind = _as_str(data.get('effect_kind') or data.get('effect_category') or data.get('kind')).lower()
    if not effect_kind:
        candidate = _as_str(data.get('effect_type'))
        if candidate in (
            'video_effect', 'transition', 'video_filter', 'video_animation', 'video_mask',
            'text_animation', 'text_effect', 'text_bubble', 'audio_effect', 'audio_fade', 'audio_keyframe',
            'video_background'
        ):
            effect_kind = candidate

    effect_type = _as_str(data.get('effect_type'))
    effect_name = _as_str(data.get('effect_name') or data.get('name'))
    effect_id = _as_str(data.get('effect_id') or data.get('id'))
    resource_id = _as_str(data.get('resource_id'))
    params = data.get('params')

    from app.services.jianying_service import JianYingService
    svc = JianYingService()

    if effect_kind in ('video_effect', 'effect', 'video'):
        etype = effect_type or effect_name or effect_id
        if not etype:
            return jsonify({'ok': False, 'error': 'effect_type required for video_effect'}), 400
        result = svc.add_video_effect(draft_id, segment_id, etype, params, track_name=track_name)
    elif effect_kind in ('transition', 'video_transition'):
        ttype = effect_type or effect_name or effect_id
        if not ttype:
            return jsonify({'ok': False, 'error': 'effect_type required for transition'}), 400
        duration = data.get('duration')
        result = svc.add_video_transition(draft_id, segment_id, ttype, duration, track_name=track_name)
    elif effect_kind in ('video_filter', 'filter'):
        ftype = effect_type or effect_name or effect_id
        if not ftype:
            return jsonify({'ok': False, 'error': 'effect_type required for video_filter'}), 400
        intensity = data.get('intensity')
        try:
            intensity = float(intensity) if intensity is not None else 80.0
        except Exception:
            intensity = 80.0
        result = svc.add_video_filter(draft_id, segment_id, ftype, intensity, track_name=track_name)
    elif effect_kind in ('video_animation', 'animation'):
        anim_type = (data.get('animation_type') or effect_type or '').strip()
        anim_name = (data.get('animation_name') or effect_name or effect_id or '').strip()
        if not (anim_type and anim_name):
            return jsonify({'ok': False, 'error': 'animation_type and animation_name required'}), 400
        duration = data.get('duration')
        result = svc.add_video_animation(draft_id, segment_id, anim_type, anim_name, duration, track_name=track_name)
    elif effect_kind in ('video_mask', 'mask'):
        mtype = effect_type or effect_name or effect_id
        if not mtype:
            return jsonify({'ok': False, 'error': 'effect_type required for video_mask'}), 400
        result = svc.add_video_mask(
            draft_id,
            segment_id,
            mtype,
            data.get('center_x', 0.0),
            data.get('center_y', 0.0),
            data.get('size', 0.5),
            data.get('rotation', 0.0),
            data.get('feather', 0.0),
            data.get('invert', False),
            data.get('rect_width'),
            data.get('round_corner'),
            track_name=track_name,
        )
    elif effect_kind in ('video_background', 'background'):
        ftype = effect_type or effect_name or effect_id
        if not ftype:
            return jsonify({'ok': False, 'error': 'effect_type required for video_background'}), 400
        result = svc.add_video_background_filling(
            draft_id,
            segment_id,
            ftype,
            data.get('blur', 0.0625),
            data.get('color', '#00000000'),
            track_name=track_name,
        )
    elif effect_kind in ('text_animation', 'text_anim'):
        anim_type = (data.get('animation_type') or effect_type or 'TextIntro').strip()
        anim_name = (data.get('animation_name') or effect_name or effect_id or '').strip()
        if not anim_name:
            return jsonify({'ok': False, 'error': 'animation_name required for text_animation'}), 400
        duration = data.get('duration')
        result = svc.add_text_animation(draft_id, segment_id, anim_type, anim_name, duration, track_name=track_name)
    elif effect_kind in ('text_effect', 'text_fx'):
        eid = effect_id or effect_type or effect_name
        if not eid:
            return jsonify({'ok': False, 'error': 'effect_id required for text_effect'}), 400
        result = svc.add_text_effect(draft_id, segment_id, eid)
    elif effect_kind in ('text_bubble', 'bubble'):
        eid = effect_id or effect_type
        rid = resource_id or effect_name
        if not (eid and rid):
            return jsonify({'ok': False, 'error': 'effect_id and resource_id required for text_bubble'}), 400
        result = svc.add_text_bubble(draft_id, segment_id, eid, rid)
    elif effect_kind in ('audio_effect', 'audio_fx'):
        etype = effect_type or 'AudioSceneEffectType'
        name = effect_name or effect_id
        if not name:
            return jsonify({'ok': False, 'error': 'effect_name required for audio_effect'}), 400
        result = svc.add_audio_effect(draft_id, segment_id, etype, name, params, track_name=track_name)
    elif effect_kind == 'audio_fade':
        in_dur = data.get('in') or data.get('fade_in') or data.get('in_duration')
        out_dur = data.get('out') or data.get('fade_out') or data.get('out_duration')
        if not (in_dur and out_dur):
            return jsonify({'ok': False, 'error': 'in/out required for audio_fade'}), 400
        result = svc.add_audio_fade(draft_id, segment_id, in_dur, out_dur, track_name=track_name)
    elif effect_kind == 'audio_keyframe':
        time_offset = data.get('time') or data.get('time_offset')
        volume = data.get('volume')
        if time_offset is None or volume is None:
            return jsonify({'ok': False, 'error': 'time and volume required for audio_keyframe'}), 400
        result = svc.add_audio_keyframe(draft_id, segment_id, time_offset, volume, track_name=track_name)
    else:
        return jsonify({'ok': False, 'error': 'unsupported effect_kind'}), 400

    payload = result.to_dict()
    status = 200 if result.ok else 400
    return jsonify(payload), status

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
        'resource_path': str(svc.resource_path or ''),
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
    save_dir = str(app_resource_path('app', 'utils', 'duo_resources'))
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
    ffmpeg, source = find_ffmpeg_with_source()
    if ffmpeg:
        return jsonify({'ok': True, 'path': ffmpeg, 'source': source})
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

@api_bp.route('/open-folder', methods=['POST'])
def open_folder():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    raw_path = (data.get('path') or '').strip()
    if not raw_path:
        return jsonify({'ok': False, 'error': 'path required'}), 400
    path = os.path.abspath(raw_path)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': 'path not found'}), 404
    allowed_roots = []
    drafts_root = get_drafts_folder()
    materials_root = get_material_folder()
    user_material_root = get_user_material_dir(user.id)
    for root in (drafts_root, materials_root, user_material_root):
        if root:
            allowed_roots.append(os.path.abspath(root))
    if not allowed_roots:
        return jsonify({'ok': False, 'error': 'no allowed roots configured'}), 400
    allowed = False
    for root in allowed_roots:
        try:
            if os.path.commonpath([path, root]) == root:
                allowed = True
                break
        except Exception:
            continue
    if not allowed:
        return jsonify({'ok': False, 'error': 'path not allowed'}), 403
    try:
        import subprocess
        if os.name == 'nt':
            subprocess.Popen(['explorer', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ========== Auth ==========
@api_bp.route('/auth/register', methods=['POST'])
def api_register():
    data = request.get_json(silent=True) or {}
    online_err = _require_remote_online('register')
    if online_err:
        return online_err
    limit_err = _enforce_rate_limit(
        "register",
        limit=6,
        window_seconds=3600,
        identity_parts=[get_request_ip(request), request.headers.get("User-Agent")],
        details={"path": "/api/auth/register"},
    )
    if limit_err:
        return limit_err
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    email = (data.get('email') or '').strip() or None
    auto_login = data.get('auto_login', True)
    ref_code = (data.get('ref_code') or '').strip().upper()
    device_fingerprint = (data.get('device_fingerprint') or '').strip()
    accepted_agreements = bool(data.get('accepted_agreements'))

    if not username or not password:
        audit_security_event("register_invalid_payload", level="warning", request_obj=request, details={"username": username, "email": email})
        return jsonify({'ok': False, 'error': 'username and password are required'}), 400
    if not accepted_agreements:
        return jsonify({'ok': False, 'error': '请先同意用户协议和隐私协议'}), 400
    if User.query.filter_by(username=username).first():
        audit_security_event("register_duplicate_username", level="warning", request_obj=request, details={"username": username})
        return jsonify({'ok': False, 'error': 'username already exists'}), 400
    if email and User.query.filter_by(email=email).first():
        audit_security_event("register_duplicate_email", level="warning", request_obj=request, details={"email": email})
        return jsonify({'ok': False, 'error': 'email already exists'}), 400

    referrer_id = None
    if ref_code:
        ref_user = User.query.filter_by(ref_code=ref_code).first()
        if ref_user:
            referrer_id = ref_user.id

    user = User(username=username, email=email, role='user')
    user.referrer_id = referrer_id
    user.password_hash = generate_password_hash(password)
    try:
        db.session.add(user)
        db.session.flush()
        _ensure_user_ref_code(user)

        _apply_invite_registration_rewards(user)
        trial_claim = _claim_trial_device_quota(device_fingerprint, user.id)
        initial_trial_quota = _get_default_user_quota_value() if trial_claim.get('granted') else 0
        quota = UserQuota(user_id=user.id, total_generated=0, remaining=initial_trial_quota)
        db.session.add(quota)
        if initial_trial_quota > 0:
            db.session.add(UserQuotaLog(
                user_id=user.id,
                change=initial_trial_quota,
                reason='register_trial',
                project_id=trial_claim.get('log_key'),
                remaining_after=initial_trial_quota,
            ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    audit_security_event(
        "register_success",
        request_obj=request,
        user_id=user.id,
        details={"username": username, "trial_granted": bool(initial_trial_quota > 0)},
    )
    token_obj = issue_token(user.id) if auto_login else None
    return jsonify({
        'ok': True,
        'message': 'register success' if initial_trial_quota > 0 else 'register success, no extra trial quota granted for this device',
        'token': token_obj.token if token_obj else None,
        'trial_granted': bool(initial_trial_quota > 0),
        'trial_quota': int(initial_trial_quota),
        'user': _build_user_profile_payload(user, quota)
    })


@api_bp.route('/auth/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    online_err = _require_remote_online('login')
    if online_err:
        return online_err
    account = (data.get('username') or data.get('email') or data.get('account') or '').strip()
    password = data.get('password') or ''
    accepted_agreements = bool(data.get('accepted_agreements'))
    limit_err = _enforce_rate_limit(
        "login",
        limit=12,
        window_seconds=900,
        identity_parts=[get_request_ip(request), account],
        details={"account": account},
    )
    if limit_err:
        return limit_err
    if not account or not password:
        audit_security_event("login_invalid_payload", level="warning", request_obj=request, details={"account": account})
        return jsonify({'ok': False, 'error': '请输入账号和密码'}), 400

    if not accepted_agreements:
        return jsonify({'ok': False, 'error': '请先同意用户协议和隐私协议'}), 400

    user = User.query.filter(or_(User.username == account, User.email == account)).first()
    if not user or not check_password_hash(user.password_hash, password):
        audit_security_event("login_failed", level="warning", request_obj=request, details={"account": account})
        return jsonify({'ok': False, 'error': '账号或密码错误'}), 401
    _ensure_user_ref_code(user, commit=True)

    token_obj = issue_token(user.id)
    quota = get_or_create_quota(user.id)
    audit_security_event("login_success", request_obj=request, user_id=user.id, details={"account": account})
    return jsonify({
        'ok': True,
        'token': token_obj.token,
        'user': _build_user_profile_payload(user, quota)
    })


@api_bp.route('/user/info', methods=['GET'])
def api_user_info():
    user, err = get_auth_user()
    if err:
        return err
    _ensure_user_ref_code(user, commit=True)
    quota = get_or_create_quota(user.id)
    return jsonify({
        'ok': True,
        'user': _build_user_profile_payload(user, quota)
    })


@api_bp.route('/user/points/overview', methods=['GET'])
def api_user_points_overview():
    user, err = get_auth_user()
    if err:
        return err
    return jsonify({
        'ok': True,
        'overview': _build_user_points_overview(user.id)
    })


@api_bp.route('/user/checkin', methods=['POST'])
def api_user_checkin():
    user, err = get_auth_user()
    if err:
        return err
    online_err = _require_remote_online('daily_checkin')
    if online_err:
        return online_err
    limit_err = _enforce_rate_limit(
        "daily_checkin",
        limit=8,
        window_seconds=3600,
        identity_parts=[user.id, get_request_ip(request)],
        user_id=user.id,
    )
    if limit_err:
        return limit_err

    quota = get_or_create_quota(user.id)
    _, _, local_day = _china_day_bounds()
    existing = UserQuotaLog.query.filter(
        UserQuotaLog.user_id == user.id,
        UserQuotaLog.reason == 'daily_checkin',
        UserQuotaLog.project_id == local_day,
    ).first()
    if existing:
        return jsonify({
            'ok': True,
            'already_checked_in': True,
            'message': '今日已签到',
            'overview': _build_user_points_overview(user.id),
        })

    reward = _get_daily_checkin_reward()
    quota.remaining = (quota.remaining or 0) + reward
    log_item = UserQuotaLog(
        user_id=user.id,
        change=reward,
        reason='daily_checkin',
        project_id=local_day,
        remaining_after=quota.remaining,
    )
    db.session.add(quota)
    db.session.add(log_item)
    db.session.commit()
    audit_security_event("daily_checkin_success", request_obj=request, user_id=user.id, details={"reward": reward})
    return jsonify({
        'ok': True,
        'message': f'签到成功，已到账 {reward} 次',
        'reward': reward,
        'overview': _build_user_points_overview(user.id),
    })



@api_bp.route('/user/config', methods=['GET', 'POST'])
def user_config():
    user, err = get_auth_user()
    if err:
        return err
    if request.method == 'GET':
        config = load_user_config(user.id)
        return jsonify({'ok': True, 'config': config})
    data = request.get_json(silent=True) or {}
    config = save_user_config(user.id, data, merge=True)
    return jsonify({'ok': True, 'config': config})


@api_bp.route('/user/deduct', methods=['POST'])
def api_user_deduct():
    user, err = get_auth_user()
    if err:
        return err
    audit_security_event("user_deduct_blocked", level="warning", request_obj=request, user_id=user.id)
    return jsonify({'ok': False, 'error': '\u8be5\u63a5\u53e3\u5df2\u505c\u7528\uff0c\u8bf7\u8d70\u6b63\u5f0f\u4e1a\u52a1\u6d41\u7a0b\u6263\u6b21\u3002'}), 403


# ========== Legacy-compatible generation entry ==========
@api_bp.route('/generate', methods=['POST'])
def submit_task():
    data = request.get_json() or {}
    template_id = data.get('template_id')
    draft_path = data.get('draft_path')
    texts_input = data.get('texts_input', [])
    materials_root = data.get('materials_root')
    effects_config = data.get('effects_config', {})
    duo_config = data.get('duo_config', {})

    resolved_path, resolved_template_id, err = _resolve_draft_path(draft_path=draft_path, template_id=template_id)
    if err == 'missing':
        return jsonify({'success': False, 'error': 'draft_path required; template_id is legacy compatibility only'}), 400
    if err == 'template_not_found':
        return jsonify({'success': False, 'error': 'template not found'}), 404
    if not materials_root:
        return jsonify({'success': False, 'error': 'materials_root is required'}), 400

    task_id = uuid.uuid4().hex

    task = Task(
        id=task_id,
        user_id=session.get('user_id', 1),
        template_id=resolved_template_id,
        status='pending'
    )
    db.session.add(task)
    db.session.commit()
    app = current_app._get_current_object()
    _run_background(
        app,
        generate_video_task,
        resolved_template_id,
        materials_root,
        texts_input,
        1,
        True,
        True,
        False,
        'both',
        'order',
        'group',
        False,
        None,
        False,
        None,
        None,
        None,
        None,
        effects_config,
        duo_config,
        session.get('user_id', 1),
        resolved_path,
        task_id,
    )

    return jsonify({
        'success': True,
        'task_id': task_id,
        'draft_path': resolved_path,
        'legacy_template_mode': bool(template_id and not draft_path),
        'deprecated': bool(template_id and not draft_path),
        'message': 'template_id is legacy compatibility only; prefer draft_path'
        if template_id and not draft_path else 'ok',
    })


@api_bp.route('/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    user, err = get_auth_user()
    if err:
        return err
    task = Task.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'task not found'}), 404
    if task.user_id and task.user_id != user.id:
        return jsonify({'success': False, 'error': 'permission denied'}), 403
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


# ========== Legacy template endpoints ==========
@api_bp.route('/template/<int:template_id>/configure', methods=['POST'], endpoint='template_configure')
def configure_template_api(template_id):
    if not _legacy_template_endpoints_enabled():
        return _legacy_template_endpoint_disabled_response()
    return _deprecated_json(
        _legacy_template_payload(ok=False, message='deprecated; use /api/draft/inspect'),
        410,
    )


@api_bp.route('/template/<int:template_id>/configure', methods=['GET'], endpoint='get_template_config')
def get_template_config_api(template_id):
    if not _legacy_template_endpoints_enabled():
        return _legacy_template_endpoint_disabled_response()
    template = TemplateModel.query.get_or_404(template_id)
    materials, texts, err = _extract_template_info(template.template_path)
    if err:
        return _deprecated_json(_legacy_template_payload(ok=False, message=err), 400)
    return _deprecated_json(_legacy_template_payload(materials=materials, texts=texts))


@api_bp.route('/template/<int:template_id>/tracks', methods=['GET'])
def get_template_tracks_api(template_id):
    if not _legacy_template_endpoints_enabled():
        return _legacy_template_endpoint_disabled_response()
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
        return _deprecated_json(_legacy_template_payload(tracks=tracks, segment_counts=seg_map))
    except Exception:
        return jsonify({'tracks': []})


# ========== Batch generation API ==========
@api_bp.route('/generate-batch', methods=['POST'], endpoint='generate_batch')
def generate_batch_api():
    user, err = get_auth_user()
    if err:
        return err
    online_err = _require_remote_online('generate_batch')
    if online_err:
        return online_err

    remote_task_token = None
    if not _should_use_remote_auth():
        quota = get_or_create_quota(user.id)
        if quota.remaining <= 0:
            return jsonify({'error': 'quota exhausted'}), 403

    data = request.get_json() or {}
    draft_path = data.get('draft_path')
    materials_root = data.get('materials_root')
    texts_input = data.get('texts_input', [])
    batch_count = data.get('batch_count', 1)
    replace_materials = data.get('replace_materials', True)
    replace_texts = data.get('replace_texts', True)
    replace_audios = data.get('replace_audios', False)
    replace_type = data.get('replace_type', 'both')
    replace_mode = data.get('replace_mode', 'order')
    replace_strategy = data.get('replace_strategy', 'group')
    sequence_clip_count = data.get('sequence_clip_count', 3)
    audio_enabled = data.get('audio_enabled', False)
    audio_root = data.get('audio_root')
    export_enabled = data.get('export_enabled', False)
    export_path = data.get('export_path')
    export_format = (data.get('export_format') or '').strip().lower() or None
    export_resolution = (data.get('export_resolution') or '').strip().lower() or None
    export_fps = data.get('export_fps')
    effects_config = data.get('effects_config', {})
    duo_config = data.get('duo_config', {})

    if export_format not in (None, 'mp4', 'mov'):
        return jsonify({'error': 'unsupported export format'}), 400
    if export_resolution not in (None, '720p', '1080p', '4k'):
        return jsonify({'error': 'unsupported export resolution'}), 400
    if export_fps is not None and export_fps != '':
        try:
            export_fps = int(export_fps)
        except Exception:
            return jsonify({'error': 'invalid export fps'}), 400
        if export_fps <= 0 or export_fps > 240:
            return jsonify({'error': 'export fps out of range'}), 400
    else:
        export_fps = None

    if not draft_path:
        return jsonify({'error': 'draft_path is required'}), 400
    template_path = draft_path

    try:
        sequence_clip_count = int(sequence_clip_count)
    except Exception:
        return jsonify({'error': 'invalid sequence_clip_count'}), 400
    if sequence_clip_count < 2 or sequence_clip_count > 12:
        return jsonify({'error': 'sequence_clip_count out of range'}), 400

    if replace_strategy == 'sequence':
        if not replace_materials:
            return jsonify({'error': 'sequence mode requires replace_materials'}), 400
        replace_type = 'video'

    if replace_materials:
        replaceable_materials = _filter_replaceable_template_materials(
            template_path,
            replace_materials,
            replace_audios,
            replace_type,
            replace_strategy,
        )
        if not replaceable_materials:
            return jsonify({'error': 'no replaceable materials found in draft'}), 400
        validation_error = _validate_mix_materials_root_v2(
            materials_root,
            replace_strategy,
            replace_type,
            replaceable_materials,
        )
        if validation_error:
            return jsonify({'error': validation_error}), 400

    if export_enabled and not export_path:
        export_path = get_drafts_folder() or draft_path

    job_id = uuid.uuid4().hex
    if _should_use_remote_auth():
        remote_task_token, remote_claim_error = _remote_desktop_task_claim(job_id, 'generate_batch', 1)
        if remote_claim_error:
            return remote_claim_error

    task = Task(
        id=job_id,
        user_id=user.id,
        template_id=None,
        status='pending'
    )
    try:
        db.session.add(task)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        if remote_task_token:
            _remote_desktop_task_complete(job_id, remote_task_token, False, str(exc))
        return jsonify({'error': f'task create failed: {exc}'}), 500
    app = current_app._get_current_object()
    _run_background(
        app,
        generate_video_task,
        None,
        materials_root,
        texts_input,
        batch_count,
        replace_materials,
        replace_texts,
        replace_audios,
        replace_type,
        replace_mode,
        replace_strategy,
        sequence_clip_count,
        audio_enabled,
        audio_root,
        export_enabled,
        export_path,
        export_format,
        export_resolution,
        export_fps,
        effects_config,
        duo_config,
        user.id,
        template_path,
        job_id,
        remote_task_token,
    )

    return jsonify({'job_id': job_id})


@api_bp.route('/task/<task_id>/refund', methods=['POST'])
def refund_task_usage(task_id):
    user, err = get_auth_user()
    if err:
        return err
    audit_security_event("task_refund_blocked", level="warning", request_obj=request, user_id=user.id, details={"task_id": task_id})
    return jsonify({'ok': False, 'error': '该退款接口已停用，失败任务请走正式回退流程。'}), 403


