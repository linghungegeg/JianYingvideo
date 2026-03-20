import os
import json
import uuid
import threading
import base64
import shutil
import re
import time
from typing import List
import tkinter as tk
import requests
import logging
from datetime import datetime, timedelta
from tkinter import filedialog
from urllib.parse import parse_qs, unquote, urlparse
from flask import Blueprint, request, jsonify, current_app, session, send_file
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
from app.models.license_binding import LicenseBinding
from app.models.ai_provider import AIProvider
from app.models.user_api_key import UserApiKey
from app.models.ai_generation_log import AIGenerationLog
from app.models.ai_task import AITask
from app.models.user_material import UserMaterial
from app.models.manga_template import MangaTemplate
from app.models.manga_generation_log import MangaGenerationLog
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

api_bp = Blueprint('api', __name__, url_prefix='/api')
draft_logger = logging.getLogger("draft_inspect")
draft_logger.setLevel(logging.INFO)

_DRAFT_CONTENT_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "gbk")

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
    "daily_checkin": "每日签到",
    "manga_generate": "AI 漫剧消耗",
    "license_activate": "激活授权",
    "refund": "失败返还",
}


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
        "manga": raw["manga"] and raw["openclaw"],
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
    if path.startswith("/api/ai/manga/") and not raw_flags.get("openclaw", False):
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
    try:
        with open(path, "rb") as f:
            raw_bytes = f.read()
    except Exception as e:
        return None, e
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
    base = os.path.join(os.getcwd(), 'user_data', 'logs')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'openclaw_error.log')


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
    exts = {
        ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif",
        ".mp4", ".mov", ".m4v", ".avi", ".mkv",
        ".mp3", ".wav", ".aac", ".m4a", ".ogg"
    }
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


def get_auth_user(require_admin=False):
    token = extract_bearer_token(request)
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

def browse_folder_thread():
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory()
    root.destroy()
    return folder

def browse_file_thread():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename()
    root.destroy()
    return file_path

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

    save_path = os.path.join(current_app.root_path, '..', 'user_data', 'mcp_cache_split')
    save_path = os.path.abspath(save_path)
    os.makedirs(save_path, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    svc = JianYingService(save_path=save_path, output_path=output_dir)
    draft_name = f"split_main_{os.path.basename(draft_path.rstrip('\\/')) or uuid.uuid4().hex[:8]}"
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

            add_resp = svc.add_video_segment(
                draft_id,
                src,
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
        'workspace_title': ('workspace_title',),
        'workspace_subtitle': ('workspace_subtitle',),
        'login_title': ('login_title',),
        'login_subtitle': ('login_subtitle',),
        'locked_title': ('locked_title',),
        'locked_subtitle': ('locked_subtitle',),
        'admin_title': ('admin_title',),
        'admin_subtitle': ('admin_subtitle',),
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
            updates[target_key] = value

        if updates:
            set_configs(updates)
        settings = get_site_settings()
        return jsonify({'ok': True, 'success': True, 'settings': settings, **settings})
    return jsonify(get_site_settings())


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
            'manga': ['MANGA_FEATURES_ENABLED', 'OPENCLAW_FEATURES_ENABLED'],
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
            openclaw_payload = {
                'base_url': (openclaw_cfg.get('base_url') or '').strip(),
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
    }


def _bind_device_to_code(user: User, cdk: CdkCode, device_fingerprint: str, device_label: str = None, device_info: dict = None):
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
    db.session.commit()
    return True, None


@api_bp.route('/license/activate', methods=['POST'])
def license_activate():
    user, err = get_auth_user()
    if err:
        return err
    data = request.get_json() or {}
    code = (data.get('code') or '').strip().upper()
    device_fingerprint = (data.get('device_fingerprint') or '').strip()
    device_label = (data.get('device_label') or '').strip() or None
    device_info = data.get('device_info')

    if not code or not device_fingerprint:
        return jsonify({'ok': False, 'error': '缺少设备指纹'}), 400

    cdk = CdkCode.query.filter_by(code=code).first()
    if not cdk:
        return jsonify({'ok': False, 'error': '卡密不存在'}), 404
    if cdk.status == 3:
        return jsonify({'ok': False, 'error': '卡密已禁用'}), 400
    now = _now()
    if cdk.redeem_deadline and now > cdk.redeem_deadline:
        cdk.status = 2
        db.session.add(cdk)
        db.session.commit()
        return jsonify({'ok': False, 'error': '已过期'}), 400

    if cdk.activated_by and cdk.activated_by != user.id:
        return jsonify({'ok': False, 'error': '已被其他账号激活'}), 400

    if not cdk.activated_by:
        cdk.activated_by = user.id
        cdk.activated_at = now
        cdk.expire_at = now + timedelta(days=int(cdk.duration_days))
        cdk.status = 1
        cdk.transfer_times_left = cdk.transfer_times or 0
        db.session.add(cdk)

        quota = get_or_create_quota(user.id)
        if cdk.expire_at:
            if not quota.vip_expire_at or cdk.expire_at > quota.vip_expire_at:
                quota.vip_expire_at = cdk.expire_at
        if cdk.bonus_points:
            ratio = get_license_settings()["points_ratio"]
            add_times = int(cdk.bonus_points / max(ratio, 1))
            if add_times:
                quota.remaining = (quota.remaining or 0) + add_times
        db.session.add(quota)
        db.session.commit()
    else:
        if cdk.expire_at and now > cdk.expire_at:
            cdk.status = 2
            db.session.add(cdk)
            db.session.commit()
            return jsonify({'ok': False, 'error': '已过期'}), 400

    ok, msg = _bind_device_to_code(user, cdk, device_fingerprint, device_label, device_info)
    if not ok:
        return jsonify({'ok': False, 'error': msg}), 400

    settings = get_license_settings()
    return jsonify({
        'ok': True,
        'code': code,
        'expire_at': cdk.expire_at.isoformat() if cdk.expire_at else None,
        'transfer_times_left': cdk.transfer_times_left or 0,
        'offline_hours': settings["offline_hours"]
    })


@api_bp.route('/license/verify', methods=['POST'])
def license_verify():
    data = request.get_json() or {}
    code = (data.get('code') or '').strip().upper()
    device_fingerprint = (data.get('device_fingerprint') or '').strip()
    if not code or not device_fingerprint:
        return jsonify({'ok': False, 'error': '缺少设备指纹'}), 400
    cdk = CdkCode.query.filter_by(code=code).first()
    if not cdk or cdk.status != 1:
        return jsonify({'ok': False, 'error': '无效或未激活'}), 400
    now = _now()
    if cdk.expire_at and now > cdk.expire_at:
        cdk.status = 2
        db.session.add(cdk)
        db.session.commit()
        return jsonify({'ok': False, 'error': '已过期'}), 400
    binding = LicenseBinding.query.filter_by(code_id=cdk.id, device_fingerprint=device_fingerprint, active=True).first()
    if not binding:
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
    data = request.get_json() or {}
    code = (data.get('code') or '').strip().upper()
    device_fingerprint = (data.get('device_fingerprint') or '').strip()
    if not code or not device_fingerprint:
        return jsonify({'ok': False, 'error': '缺少设备指纹'}), 400
    cdk = CdkCode.query.filter_by(code=code).first()
    if not cdk or cdk.activated_by != user.id:
        return jsonify({'ok': False, 'error': '无权限'}), 403
    binding = LicenseBinding.query.filter_by(code_id=cdk.id, device_fingerprint=device_fingerprint, active=True).first()
    if not binding:
        return jsonify({'ok': False, 'error': '设备未绑定'}), 400
    binding.active = False
    binding.unbound_at = _now()
    db.session.add(binding)
    db.session.commit()
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

    return jsonify({
        'ok': True,
        'total_remaining': int(total_remaining),
        'total_generated': int(total_generated),
        'quota_users': int(quota_users),
        'active_trial_users': int(active_trial_users),
        'total_users': int(total_users),
    })


@api_bp.route('/admin/license-settings', methods=['GET', 'POST'])
def admin_license_settings():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    if request.method == 'POST':
        data = request.get_json() or {}
        for key in ("license_offline_hours", "license_transfer_cooldown_hours", "license_code_length", "license_points_ratio", "manga_generate_cost", "daily_checkin_reward"):
            if key in data:
                set_config(key, str(data.get(key)))
    settings = get_license_settings()
    settings['manga_generate_cost'] = int(get_config('manga_generate_cost', '1') or 1)
    return jsonify({"ok": True, "settings": settings})
    return jsonify({"ok": True, "settings": settings})


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
    if not kw:
        return jsonify({"ok": True, "items": []})
    query = User.query
    if kw.isdigit():
        query = query.filter(User.id == int(kw))
    else:
        like = f"%{kw}%"
        query = query.filter(or_(User.username.like(like), User.email.like(like)))
    items = []
    for u in query.limit(20).all():
        items.append({"id": u.id, "username": u.username, "email": u.email, "ref_code": u.ref_code})
    return jsonify({"ok": True, "items": items})


@api_bp.route('/admin/logs', methods=['GET'])
def admin_logs_api():
    user, err = get_auth_user(require_admin=True)
    if err:
        return err
    logs = read_generate_logs(limit=500)
    logs = list(reversed(logs))
    return jsonify({"ok": True, "items": logs})


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

    return jsonify({
        'ok': True,
        'output_dir': output_dir,
        'total': len(results),
        'success_count': success_count,
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
            'params': params,
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
    base_url = (data.get('base_url') or '').strip()
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
    base_url = (data.get('base_url') or '').strip()
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
        key.base_url = base_url.strip() or None
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
    base_url = (data.get('base_url') or '').strip()
    token = (data.get('token') or '').strip()
    if not base_url:
        return jsonify({'ok': False, 'error': 'Missing service base_url'}), 400
    client = OpenClawClient(base_url, token)
    ok = client.test_connection()
    if ok:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Connection failed'}), 400


@api_bp.route('/ai/manga/generate', methods=['POST'])
def ai_manga_generate():
    user, err = get_auth_user()
    if err:
        return err
    if not _effective_runtime_features().get("manga"):
        return jsonify({'ok': False, 'error': 'AI manga feature is disabled in this build'}), 404
    data = request.get_json(silent=True) or {}
    config = load_user_config(user.id) or {}
    openclaw_cfg = config.get('openclaw') or {}
    base_url = (openclaw_cfg.get('base_url') or '').strip()
    token = (openclaw_cfg.get('token') or '').strip()
    if not base_url:
        return jsonify({'ok': False, 'error': 'OpenClaw base_url not configured'}), 400

    cost = int(get_config('manga_generate_cost', '1') or 1)
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
    except Exception as e:
        _log_openclaw_error(user.id, params, str(e))
        return jsonify({'ok': False, 'error': f'OpenClaw call failed: {e}'}), 500

    user_material_dir = get_user_material_dir(user.id)
    if not user_material_dir:
        return jsonify({'ok': False, 'error': 'Material folder not configured'}), 400

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

    # deduct quota after success
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

    return jsonify({
        'ok': True,
        'project_id': project_id,
        'project_name': project_name,
        'material_ids': material_ids,
        'frames': saved_frames,
        'video': video_payload,
        'quota': quota_to_dict(quota),
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
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    email = (data.get('email') or '').strip() or None
    auto_login = data.get('auto_login', True)
    ref_code = (data.get('ref_code') or '').strip().upper()

    if not username or not password:
        return jsonify({'ok': False, 'error': 'username and password are required'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'ok': False, 'error': 'username already exists'}), 400
    if email and User.query.filter_by(email=email).first():
        return jsonify({'ok': False, 'error': 'email already exists'}), 400

    referrer_id = None
    if ref_code:
        ref_user = User.query.filter_by(ref_code=ref_code).first()
        if ref_user:
            referrer_id = ref_user.id

    user = User(username=username, email=email, role='user')
    user.referrer_id = referrer_id
    user.password_hash = generate_password_hash(password)
    db.session.add(user)
    _ensure_user_ref_code(user)
    db.session.commit()

    quota = get_or_create_quota(user.id)
    token_obj = issue_token(user.id) if auto_login else None
    return jsonify({
        'ok': True,
        'message': 'register success',
        'token': token_obj.token if token_obj else None,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'ref_code': user.ref_code,
            'referrer_id': user.referrer_id,
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
    _ensure_user_ref_code(user, commit=True)

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
            'ref_code': user.ref_code,
            'referrer_id': user.referrer_id,
            **quota_to_dict(quota)
        }
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
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'ref_code': user.ref_code,
            'referrer_id': user.referrer_id,
            **quota_to_dict(quota)
        }
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
    ok, msg, quota = deduct_quota(user.id, amount=1)
    if not ok:
        return jsonify({'ok': False, 'error': msg, **quota_to_dict(quota)}), 400
    return jsonify({'ok': True, **quota_to_dict(quota)})


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

    if replace_materials:
        materials, _texts, extract_err = _extract_template_info(template_path)
        if extract_err:
            return jsonify({'error': extract_err}), 400
        if not materials:
            return jsonify({'error': 'no replaceable materials found in draft'}), 400
        validation_error = _validate_mix_materials_root(
            materials_root,
            replace_strategy,
            replace_type,
            materials,
        )
        if validation_error:
            return jsonify({'error': validation_error}), 400

    if export_enabled and not export_path:
        export_path = get_drafts_folder() or draft_path

    job_id = uuid.uuid4().hex

    task = Task(
        id=job_id,
        user_id=user.id,
        template_id=None,
        status='pending'
    )
    db.session.add(task)
    db.session.commit()
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
    )

    return jsonify({'job_id': job_id})


@api_bp.route('/task/<task_id>/refund', methods=['POST'])
def refund_task_usage(task_id):
    user, err = get_auth_user()
    if err:
        return err
    task = Task.query.get(task_id)
    if not task:
        return jsonify({'ok': False, 'error': 'task not found'}), 404
    if task.user_id and task.user_id != user.id:
        return jsonify({'ok': False, 'error': 'permission denied'}), 403
    if task.status != 'failed':
        return jsonify({'ok': False, 'error': 'only failed tasks can be refunded'}), 400
    if getattr(task, "refunded", False):
        return jsonify({'ok': False, 'error': 'task already refunded'}), 400
    try:
        quota = get_or_create_quota(user.id)
        quota.remaining = (quota.remaining or 0) + 1
        setattr(task, "refunded", True)
        db.session.add(quota)
        db.session.add(task)
        db.session.commit()
        return jsonify({'ok': True, **quota_to_dict(quota)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': f'refund failed: {e}'}), 500


