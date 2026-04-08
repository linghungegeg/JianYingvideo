import os
import shutil
import uuid
import json
import random
import logging
import threading
import subprocess
import base64
import time
import re

try:
    from rq import get_current_job
except Exception:  # pragma: no cover - local desktop runtime can run without RQ
    def get_current_job():
        return None
from app import create_app
from app.extensions import db
from app.models.task import Task
from app.models.template_model import TemplateModel
from app.models.task_effect_log import TaskEffectLog
from app.services.jianying.local_draft_service import (
    build_attachment_material_entries as _service_build_attachment_material_entries,
    find_draft_content_files as _service_find_draft_content_files,
    is_valid_draft_project_path as _service_is_valid_draft_project_path,
    load_draft_content as _service_load_draft_content,
    normalize_draft_project_path as _service_normalize_draft_project_path,
    resolve_active_draft_payload as _service_resolve_active_draft_payload,
)
from app.services.jianying.official_draft_replace_service import replace_official_draft
from app.utils.helpers import get_drafts_folder, pick_preferred_draft_root
from app.utils.ffmpeg_utils import find_ffmpeg
from app.utils.remote_service import call_remote_api

# MCP 路径当前不匹配实际目录结构，避免误用导致退回字符串替换
MCP_AVAILABLE = False
_LOCAL_TASK_CONTEXT = threading.local()
_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
_VIDEO_EXTS = ('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v')
_AUDIO_EXTS = ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')
_ALL_MEDIA_EXTS = _IMAGE_EXTS + _VIDEO_EXTS + _AUDIO_EXTS
_VF_GENERATED_MARKER = ".vf_generated.json"
_VF_MANAGED_RUN_KEEP = 0
_DRAFT_CONTENT_ENCODINGS = (
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "gb18030",
    "gbk",
)


def _quiet_subprocess_kwargs():
    kwargs = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    use_show_window = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    show_window_hidden = getattr(subprocess, "SW_HIDE", 0)
    if startupinfo_cls and use_show_window:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= use_show_window
        startupinfo.wShowWindow = show_window_hidden
        kwargs["startupinfo"] = startupinfo
    return kwargs


def normalize_draft_project_path(template_path):
    return _service_normalize_draft_project_path(template_path)


def find_draft_content_files(template_path):
    return _service_find_draft_content_files(template_path)


def is_valid_draft_project_path(template_path):
    return _service_is_valid_draft_project_path(template_path)


def _resolve_active_draft_payload(data):
    return _service_resolve_active_draft_payload(data)


def _load_json_with_encodings(path):
    last_err = None
    raw_bytes = None
    for attempt in range(3):
        try:
            with open(path, "rb") as handle:
                raw_bytes = handle.read()
            break
        except Exception as exc:
            last_err = exc
            if attempt >= 2:
                return None, exc
            time.sleep(0.15)
    if not raw_bytes:
        return None, ValueError("empty file")

    for encoding in _DRAFT_CONTENT_ENCODINGS:
        try:
            raw = raw_bytes.decode(encoding).lstrip()
            if not raw or raw[0] not in "{[":
                continue
            decoder = json.JSONDecoder()
            data, _end = decoder.raw_decode(raw)
            return data, None
        except Exception as exc:
            last_err = exc

    try:
        b64_text = raw_bytes.decode("ascii", errors="ignore").strip()
        if b64_text:
            decoded = base64.b64decode(b64_text, validate=True)
            for encoding in _DRAFT_CONTENT_ENCODINGS:
                try:
                    raw = decoded.decode(encoding).lstrip()
                    if not raw or raw[0] not in "{[":
                        continue
                    decoder = json.JSONDecoder()
                    data, _end = decoder.raw_decode(raw)
                    return data, None
                except Exception as exc:
                    last_err = exc
    except Exception as exc:
        last_err = exc
    return None, ValueError(str(last_err or "non-json or encrypted content"))


def load_draft_content(template_path):
    return _service_load_draft_content(template_path)


def _build_file_index(root_path):
    index = {}
    for root, _dirs, files in os.walk(root_path):
        for fname in files:
            key = fname.lower()
            if key not in index:
                index[key] = os.path.join(root, fname)
    return index

def _to_bool_flag(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text in {"0", "false", "off", "no", "n", "none", "null", "undefined"}:
        return False
    if text in {"1", "true", "on", "yes", "y"}:
        return True
    return bool(text)


def _normalize_replace_types(replace_type):
    explicit_empty = False
    if isinstance(replace_type, dict):
        raw_items = [key for key, enabled in replace_type.items() if _to_bool_flag(enabled)]
        explicit_empty = len(replace_type) > 0 and not raw_items
    elif isinstance(replace_type, (list, tuple, set)):
        raw_items = replace_type
        explicit_empty = len(list(replace_type)) == 0
    else:
        raw_text = str(replace_type or "both")
        for sep in ("|", ";", "/", " "):
            raw_text = raw_text.replace(sep, ",")
        raw_items = raw_text.split(",")
    alias_map = {
        "image": "image",
        "images": "image",
        "img": "image",
        "photo": "image",
        "photos": "image",
        "pic": "image",
        "pics": "image",
        "图片": "image",
        "图像": "image",
        "video": "video",
        "videos": "video",
        "movie": "video",
        "movies": "video",
        "视频": "video",
        "audio": "audio",
        "audios": "audio",
        "music": "audio",
        "音频": "audio",
        "音乐": "audio",
    }
    normalized = []
    seen = set()
    for item in raw_items:
        value = str(item or "").strip().lower()
        if not value:
            continue
        if value == "both":
            for kind in ("image", "video"):
                if kind not in seen:
                    normalized.append(kind)
                    seen.add(kind)
            continue
        value = alias_map.get(value, value)
        if value in {"image", "video", "audio"} and value not in seen:
            normalized.append(value)
            seen.add(value)
    if explicit_empty:
        return []
    if not normalized:
        return ["image", "video"]
    return normalized

def _list_media_files(root_path, replace_type):
    if not root_path or not os.path.exists(root_path):
        return []
    replace_types = set(_normalize_replace_types(replace_type))
    files = []
    for root, _dirs, fnames in os.walk(root_path):
        for fname in fnames:
            ext = os.path.splitext(fname)[1].lower()
            matches = False
            if 'image' in replace_types and ext in _IMAGE_EXTS:
                matches = True
            if 'video' in replace_types and ext in _VIDEO_EXTS:
                matches = True
            if 'audio' in replace_types and ext in _AUDIO_EXTS:
                matches = True
            if not matches:
                continue
            files.append(os.path.join(root, fname))
    return files

def _list_subfolders(root_path):
    if not root_path or not os.path.exists(root_path):
        return []
    folders = []
    for name in os.listdir(root_path):
        p = os.path.join(root_path, name)
        if os.path.isdir(p):
            folders.append(p)
    folders.sort()
    return folders

def _normalize_name(name):
    return os.path.splitext(name or '')[0].strip().lower()


def _template_material_matches_type(name, source_kind, replace_type, replace_strategy=None):
    ext = os.path.splitext(name or '')[1].lower()
    replace_types = set(_normalize_replace_types(replace_type))
    if replace_strategy == 'sequence':
        if source_kind:
            return source_kind == 'videos'
        return ext in _VIDEO_EXTS
    if replace_types == {'image'}:
        if source_kind == 'audios':
            return False
        if source_kind == 'images':
            return True
        return ext in _IMAGE_EXTS
    if replace_types == {'video'}:
        if source_kind:
            return source_kind == 'videos'
        return ext in _VIDEO_EXTS
    if replace_types == {'audio'}:
        if source_kind:
            return source_kind == 'audios'
        return ext in _AUDIO_EXTS
    if replace_types == {'image', 'video'}:
        if source_kind == 'audios':
            return False
        if source_kind in ('videos', 'images'):
            return True
        return ext in (_IMAGE_EXTS + _VIDEO_EXTS)
    if source_kind in ('videos', 'images', 'audios'):
        if source_kind == 'images':
            return 'image' in replace_types
        if source_kind == 'videos':
            return 'video' in replace_types
        if source_kind == 'audios':
            return 'audio' in replace_types
    if ext in _IMAGE_EXTS:
        return 'image' in replace_types
    if ext in _VIDEO_EXTS:
        return 'video' in replace_types
    if ext in _AUDIO_EXTS:
        return 'audio' in replace_types
    return False


def _build_sequence_output_path(draft_root, fname, source_files, slot_index):
    seq_root = os.path.join(draft_root, "_sequence_slots")
    os.makedirs(seq_root, exist_ok=True)
    source_ext = os.path.splitext((source_files or [''])[0])[1].lower() or '.mp4'
    base_name = _normalize_name(fname) or f"slot_{slot_index + 1}"
    return os.path.join(seq_root, f"{slot_index + 1:02d}_{base_name}{source_ext}")

def _build_partition_folder_map(root_path):
    folders = _list_subfolders(root_path)
    mapping = {}
    for folder in folders:
        key = _normalize_name(os.path.basename(folder))
        if key and key not in mapping:
            mapping[key] = folder
    return mapping


def _resolve_generated_drafts_root(template_path, export_path=None):
    explicit = str(export_path or "").strip()
    if explicit:
        return explicit

    normalized_template_path = normalize_draft_project_path(template_path)
    if normalized_template_path:
        parent = os.path.dirname(normalized_template_path.rstrip("\\/"))
        fallback_root = parent or normalized_template_path
    else:
        fallback_root = ""

    preferred = pick_preferred_draft_root(fallback_root)
    if preferred:
        return preferred
    return fallback_root

def _pick_from_list(files, mode, seed_index):
    if not files:
        return None
    if mode == 'random':
        return random.choice(files)
    return files[seed_index % len(files)]


def _pick_sequence_files(files, mode, seed_index, clip_count):
    if not files:
        return []
    if mode == 'random':
        if len(files) >= clip_count:
            return random.sample(files, clip_count)
        return [random.choice(files) for _ in range(clip_count)]
    return [files[(seed_index + offset) % len(files)] for offset in range(clip_count)]


def _find_material_target_file(root_path, fname, material_map):
    for root, _dirs, files in os.walk(root_path):
        if fname in files:
            return os.path.join(root, fname)
    internal_id = material_map.get(fname)
    if internal_id:
        for root, _dirs, files in os.walk(root_path):
            if internal_id in files:
                return os.path.join(root, internal_id)
    return None


def _ensure_draft_material_target_file(root_path, fname, source_kind=None, material_map=None):
    target_file = _find_material_target_file(root_path, fname, material_map or {})
    if target_file:
        return target_file

    safe_name = os.path.basename(str(fname or "").strip())
    if not safe_name:
        return None

    folder_by_source = {
        'videos': os.path.join('materials', 'video'),
        'images': os.path.join('materials', 'image'),
        'audios': os.path.join('materials', 'audio'),
    }
    relative_dir = folder_by_source.get(source_kind or 'videos', os.path.join('materials', 'video'))
    target_dir = os.path.join(root_path, relative_dir)
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, safe_name)


def _compose_slot_sequence(files, output_path):
    if not files or not output_path:
        return None
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if len(files) == 1:
        shutil.copy2(files[0], output_path)
        return output_path

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        shutil.copy2(files[0], output_path)
        return output_path

    list_file = os.path.join(
        os.path.dirname(output_path),
        f"_sequence_{uuid.uuid4().hex[:8]}.txt",
    )
    try:
        with open(list_file, 'w', encoding='utf-8') as fh:
            for item in files:
                safe_path = os.path.abspath(item).replace("'", "'\\''")
                fh.write(f"file '{safe_path}'\n")

        commands = [
            [ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', list_file, '-c', 'copy', output_path],
            [ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', list_file, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-c:a', 'aac', '-b:a', '192k', output_path],
        ]
        for cmd in commands:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                **_quiet_subprocess_kwargs(),
            )
            if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path
    except Exception as exc:
        logging.warning("compose slot sequence failed: %s", exc)
    finally:
        try:
            if os.path.exists(list_file):
                os.remove(list_file)
        except Exception:
            pass

    shutil.copy2(files[0], output_path)
    return output_path

def _update_material_paths(draft_data, file_index):
    for payload in _iter_draft_payloads(draft_data):
        materials = payload.get('materials', {})
        for media_type in ('videos', 'images', 'audios'):
            items = materials.get(media_type, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                path = item.get('path') or item.get('file_path')
                if not path:
                    continue
                fname = os.path.basename(path)
                if not fname:
                    continue
                new_path = file_index.get(fname.lower())
                if new_path:
                    item['path'] = new_path
                    if 'file_path' in item:
                        item['file_path'] = new_path

def _update_material_paths_from_user_files(draft_data, user_files, material_map):
    if not user_files:
        return
    for payload in _iter_draft_payloads(draft_data):
        materials = payload.get('materials', {})
        for media_type in ('videos', 'images', 'audios'):
            items = materials.get(media_type, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = item.get('id')
                material_name = item.get('material_name')
                path = item.get('path') or item.get('file_path')
                fname = None
                if material_name:
                    fname = material_name
                elif path:
                    fname = os.path.basename(path)

                new_path = None
                if fname and fname.lower() in user_files:
                    new_path = user_files[fname.lower()]
                elif item_id and material_map:
                    for name, mid in material_map.items():
                        if mid == item_id and name.lower() in user_files:
                            new_path = user_files[name.lower()]
                            break

                if new_path:
                    item['path'] = new_path
                    if 'file_path' in item:
                        item['file_path'] = new_path

def _safe_update_style_ranges(styles, total_len):
    if not isinstance(styles, list) or total_len is None:
        return
    for style in styles:
        if not isinstance(style, dict):
            continue
        if isinstance(style.get('range'), list) and len(style['range']) == 2:
            start, end = style['range']
            try:
                start = max(0, int(start))
                end = max(0, int(end))
            except Exception:
                continue
            start = min(start, total_len)
            end = min(end, total_len)
            if end < start:
                end = start
            style['range'] = [start, end]
        if isinstance(style.get('ranges'), list):
            fixed = []
            for r in style['ranges']:
                if not isinstance(r, list) or len(r) != 2:
                    continue
                try:
                    start = max(0, int(r[0]))
                    end = max(0, int(r[1]))
                except Exception:
                    continue
                start = min(start, total_len)
                end = min(end, total_len)
                if end < start:
                    end = start
                fixed.append([start, end])
            style['ranges'] = fixed


def _iter_draft_payloads(draft_data):
    visited = set()

    def _walk(payload):
        if not isinstance(payload, dict):
            return
        ident = id(payload)
        if ident in visited:
            return
        visited.add(ident)
        yield payload
        materials = payload.get('materials', {})
        if not isinstance(materials, dict):
            return
        for item in materials.get('drafts', []) or []:
            if not isinstance(item, dict):
                continue
            child = item.get('draft')
            if isinstance(child, dict):
                yield from _walk(child)

    yield from _walk(draft_data)


def _replace_word_timing_payload(words_payload, new_text):
    if not isinstance(words_payload, dict):
        return False

    texts = words_payload.get('text')
    starts = words_payload.get('start_time')
    ends = words_payload.get('end_time')

    if not isinstance(texts, list):
        return False

    first_start = 0
    last_end = 0
    if isinstance(starts, list) and starts:
        try:
            first_start = int(starts[0] or 0)
        except Exception:
            first_start = 0
    if isinstance(ends, list) and ends:
        try:
            last_end = int(ends[-1] or 0)
        except Exception:
            last_end = first_start
    if last_end < first_start:
        last_end = first_start

    words_payload['text'] = [new_text]
    if isinstance(starts, list):
        words_payload['start_time'] = [first_start]
    if isinstance(ends, list):
        words_payload['end_time'] = [last_end]
    return True


def _extract_template_runtime_info_from_meta(template_path):
    materials = []
    material_map = {}
    texts_info = []
    material_sources = {}
    attachment_entries = _build_attachment_material_entries(template_path)

    def _apply_entries(entries):
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            if name not in materials:
                materials.append(name)
            source_kind = str(entry.get("source") or "videos").strip() or "videos"
            material_sources[name] = source_kind
            material_id = entry.get("material_id")
            if material_id:
                material_map[name] = material_id

    meta_path = os.path.join(template_path, "draft_meta_info.json")
    if not os.path.exists(meta_path):
        _apply_entries(attachment_entries)
        return materials, material_map, texts_info, material_sources
    data, err = _load_json_with_encodings(meta_path)
    if err is not None or not isinstance(data, dict):
        _apply_entries(attachment_entries)
        return materials, material_map, texts_info, material_sources

    source_map = {
        "photo": "videos",
        "image": "images",
        "video": "videos",
        "music": "audios",
        "audio": "audios",
    }
    prefix_map = {
        "videos": "video_slot",
        "images": "image_slot",
        "audios": "audio_slot",
    }
    slot_counters = {"videos": 0, "images": 0, "audios": 0}
    for group in data.get("draft_materials", []) or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("value", []) or []:
            if not isinstance(item, dict):
                continue
            raw_type = str(item.get("metetype") or item.get("type") or "").strip().lower()
            if raw_type in {"text", "subtitle"}:
                continue
            source_kind = source_map.get(raw_type, "videos")
            raw_path = item.get("file_Path") or item.get("file_path") or item.get("path") or ""
            name = os.path.basename(raw_path) if raw_path else ""
            if not name:
                name = os.path.basename(
                    item.get("extra_info") or item.get("name") or item.get("file_name") or ""
                )
            if not name:
                slot_counters[source_kind] += 1
                material_id = str(item.get("id") or "").strip()
                suffix = re.sub(r"[^0-9A-Za-z._-]+", "_", material_id).strip("_")
                if not suffix:
                    suffix = f"{slot_counters[source_kind]:02d}"
                name = f"{prefix_map.get(source_kind, 'material_slot')}_{suffix}"
            if not name:
                continue
            if name not in materials:
                materials.append(name)
            material_sources[name] = source_kind
            material_id = item.get("id")
            if material_id:
                material_map[name] = material_id

    if not materials:
        _apply_entries(attachment_entries)

    return materials, material_map, texts_info, material_sources


def _extract_template_runtime_info(template_path):
    materials = []
    material_map = {}
    material_sources = {}
    texts_info = []
    if not template_path:
        return materials, material_map, texts_info, material_sources
    normalized_path = normalize_draft_project_path(template_path)
    data, err, _diagnostics = load_draft_content(normalized_path)
    if err or not isinstance(data, dict):
        return _extract_template_runtime_info_from_meta(normalized_path)

    data = _resolve_active_draft_payload(data)
    mats = data.get('materials', {})
    for media_type in ('videos', 'images', 'audios'):
        for item in mats.get(media_type, []) or []:
            if not isinstance(item, dict):
                continue
            path = item.get('path') or item.get('file_path') or ''
            mid = item.get('id')
            if path:
                name = os.path.basename(path)
                if name and name not in materials:
                    materials.append(name)
                if name and name not in material_sources:
                    material_sources[name] = media_type
                if name and mid:
                    material_map[name] = mid

    for item in mats.get('texts', []) or []:
        if not isinstance(item, dict):
            continue
        default_text = item.get('recognize_text') or item.get('content') or ''
        texts_info.append({
            'index': len(texts_info),
            'default': default_text,
            'material_id': item.get('id')
        })

    return materials, material_map, texts_info, material_sources

    if not styles:
        return
    for style in styles:
        if not isinstance(style, dict):
            continue
        rng = style.get('range')
        if not (isinstance(rng, list) and len(rng) == 2):
            continue
        start = min(max(int(rng[0]), 0), total_len)
        end = min(max(int(rng[1]), 0), total_len)
        if end < start:
            end = start
        style['range'] = [start, end]
    # 确保最后一个范围覆盖新文本长度
    for style in reversed(styles):
        rng = style.get('range')
        if isinstance(rng, list) and len(rng) == 2:
            style['range'] = [min(rng[0], total_len), total_len]
            break

def _replace_texts_with_style(draft_data, texts_input, texts_info):
    replaced = 0
    for payload in _iter_draft_payloads(draft_data):
        materials = payload.get('materials', {})
        text_materials = materials.get('texts', [])
        if not isinstance(text_materials, list) or not text_materials:
            continue

        track_material_ids = []
        for track in payload.get('tracks', []):
            if track.get('type') != 'text':
                continue
            for seg in track.get('segments', []):
                mid = seg.get('material_id')
                if mid:
                    track_material_ids.append(mid)

        text_by_id = {}
        for item in text_materials:
            if isinstance(item, dict) and item.get('id'):
                text_by_id[item['id']] = item

        payload_replaced_ids = set()
        for user_text in texts_input:
            if not isinstance(user_text, dict):
                continue
            idx = user_text.get('index')
            contents = user_text.get('contents') or []
            new_text = contents[0] if contents else ''
            if new_text is None:
                continue
            new_text = str(new_text)

            target_item = None
            material_id = None
            if isinstance(texts_info, list) and idx is not None and 0 <= idx < len(texts_info):
                info = texts_info[idx]
                if isinstance(info, dict):
                    material_id = info.get('material_id')
            if material_id and material_id in text_by_id:
                target_item = text_by_id[material_id]
            elif idx is not None and 0 <= idx < len(track_material_ids):
                track_mid = track_material_ids[idx]
                target_item = text_by_id.get(track_mid)
            elif idx is not None and 0 <= idx < len(text_materials):
                target_item = text_materials[idx]

            if not isinstance(target_item, dict):
                continue

            content_str = target_item.get('content')
            if content_str:
                try:
                    content_json = json.loads(content_str)
                    content_json['text'] = new_text
                    styles = content_json.get('styles', [])
                    _safe_update_style_ranges(styles, len(new_text))
                    target_item['content'] = json.dumps(content_json, ensure_ascii=False)
                except Exception:
                    pass

            target_item['recognize_text'] = new_text
            _replace_word_timing_payload(target_item.get('words'), new_text)
            _replace_word_timing_payload(target_item.get('current_words'), new_text)
            target_item['_vf_new_text'] = new_text
            material_key = target_item.get('id') or f"idx:{idx}"
            if material_key not in payload_replaced_ids:
                payload_replaced_ids.add(material_key)
                replaced += 1

    return replaced

def _update_subtitle_taskinfo(draft_data):
    updated = 0
    for payload in _iter_draft_payloads(draft_data):
        text_by_task = {}
        for txt in payload.get('materials', {}).get('texts', []):
            if isinstance(txt, dict):
                task_id = txt.get('recognize_task_id')
                new_text = txt.get('_vf_new_text')
                if task_id and new_text is not None:
                    text_by_task[task_id] = new_text

        config = payload.get('config', {})
        subtitle_taskinfo = config.get('subtitle_taskinfo', [])
        if not isinstance(subtitle_taskinfo, list):
            continue

        for item in subtitle_taskinfo:
            if not isinstance(item, dict):
                continue
            task_id = item.get('id')
            if task_id in text_by_task:
                try:
                    content = item.get('content')
                    if not content:
                        continue
                    content_json = json.loads(content)
                    utterances = content_json.get('utterances', [])
                    if utterances:
                        for u in utterances:
                            u['text'] = text_by_task[task_id]
                            words = u.get('words')
                            if isinstance(words, list) and words:
                                first_word = words[0] if isinstance(words[0], dict) else {}
                                last_word = words[-1] if isinstance(words[-1], dict) else {}
                                start_time = first_word.get('start_time', u.get('start_time', 0))
                                end_time = last_word.get('end_time', u.get('end_time', start_time))
                                u['words'] = [{
                                    'start_time': start_time,
                                    'end_time': end_time,
                                    'text': text_by_task[task_id],
                                    'attribute': first_word.get('attribute') if isinstance(first_word, dict) else {},
                                }]
                    content_json['utterances'] = utterances
                    item['content'] = json.dumps(content_json, ensure_ascii=False)
                    updated += 1
                except Exception:
                    continue
    return updated

def _clear_temp_text_marks(draft_data):
    for payload in _iter_draft_payloads(draft_data):
        for txt in payload.get('materials', {}).get('texts', []):
            if isinstance(txt, dict) and '_vf_new_text' in txt:
                del txt['_vf_new_text']

def _update_track_text_segments(draft_data):
    updated = 0
    for payload in _iter_draft_payloads(draft_data):
        text_by_id = {}
        for txt in payload.get('materials', {}).get('texts', []):
            if isinstance(txt, dict) and txt.get('id') and txt.get('_vf_new_text') is not None:
                text_by_id[txt['id']] = txt['_vf_new_text']

        for track in payload.get('tracks', []):
            if track.get('type') != 'text':
                continue
            for seg in track.get('segments', []):
                mid = seg.get('material_id')
                if not mid or mid not in text_by_id:
                    continue
                new_text = text_by_id[mid]
                if seg.get('content'):
                    try:
                        content_json = json.loads(seg.get('content'))
                        if isinstance(content_json, dict):
                            content_json['text'] = new_text
                            styles = content_json.get('styles', [])
                            _safe_update_style_ranges(styles, len(new_text))
                            seg['content'] = json.dumps(content_json, ensure_ascii=False)
                            updated += 1
                    except Exception:
                        continue
    return updated


def _build_text_replacement_map(texts_input):
    replacements = {}
    if not isinstance(texts_input, list):
        return replacements
    for item in texts_input:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        contents = item.get("contents") or []
        if not isinstance(idx, int) or not contents:
            continue
        replacement = contents[0]
        if replacement is None:
            continue
        replacements[idx] = str(replacement)
    return replacements


def _resolve_batch_texts_input(texts_input, batch_index):
    if not isinstance(texts_input, list):
        return texts_input

    resolved = []
    for item in texts_input:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        contents = item.get("contents") or []
        if not isinstance(idx, int):
            continue
        if not isinstance(contents, list):
            contents = [contents]
        normalized = []
        for content in contents:
            if content is None:
                continue
            normalized.append(str(content))
        if not normalized:
            normalized = [""]
        selected_index = min(max(int(batch_index or 0), 0), len(normalized) - 1)
        resolved.append(
            {
                "index": idx,
                "contents": [normalized[selected_index]],
                "rule": item.get("rule") or "order",
            }
        )
    return resolved


def _collect_user_material_overrides(
    material_names,
    materials_root,
    replace_type,
    replace_mode,
    replace_strategy,
    sequence_clip_count,
    batch_index,
    sequence_cache_root,
    selection_offset=0,
):
    user_files = {}
    folder_cache = {}
    pool_files = []
    group_folders = []
    partition_map = {}
    effective_batch_index = max(0, int(selection_offset or 0)) + max(0, int(batch_index or 0))

    if replace_strategy == 'mix':
        pool_files = _list_media_files(materials_root, replace_type)
    elif replace_strategy == 'partition':
        partition_map = _build_partition_folder_map(materials_root)
    else:
        # In group mode, only folders that contain media matching selected replace_type
        # should participate in slot assignment.
        group_folders = [
            folder
            for folder in _list_subfolders(materials_root)
            if _list_media_files(folder, replace_type)
        ]

    for idx, fname in enumerate(material_names or []):
        user_file = None
        if replace_strategy == 'mix':
            user_file = _pick_from_list(pool_files, replace_mode, effective_batch_index + idx)
        elif replace_strategy == 'sequence':
            if not group_folders:
                group_folders = _list_subfolders(materials_root)
            if idx < len(group_folders):
                folder = group_folders[idx]
                files = folder_cache.get(folder)
                if files is None:
                    files = _list_media_files(folder, 'video')
                    folder_cache[folder] = files
                sequence_files = _pick_sequence_files(files, replace_mode, effective_batch_index, sequence_clip_count)
                if sequence_files:
                    composed_target = _build_sequence_output_path(
                        sequence_cache_root,
                        fname,
                        sequence_files,
                        idx,
                    )
                    composed_file = _compose_slot_sequence(sequence_files, composed_target)
                    if composed_file:
                        user_files[fname.lower()] = composed_file
                        continue
                user_file = sequence_files[0] if sequence_files else None
        elif replace_strategy == 'partition':
            folder = partition_map.get(_normalize_name(fname))
            if folder:
                files = folder_cache.get(folder)
                if files is None:
                    files = _list_media_files(folder, replace_type)
                    folder_cache[folder] = files
                user_file = _pick_from_list(files, replace_mode, effective_batch_index)
        else:
            if not group_folders:
                if not pool_files:
                    pool_files = _list_media_files(materials_root, replace_type)
                user_file = _pick_from_list(pool_files, replace_mode, effective_batch_index + idx)
            elif len(group_folders) > 0:
                if idx < len(group_folders):
                    folder = group_folders[idx]
                    files = folder_cache.get(folder)
                    if files is None:
                        files = _list_media_files(folder, replace_type)
                        folder_cache[folder] = files
                    user_file = _pick_from_list(files, replace_mode, effective_batch_index)

        if user_file:
            user_files[fname.lower()] = user_file

    return user_files


def _build_material_override_summary(material_names, material_replacements, sample_limit=6):
    summary_items = []
    seen = set()
    for material_name in material_names or []:
        key = str(material_name or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        override_path = (material_replacements or {}).get(key)
        if not override_path:
            continue
        summary_items.append({
            "slot_name": str(material_name or "").strip(),
            "path": str(override_path or "").strip(),
            "file_name": os.path.basename(str(override_path or "").strip()),
        })

    total_count = len(summary_items)
    expected_count = len([item for item in (material_names or []) if str(item or "").strip()])
    return {
        "expected_count": expected_count,
        "selected_count": total_count,
        "missing_count": max(0, expected_count - total_count),
        "selected_items": summary_items[:max(1, int(sample_limit or 1))],
        "truncated_count": max(0, total_count - max(1, int(sample_limit or 1))),
    }


def _build_material_pool_warning(
    materials_root,
    replace_type,
    replace_mode,
    replace_strategy,
    batch_count,
    material_slot_count,
    material_names=None,
):
    if replace_strategy not in {"mix", "group", "sequence", "partition"}:
        return None

    try:
        batch_count = max(1, int(batch_count or 1))
    except Exception:
        batch_count = 1
    try:
        material_slot_count = max(0, int(material_slot_count or 0))
    except Exception:
        material_slot_count = 0

    if batch_count <= 1 or material_slot_count <= 0:
        return None
    if str(replace_mode or "").strip().lower() == "random":
        return None

    if replace_strategy == "mix":
        pool_size = len(_list_media_files(materials_root, replace_type))
        if pool_size <= 0:
            return None
        required_span = batch_count + max(0, material_slot_count - 1)
        if pool_size < required_span:
            return f"当前素材池共 {pool_size} 个素材，批量 {batch_count} 份、每份约 {material_slot_count} 个槽位，后续批次会循环复用素材。"
        return None

    subfolders = _list_subfolders(materials_root)
    if not subfolders:
        return None

    if replace_strategy == "group":
        undersized = []
        for folder in subfolders[:material_slot_count]:
            file_count = len(_list_media_files(folder, replace_type))
            if 0 < file_count < batch_count:
                undersized.append(f"{os.path.basename(folder)}({file_count})")
        if undersized:
            return "这些槽位目录素材数少于批量数量，后续批次会循环复用：" + "，".join(undersized[:6])
        return None

    if replace_strategy == "sequence":
        undersized = []
        for folder in subfolders[:material_slot_count]:
            file_count = len(_list_media_files(folder, "video"))
            if 0 < file_count < batch_count:
                undersized.append(f"{os.path.basename(folder)}({file_count})")
        if undersized:
            return "这些拼接槽位目录视频数少于批量数量，后续批次会循环复用：" + "，".join(undersized[:6])
        return None

    if replace_strategy == "partition":
        undersized = []
        folder_map = {_normalize_name(os.path.basename(folder)): folder for folder in subfolders}
        for slot_name in material_names or []:
            normalized_name = _normalize_name(slot_name)
            folder = folder_map.get(normalized_name)
            if not folder:
                continue
            file_count = len(_list_media_files(folder, replace_type))
            if 0 < file_count < batch_count:
                undersized.append(f"{os.path.basename(folder)}({file_count})")
        if undersized:
            return "这些分区目录素材数少于批量数量，后续批次会循环复用：" + "，".join(undersized[:6])
    return None


def _lookup_material_override(material_replacements, material_name=None, material_path=None, material_id=None):
    if not isinstance(material_replacements, dict) or not material_replacements:
        return None

    candidates = []
    if material_name:
        candidates.append(str(material_name).strip().lower())
    if material_path:
        basename = os.path.basename(str(material_path).strip())
        if basename:
            candidates.append(basename.lower())
    if material_id:
        candidates.append(str(material_id).strip().lower())

    seen = set()
    for key in candidates:
        if not key or key in seen:
            continue
        seen.add(key)
        path = material_replacements.get(key)
        if path:
            return path
    return None


def _estimate_media_duration(media_path, default_duration=3.0):
    if not media_path:
        return default_duration
    try:
        from app.utils.jianying_mcp.utils.media_parser import get_media_duration
        duration = get_media_duration(media_path)
        if duration and duration > 0:
            return max(0.1, float(duration))
    except Exception:
        pass
    return default_duration


def _build_attachment_material_entries(template_path):
    entries = _service_build_attachment_material_entries(template_path)
    if entries:
        return entries

    normalized_path = normalize_draft_project_path(template_path)
    if not normalized_path or not os.path.isdir(normalized_path):
        return []

    slot_keys = []
    for root_path in (
        normalized_path,
        os.path.join(normalized_path, "common_attachment"),
        os.path.join(normalized_path, "video"),
    ):
        if not os.path.isdir(root_path):
            continue
        for walk_root, _dirs, files in os.walk(root_path):
            for name in files:
                lower_name = str(name).lower()
                if "material_placeholder" not in lower_name or "_water_mark" not in lower_name:
                    continue
                prefix = lower_name.split("##", 1)[0].strip()
                if re.fullmatch(r"[0-9a-f]{32}", prefix):
                    slot_keys.append(prefix)

    deduped_keys = []
    seen = set()
    for key in slot_keys:
        if key in seen:
            continue
        seen.add(key)
        deduped_keys.append(key)

    if not deduped_keys:
        return []

    return [
        {
            "name": f"video_slot_{idx + 1:02d}",
            "source": "videos",
            "material_id": f"attachment_fragment_{idx + 1:02d}",
        }
        for idx, _key in enumerate(deduped_keys)
    ]

def update_task_meta(meta, task_id=None):
    resolved_task_id = task_id
    if not resolved_task_id:
        resolved_task_id = getattr(_LOCAL_TASK_CONTEXT, "task_id", None)
    if not resolved_task_id:
        job = get_current_job()
        if job:
            resolved_task_id = job.id
    if resolved_task_id:
        task = Task.query.get(resolved_task_id)
        if task:
            task.progress = json.dumps(meta)
            db.session.commit()


def _resp_ok(resp):
    if resp is None:
        return False
    if hasattr(resp, "ok"):
        try:
            return bool(resp.ok)
        except Exception:
            return False
    if hasattr(resp, "success"):
        try:
            return bool(resp.success)
        except Exception:
            return False
    return False


def _resp_data(resp):
    if resp is None:
        return {}
    data = getattr(resp, "data", None)
    return data if isinstance(data, dict) else {}


def handle_generate_success(job, connection, result, *args, **kwargs):
    user_id = None
    try:
        if getattr(job, "args", None):
            # Batch jobs append template_path as the last positional arg,
            # while user_id is the argument right before it.
            if len(job.args) >= 2 and isinstance(job.args[-2], int):
                user_id = job.args[-2]
            elif isinstance(job.args[-1], int):
                user_id = job.args[-1]
    except Exception:
        user_id = None
    if not user_id:
        return
    if isinstance(result, dict) and result.get('ok') is False:
        return
    try:
        app = create_app()
        with app.app_context():
            from app.services.user_quota_service import deduct_quota
            deduct_quota(user_id, amount=1)
    except Exception as e:
        logging.error(f"quota deduct failed: {e}")


def _complete_remote_desktop_task(task_id, auth_token, success, error_msg=""):
    if not task_id or not auth_token:
        return
    try:
        call_remote_api(
            "/api/desktop/task-complete",
            method="POST",
            headers={"Authorization": f"Bearer {auth_token}"},
            json_data={
                "task_id": task_id,
                "success": bool(success),
                "error_msg": error_msg or "",
            },
            timeout=15,
        )
    except Exception as exc:
        logging.warning("remote desktop task finalize failed: %s", exc)


def _normalize_managed_template_key(template_path: str) -> str:
    normalized = normalize_draft_project_path(template_path) or str(template_path or "").strip()
    return os.path.normcase(os.path.normpath(normalized)) if normalized else ""


def _safe_managed_draft_name_part(value: str, fallback: str, limit: int = 24) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("._- ")
    if not text:
        return fallback
    if len(text) > limit:
        text = text[:limit].rstrip("._- ")
    return text or fallback


def _build_managed_run_token(task_id: str = "") -> str:
    token = str(task_id or "").strip()
    if token:
        return _safe_managed_draft_name_part(token[:8], "run", limit=12)
    return f"{time.strftime('%m%d%H%M%S', time.localtime())}_{uuid.uuid4().hex[:4]}"


def _build_managed_draft_name(
    template_path: str,
    drafts_root: str = "",
    task_id: str = "",
    batch_index: int = 0,
    generator: str = "official",
    run_token: str = "",
) -> str:
    template_basename = os.path.basename(str(template_path or "").rstrip("\\/")) or "draft"
    template_part = _safe_managed_draft_name_part(template_basename, "draft")
    drafts_root = str(drafts_root or "").strip()
    serial = max(1, int(batch_index or 0) + 1)

    while True:
        candidate = f"{template_part}_zysj_{serial:03d}"
        if not drafts_root or not os.path.exists(os.path.join(drafts_root, candidate)):
            return candidate
        serial += 1


def _build_generated_draft_marker(
    draft_name: str,
    draft_path: str,
    template_path: str,
    task_id: str = "",
    generator: str = "official",
    batch_index: int = 0,
    batch_count: int = 1,
    run_token: str = "",
) -> dict:
    resolved_run_id = str(run_token or "").strip() or _build_managed_run_token(task_id)
    return {
        "generator": str(generator or "official").strip().lower() or "official",
        "task_id": str(task_id or "").strip(),
        "run_id": resolved_run_id,
        "template_path": normalize_draft_project_path(template_path) or str(template_path or "").strip(),
        "template_key": _normalize_managed_template_key(template_path),
        "draft_name": str(draft_name or "").strip(),
        "draft_path": str(draft_path or "").strip(),
        "batch_index": int(batch_index or 0),
        "batch_count": max(1, int(batch_count or 1)),
        "created_at_ms": int(time.time() * 1000),
        "managed_by": "videofactory",
    }


def _marker_file_path(draft_path: str) -> str:
    return os.path.join(str(draft_path or "").strip(), _VF_GENERATED_MARKER)


def _write_generated_draft_marker(draft_path: str, marker: dict) -> None:
    target = _marker_file_path(draft_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(marker, handle, ensure_ascii=False, indent=2)


def _load_generated_draft_marker(draft_path: str) -> dict | None:
    target = _marker_file_path(draft_path)
    if not os.path.exists(target):
        return None
    try:
        with open(target, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _count_existing_managed_drafts(
    drafts_folder: str,
    template_path: str,
    generator: str = "official",
) -> int:
    root = str(drafts_folder or "").strip()
    if not root or not os.path.isdir(root):
        return 0

    target_template_key = _normalize_managed_template_key(template_path)
    target_generator = str(generator or "official").strip().lower() or "official"
    count = 0
    for name in os.listdir(root):
        draft_path = os.path.join(root, name)
        if not os.path.isdir(draft_path):
            continue
        marker = _load_generated_draft_marker(draft_path)
        if not isinstance(marker, dict):
            continue
        if str(marker.get("managed_by") or "").strip().lower() != "videofactory":
            continue
        if str(marker.get("generator") or "").strip().lower() != target_generator:
            continue
        if str(marker.get("template_key") or "").strip().lower() != target_template_key.lower():
            continue
        count += 1
    return count


def _cleanup_managed_drafts(
    drafts_folder: str,
    template_path: str,
    generator: str = "official",
    keep_run_count: int = _VF_MANAGED_RUN_KEEP,
    keep_paths: list[str] | None = None,
) -> list[str]:
    root = str(drafts_folder or "").strip()
    if not root or not os.path.isdir(root):
        return []

    if int(keep_run_count or 0) <= 0:
        return []
    keep_run_count = max(1, int(keep_run_count or 1))
    target_template_key = _normalize_managed_template_key(template_path)
    target_generator = str(generator or "official").strip().lower() or "official"
    keep_path_set = {
        os.path.normcase(os.path.normpath(str(item)))
        for item in (keep_paths or [])
        if str(item or "").strip()
    }

    candidates_by_run: dict[str, list[tuple[float, str, dict]]] = {}
    for name in os.listdir(root):
        draft_path = os.path.join(root, name)
        if not os.path.isdir(draft_path):
            continue
        marker = _load_generated_draft_marker(draft_path)
        if not isinstance(marker, dict):
            continue
        if str(marker.get("managed_by") or "").strip().lower() != "videofactory":
            continue
        if str(marker.get("generator") or "").strip().lower() != target_generator:
            continue
        if str(marker.get("template_key") or "").strip().lower() != target_template_key.lower():
            continue
        run_id = str(marker.get("run_id") or "").strip()
        if not run_id:
            continue
        try:
            created_at_ms = float(marker.get("created_at_ms") or 0)
        except Exception:
            created_at_ms = 0.0
        candidates_by_run.setdefault(run_id, []).append((created_at_ms, draft_path, marker))

    if len(candidates_by_run) <= keep_run_count:
        return []

    run_infos = []
    for run_id, items in candidates_by_run.items():
        latest_ts = max((item[0] for item in items), default=0.0)
        has_keep_path = any(os.path.normcase(os.path.normpath(item[1])) in keep_path_set for item in items)
        run_infos.append((has_keep_path, latest_ts, run_id, items))

    run_infos.sort(key=lambda item: (1 if item[0] else 0, item[1]), reverse=True)
    keep_run_ids = {item[2] for item in run_infos[:keep_run_count]}
    removed_paths: list[str] = []
    for _has_keep_path, _latest_ts, run_id, items in run_infos[keep_run_count:]:
        if run_id in keep_run_ids:
            continue
        for _created_at_ms, draft_path, _marker in items:
            norm_path = os.path.normcase(os.path.normpath(draft_path))
            if norm_path in keep_path_set or not os.path.isdir(draft_path):
                continue
            try:
                shutil.rmtree(draft_path)
                removed_paths.append(draft_path)
            except Exception as exc:
                logging.warning("managed draft cleanup skipped for %s: %s", draft_path, exc)
    return removed_paths


def _generate_video_task_via_mcp(
    template_id,
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
    template_path,
    task_id,
):
    from app.services.jianying_service import JianYingService

    if not template_path:
        template = TemplateModel.query.get(template_id)
        if not template:
            raise Exception("legacy template not found")
        template_path = template.template_path

    template_path = normalize_draft_project_path(template_path)
    if not template_path or not os.path.isdir(template_path):
        raise Exception("template_path is invalid")
    if not is_valid_draft_project_path(template_path):
        raise Exception("template_path is not a valid draft project")

    update_task_meta({'progress': 'reading material files...'}, task_id=task_id)
    drafts_folder = _resolve_generated_drafts_root(template_path, export_path)
    if not drafts_folder:
        raise Exception("drafts folder is not configured")
    os.makedirs(drafts_folder, exist_ok=True)

    materials, material_map, texts_info, material_sources = _extract_template_runtime_info(template_path)
    all_material_names = list(material_map.keys())
    material_names = []
    for fname in all_material_names:
        is_audio = material_sources.get(fname) == 'audios'
        if is_audio and not replace_audios:
            continue
        if not is_audio and not replace_materials:
            continue
        if _template_material_matches_type(
            fname,
            material_sources.get(fname),
            replace_type,
            replace_strategy,
        ):
            material_names.append(fname)

    generated = 0
    generated_paths = []
    batch_details = []
    failed_batches = []
    cleaned_paths = []
    warnings = []
    run_token = _build_managed_run_token(task_id)
    material_selection_offset = _count_existing_managed_drafts(
        drafts_folder=drafts_folder,
        template_path=template_path,
        generator="official",
    )
    material_selection_offset = _count_existing_managed_drafts(
        drafts_folder=drafts_folder,
        template_path=template_path,
        generator="mcp",
    )

    material_replacements_by_key = {}
    if replace_materials and material_names:
        sequence_cache_root = os.path.join(drafts_folder, ".vf_sequence_cache")
        os.makedirs(sequence_cache_root, exist_ok=True)
    else:
        sequence_cache_root = None

    pool_warning = _build_material_pool_warning(
        materials_root=materials_root,
        replace_type=replace_type,
        replace_mode=replace_mode,
        replace_strategy=replace_strategy,
        batch_count=batch_count,
        material_slot_count=len(material_names),
        material_names=material_names,
    )
    if pool_warning and pool_warning not in warnings:
        warnings.append(pool_warning)

    for i in range(batch_count):
        draft_name = _build_managed_draft_name(
            template_path=template_path,
            drafts_root=drafts_folder,
            task_id=task_id,
            batch_index=i,
            generator="mcp",
            run_token=run_token,
        )
        update_task_meta({'progress': f'mcp rebuilding draft ({i+1}/{batch_count})...'}, task_id=task_id)

        user_files = {}
        material_summary = {"expected_count": 0, "selected_count": 0, "missing_count": 0, "selected_items": [], "truncated_count": 0}
        if replace_materials and material_names:
            user_files = _collect_user_material_overrides(
                material_names=material_names,
                materials_root=materials_root,
                replace_type=replace_type,
                replace_mode=replace_mode,
                replace_strategy=replace_strategy,
                sequence_clip_count=sequence_clip_count,
                batch_index=i,
                sequence_cache_root=os.path.join(sequence_cache_root, draft_name) if sequence_cache_root else drafts_folder,
                selection_offset=material_selection_offset,
            )
            material_replacements_by_key = dict(user_files)
            material_summary = _build_material_override_summary(material_names, user_files)

        try:
            svc = JianYingService(output_path=drafts_folder)
            batch_texts_input = _resolve_batch_texts_input(texts_input, i) if replace_texts else None
            summary = _apply_mcp_effects(
                template_path,
                effects_config or {},
                svc,
                duo_config,
                export_format=export_format,
                export_resolution=export_resolution,
                export_fps=export_fps,
                texts_input=batch_texts_input,
                material_replacements=material_replacements_by_key if replace_materials else None,
                output_path=drafts_folder,
                force_export=True,
                draft_name=draft_name,
                audio_source_root=audio_root or materials_root if (audio_enabled or replace_audios) else None,
            )
            exported_name = str((summary or {}).get("exported_draft_name") or draft_name).strip() or draft_name
            exported_path = os.path.join(drafts_folder, exported_name)
            if not os.path.isdir(exported_path):
                raise RuntimeError(f"MCP export draft missing: {exported_path}")
            if summary:
                if task_id:
                    try:
                        log = TaskEffectLog(task_id=task_id, summary=json.dumps(summary, ensure_ascii=False))
                        db.session.add(log)
                        db.session.commit()
                    except Exception as exc:
                        logging.warning("MCP effects log failed: %s", exc)
                for warning in summary.get("warnings") or []:
                    if warning not in warnings:
                        warnings.append(warning)

            generated += 1
            generated_paths.append(exported_path)
            batch_details.append({
                "batch_index": i,
                "draft_name": exported_name,
                "draft_path": exported_path,
                "expected_count": material_summary.get("expected_count", 0),
                "selected_count": material_summary.get("selected_count", 0),
                "missing_count": material_summary.get("missing_count", 0),
                "selected_items": material_summary.get("selected_items", []),
                "truncated_count": material_summary.get("truncated_count", 0),
                "replace_strategy": replace_strategy,
                "replace_mode": replace_mode,
                "status": "ok",
            })
            try:
                _write_generated_draft_marker(
                    exported_path,
                    _build_generated_draft_marker(
                        draft_name=exported_name,
                        draft_path=exported_path,
                        template_path=template_path,
                        task_id=task_id,
                        generator="mcp",
                        batch_index=i,
                        batch_count=batch_count,
                        run_token=run_token,
                    ),
                )
            except Exception as exc:
                logging.warning("managed draft marker write failed for %s: %s", exported_path, exc)
        except Exception as exc:
            logging.exception("mcp batch generation failed at index %s", i)
            failure_message = str(exc or "unknown error")
            failed_batches.append({
                "batch_index": i,
                "draft_name": draft_name,
                "expected_count": material_summary.get("expected_count", 0),
                "selected_count": material_summary.get("selected_count", 0),
                "missing_count": material_summary.get("missing_count", 0),
                "selected_items": material_summary.get("selected_items", []),
                "truncated_count": material_summary.get("truncated_count", 0),
                "replace_strategy": replace_strategy,
                "replace_mode": replace_mode,
                "status": "failed",
                "error": failure_message,
            })
            warning_message = f"第 {i + 1} 份生成失败：{failure_message}"
            if warning_message not in warnings:
                warnings.append(warning_message)
        update_task_meta({'progress': f'completed {generated}/{batch_count} drafts'}, task_id=task_id)

    try:
        cleaned_paths = _cleanup_managed_drafts(
            drafts_folder=drafts_folder,
            template_path=template_path,
            generator="mcp",
            keep_paths=generated_paths,
        )
    except Exception as exc:
        logging.warning("managed draft cleanup failed: %s", exc)

    if generated <= 0 and failed_batches:
        raise RuntimeError(f"all batch generations failed: {failed_batches[0].get('error') or 'unknown error'}")

    result = {'ok': True, 'message': 'batch generation completed', 'generated': generated}
    if warnings:
        result['warnings'] = warnings
    if generated_paths:
        result['generated_paths'] = generated_paths
    if batch_details:
        result['batch_details'] = batch_details
    if failed_batches:
        result['failed_batches'] = failed_batches
    if cleaned_paths:
        result['cleaned_paths'] = cleaned_paths
    return result


def _generate_video_task_via_official_draft(
    template_id,
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
    template_path,
    task_id,
):
    if not template_path:
        template = TemplateModel.query.get(template_id)
        if not template:
            raise Exception("legacy template not found")
        template_path = template.template_path

    template_path = normalize_draft_project_path(template_path)
    if not template_path or not os.path.isdir(template_path):
        raise Exception("template_path is invalid")
    if not is_valid_draft_project_path(template_path):
        raise Exception("template_path is not a valid draft project")

    drafts_folder = _resolve_generated_drafts_root(template_path, export_path)
    if not drafts_folder:
        raise Exception("drafts folder is not configured")
    os.makedirs(drafts_folder, exist_ok=True)

    materials, material_map, _texts_info, material_sources = _extract_template_runtime_info(template_path)
    material_names = []
    for fname in materials:
        source_kind = material_sources.get(fname)
        is_audio = source_kind == 'audios'
        if is_audio and not replace_audios:
            continue
        if not is_audio and not replace_materials:
            continue
        if _template_material_matches_type(fname, source_kind, replace_type, replace_strategy):
            material_names.append(fname)

    generated_paths = []
    batch_details = []
    failed_batches = []
    cleaned_paths = []
    warnings = []
    run_token = _build_managed_run_token(task_id)
    material_selection_offset = _count_existing_managed_drafts(
        drafts_folder=drafts_folder,
        template_path=template_path,
        generator="official",
    )

    pool_warning = _build_material_pool_warning(
        materials_root=materials_root,
        replace_type=replace_type,
        replace_mode=replace_mode,
        replace_strategy=replace_strategy,
        batch_count=batch_count,
        material_slot_count=len(material_names),
        material_names=material_names,
    )
    if pool_warning and pool_warning not in warnings:
        warnings.append(pool_warning)

    for i in range(batch_count):
        draft_name = _build_managed_draft_name(
            template_path=template_path,
            drafts_root=drafts_folder,
            task_id=task_id,
            batch_index=i,
            generator="official",
            run_token=run_token,
        )
        update_task_meta({'progress': f'official draft rebuilding ({i+1}/{batch_count})...'}, task_id=task_id)

        material_replacements = {}
        material_summary = {"expected_count": 0, "selected_count": 0, "missing_count": 0, "selected_items": [], "truncated_count": 0}
        if replace_materials and material_names:
            selected_material_overrides = _collect_user_material_overrides(
                material_names=material_names,
                materials_root=materials_root,
                replace_type=replace_type,
                replace_mode=replace_mode,
                replace_strategy=replace_strategy,
                sequence_clip_count=sequence_clip_count,
                batch_index=i,
                sequence_cache_root=os.path.join(drafts_folder, ".vf_sequence_cache", draft_name),
                selection_offset=material_selection_offset,
            )
            material_summary = _build_material_override_summary(material_names, selected_material_overrides)
            material_replacements = dict(selected_material_overrides)
            if material_map and material_replacements:
                expanded_replacements = dict(material_replacements)
                for material_name, override_path in selected_material_overrides.items():
                    material_id = material_map.get(material_name) or material_map.get(str(material_name or "").strip())
                    if material_id and override_path:
                        expanded_replacements[str(material_id).strip().lower()] = override_path
                material_replacements = expanded_replacements

        try:
            batch_texts_input = _resolve_batch_texts_input(texts_input, i) if replace_texts else None
            summary = replace_official_draft(
                template_path=template_path,
                draft_name=draft_name,
                texts_input=batch_texts_input,
                material_replacements=material_replacements if replace_materials else None,
                output_root=drafts_folder,
            )
            generated_paths.append(summary["draft_path"])
            batch_details.append({
                "batch_index": i,
                "draft_name": draft_name,
                "draft_path": summary["draft_path"],
                "expected_count": material_summary.get("expected_count", 0),
                "selected_count": material_summary.get("selected_count", 0),
                "missing_count": material_summary.get("missing_count", 0),
                "selected_items": material_summary.get("selected_items", []),
                "truncated_count": material_summary.get("truncated_count", 0),
                "replace_strategy": replace_strategy,
                "replace_mode": replace_mode,
                "status": "ok",
            })
            try:
                summary_diagnostics = ((summary or {}).get("diagnostics") or {})
                marker_payload = _build_generated_draft_marker(
                    draft_name=draft_name,
                    draft_path=summary["draft_path"],
                    template_path=template_path,
                    task_id=task_id,
                    generator="official",
                    batch_index=i,
                    batch_count=batch_count,
                    run_token=run_token,
                )
                marker_payload["write_mode"] = summary_diagnostics.get("write_mode")
                marker_payload["timeline_project_reconciliation"] = summary_diagnostics.get("timeline_project_reconciliation")
                _write_generated_draft_marker(summary["draft_path"], marker_payload)
            except Exception as exc:
                logging.warning("managed draft marker write failed for %s: %s", summary["draft_path"], exc)
            for warning in summary.get("warnings") or []:
                if warning not in warnings:
                    warnings.append(warning)
        except Exception as exc:
            logging.exception("official batch generation failed at index %s", i)
            failure_message = str(exc or "unknown error")
            failed_batches.append({
                "batch_index": i,
                "draft_name": draft_name,
                "expected_count": material_summary.get("expected_count", 0),
                "selected_count": material_summary.get("selected_count", 0),
                "missing_count": material_summary.get("missing_count", 0),
                "selected_items": material_summary.get("selected_items", []),
                "truncated_count": material_summary.get("truncated_count", 0),
                "replace_strategy": replace_strategy,
                "replace_mode": replace_mode,
                "status": "failed",
                "error": failure_message,
            })
            warning_message = f"第 {i + 1} 份生成失败：{failure_message}"
            if warning_message not in warnings:
                warnings.append(warning_message)

    try:
        cleaned_paths = _cleanup_managed_drafts(
            drafts_folder=drafts_folder,
            template_path=template_path,
            generator="official",
            keep_paths=generated_paths,
        )
    except Exception as exc:
        logging.warning("managed draft cleanup failed: %s", exc)

    if not generated_paths and failed_batches:
        raise RuntimeError(f"all batch generations failed: {failed_batches[0].get('error') or 'unknown error'}")

    result = {'ok': True, 'message': 'batch generation completed', 'generated': len(generated_paths)}
    if warnings:
        result['warnings'] = warnings
    if generated_paths:
        result['generated_paths'] = generated_paths
    if batch_details:
        result['batch_details'] = batch_details
    if failed_batches:
        result['failed_batches'] = failed_batches
    if cleaned_paths:
        result['cleaned_paths'] = cleaned_paths
    return result

def generate_video_task(template_id, materials_root, texts_input, batch_count,
                        replace_materials=True, replace_texts=True,
                        replace_audios=False,
                        replace_type='both', replace_mode='order', replace_strategy='group',
                        sequence_clip_count=3,
                        audio_enabled=False, audio_root=None, export_enabled=False, export_path=None, export_format=None,
                        export_resolution=None, export_fps=None,
                        effects_config=None, duo_config=None, user_id=None, template_path=None,
                        task_id_override=None, auth_token=None):
    app = create_app()
    with app.app_context():
        job = get_current_job()
        task_id = task_id_override or (job.id if job else None)
        _LOCAL_TASK_CONTEXT.task_id = task_id
        task = Task.query.get(task_id) if task_id else None
        if task:
            task.status = 'started'
            db.session.commit()
        try:
            if not template_path:
                template = TemplateModel.query.get(template_id)
                if not template:
                    raise Exception("legacy template not found")

                template_path = template.template_path
            result = _generate_video_task_via_official_draft(
                template_id=template_id,
                materials_root=materials_root,
                texts_input=texts_input,
                batch_count=batch_count,
                replace_materials=replace_materials,
                replace_texts=replace_texts,
                replace_audios=replace_audios,
                replace_type=replace_type,
                replace_mode=replace_mode,
                replace_strategy=replace_strategy,
                sequence_clip_count=sequence_clip_count,
                audio_enabled=audio_enabled,
                audio_root=audio_root,
                export_enabled=export_enabled,
                export_path=export_path,
                export_format=export_format,
                export_resolution=export_resolution,
                export_fps=export_fps,
                effects_config=effects_config,
                duo_config=duo_config,
                template_path=template_path,
                task_id=task_id,
            )
            update_task_meta({'progress': 'all completed', 'result': result}, task_id=task_id)
            if task:
                task.status = 'finished'
                db.session.commit()
            if auth_token and task_id:
                _complete_remote_desktop_task(task_id, auth_token, True, "")
            elif user_id and not job:
                try:
                    from app.services.user_quota_service import deduct_quota
                    deduct_quota(user_id, amount=1)
                except Exception as quota_error:
                    logging.error(f"quota deduct failed: {quota_error}")
            return result
        except Exception as e:
            if task:
                task.status = 'failed'
                task.error_msg = str(e)
                db.session.commit()
            if auth_token and task_id:
                _complete_remote_desktop_task(task_id, auth_token, False, str(e))
            raise e
        finally:
            if hasattr(_LOCAL_TASK_CONTEXT, "task_id"):
                delattr(_LOCAL_TASK_CONTEXT, "task_id")


def _apply_mcp_effects(draft_path, effects_config, svc, duo_config=None,
                       export_format=None, export_resolution=None, export_fps=None,
                       texts_input=None, material_replacements=None,
                       output_path=None, force_export=False, draft_name=None,
                       audio_source_root=None):
    """
    基于 MCP 导出流程生成带效果的新草稿（实验性）。
    注意：该流程会重建轨道与素材，可能丢失部分模板样式。
    """
    import json
    import os
    import uuid
    import shutil
    import subprocess

    summary = {"applied": [], "warnings": []}

    normalized_draft_path = normalize_draft_project_path(draft_path)
    draft_content_candidates = find_draft_content_files(normalized_draft_path)
    draft_content = draft_content_candidates[0] if draft_content_candidates else os.path.join(normalized_draft_path, 'draft_content.json')
    if not os.path.exists(draft_content):
        summary["warnings"].append("draft_content.json not found")
    attachment_entries = []

    data, load_err, diagnostics = load_draft_content(normalized_draft_path)
    if load_err or not isinstance(data, dict):
        summary["warnings"].append(load_err or "draft_content.json read failed")
        if diagnostics.get("matched_candidate"):
            draft_content = diagnostics["matched_candidate"]
        attachment_entries = _build_attachment_material_entries(normalized_draft_path)
        if not attachment_entries:
            return summary
        summary["warnings"].append("attachment fallback active: slot-level MCP rebuild")
        data = {}
    else:
        data = _resolve_active_draft_payload(data)
        draft_content = diagnostics.get("matched_candidate") or draft_content

    template_file_index = _build_file_index(normalized_draft_path)

    def _resolve_template_media_path(path_value):
        raw_path = str(path_value or "").strip()
        if not raw_path:
            return ""
        if os.path.isabs(raw_path) and os.path.exists(raw_path):
            return raw_path
        joined_path = os.path.normpath(os.path.join(normalized_draft_path, raw_path.replace("/", os.sep)))
        if os.path.exists(joined_path):
            return joined_path
        basename = os.path.basename(raw_path)
        if basename:
            resolved = template_file_index.get(basename.lower())
            if resolved and os.path.exists(resolved):
                return resolved
        return raw_path

    effects_config = effects_config or {}

    # if only duo preprocess/text styles, avoid rebuild to preserve template
    if effects_config.get('video') is None and effects_config.get('audio') is None and effects_config.get('text') is None:
        effects_config = {}
    # 构建 MCP 草稿
    draft_id = uuid.uuid4().hex
    fmt = export_format if export_format in ("mp4", "mov") else None
    draft_name = str(draft_name or "").strip() or f"mcp_{draft_id}{'_' + fmt if fmt else ''}"
    canvas = data.get("canvas_config", {}) or {}
    base_w = canvas.get("width", 1080)
    base_h = canvas.get("height", 1920)
    landscape = base_w >= base_h
    if export_resolution in ("720p", "1080p", "4k"):
        if export_resolution == "720p":
            target_w, target_h = (1280, 720) if landscape else (720, 1280)
        elif export_resolution == "1080p":
            target_w, target_h = (1920, 1080) if landscape else (1080, 1920)
        else:  # 4k
            target_w, target_h = (3840, 2160) if landscape else (2160, 3840)
    else:
        target_w, target_h = base_w, base_h

    target_fps = data.get("fps", 30)
    if export_fps is not None:
        try:
            fps_int = int(export_fps)
            if fps_int > 0:
                target_fps = fps_int
        except Exception:
            pass

    create_resp = svc.create_draft(
        draft_name=draft_name,
        width=target_w,
        height=target_h,
        fps=target_fps,
    )
    if not create_resp or not getattr(create_resp, "ok", False):
        raise RuntimeError(getattr(create_resp, "message", None) or "create draft failed")
    created_draft_id = ((getattr(create_resp, "data", None) or {}).get("draft_id") or "").strip()
    if not created_draft_id:
        raise RuntimeError("create draft returned empty draft_id")

    draft_id = created_draft_id
    summary["draft_id"] = draft_id
    summary["draft_name"] = draft_name
    if fmt:
        summary["export_format"] = fmt
    if audio_source_root:
        summary["audio_source_root"] = audio_source_root

    # create tracks based on original draft order
    track_name_by_index = {}
    overlay_track_name = None
    if attachment_entries:
        resp = svc.create_track(draft_id, "video", "video_main")
        if resp and getattr(resp, "ok", False) and resp.data and resp.data.get("track_name"):
            track_name_by_index[0] = resp.data.get("track_name")
        else:
            track_name_by_index[0] = "video_main"
    else:
        for idx, track in enumerate(data.get("tracks", [])):
            ttype = track.get("type")
            if ttype not in ("video", "audio", "text"):
                continue
            raw_name = track.get("name") or track.get("track_name") or f"{ttype}_{idx}"
            resp = svc.create_track(draft_id, ttype, raw_name)
            if resp and getattr(resp, "ok", False) and resp.data and resp.data.get("track_name"):
                track_name_by_index[idx] = resp.data.get("track_name")
            else:
                track_name_by_index[idx] = raw_name

    # build maps
    materials = data.get("materials", {})
    video_mats = {m.get("id"): m for m in materials.get("videos", [])}
    audio_mats = {m.get("id"): m for m in materials.get("audios", [])}
    text_mats = {m.get("id"): m for m in materials.get("texts", [])}

    video_segment_ids = []
    audio_segment_ids = []
    text_segment_ids = []

    expected_video_segments = 0
    expected_audio_segments = 0
    expected_text_segments = 0
    if attachment_entries:
        expected_video_segments = len(attachment_entries)
    else:
        for track in data.get("tracks", []):
            ttype = track.get("type")
            if ttype not in ("video", "audio", "text"):
                continue
            segment_count = len(track.get("segments") or [])
            if ttype == "video":
                expected_video_segments += segment_count
            elif ttype == "audio":
                expected_audio_segments += segment_count
            else:
                expected_text_segments += segment_count

    video_segment_track = {}
    audio_segment_track = {}
    text_segment_track = {}
    text_replacements = _build_text_replacement_map(texts_input)

    micro_cfg = (effects_config.get("video") or {}).get("micro_adjust") or {}
    if micro_cfg.get("enabled") is False:
        micro_cfg = {}
    micro_indexes = set()
    if isinstance(micro_cfg.get("indexes"), list):
        micro_indexes = {i for i in micro_cfg.get("indexes") if isinstance(i, int) and i >= 0}
    micro_applied = False
    video_segment_meta = []

    def _rand_between(low, high):
        try:
            low = float(low)
            high = float(high)
        except Exception:
            return None
        if low > high:
            low, high = high, low
        return random.uniform(low, high)

    def _duration_from_tr(tr):
        if not isinstance(tr, dict):
            return None
        try:
            return float(tr.get("duration", 0)) / 1_000_000
        except Exception:
            return None

    def _to_color_triplet(value):
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("#"):
                hex_value = raw[1:]
                if len(hex_value) == 3:
                    hex_value = "".join(ch * 2 for ch in hex_value)
                if len(hex_value) >= 6:
                    try:
                        return [
                            int(hex_value[0:2], 16) / 255.0,
                            int(hex_value[2:4], 16) / 255.0,
                            int(hex_value[4:6], 16) / 255.0,
                        ]
                    except Exception:
                        return None
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                parts = [float(value[0]), float(value[1]), float(value[2])]
            except Exception:
                return None
            if any(part > 1 for part in parts):
                return [min(max(part / 255.0, 0.0), 1.0) for part in parts]
            return [min(max(part, 0.0), 1.0) for part in parts]
        return None

    def _extract_text_segment_params(mat, seg, replacement_text=None):
        content = replacement_text if replacement_text is not None else (mat.get("recognize_text") or "")
        style = {}
        size = mat.get("text_size")
        if size is None:
            size = mat.get("font_size")
        try:
            if size is not None:
                style["size"] = float(size)
        except Exception:
            pass
        color = _to_color_triplet(mat.get("text_color"))
        if color:
            style["color"] = color
        try:
            style["alpha"] = float(mat.get("text_alpha", mat.get("global_alpha", 1.0)) or 1.0)
        except Exception:
            pass
        try:
            style["align"] = int(mat.get("alignment", 0) or 0)
        except Exception:
            pass
        style["bold"] = bool(mat.get("bold_width"))
        style["italic"] = bool(mat.get("italic_degree"))
        style["underline"] = bool(mat.get("underline"))
        try:
            style["letter_spacing"] = float(mat.get("letter_spacing", 0) or 0)
        except Exception:
            pass
        try:
            style["line_spacing"] = float(mat.get("line_spacing", 0) or 0)
        except Exception:
            pass
        try:
            style["max_line_width"] = float(mat.get("line_max_width", 0.82) or 0.82)
        except Exception:
            pass

        border = None
        border_width = mat.get("border_width")
        border_color = _to_color_triplet(mat.get("border_color"))
        if border_width or border_color:
            border = {
                "alpha": float(mat.get("border_alpha", 1.0) or 1.0),
                "width": float(border_width or 0.0),
            }
            if border_color:
                border["color"] = border_color

        background = None
        background_color = mat.get("background_color") or mat.get("background_fill")
        if background_color:
            background = {
                "color": background_color,
                "style": int(mat.get("background_style", 1) or 1),
                "alpha": float(mat.get("background_alpha", 1.0) or 1.0),
                "round_radius": float(mat.get("background_round_radius", 0.0) or 0.0),
                "height": float(mat.get("background_height", 0.14) or 0.14),
                "width": float(mat.get("background_width", 0.14) or 0.14),
                "horizontal_offset": float(mat.get("background_horizontal_offset", 0.0) or 0.0),
                "vertical_offset": float(mat.get("background_vertical_offset", 0.0) or 0.0),
            }

        clip_settings = None
        clip = seg.get("clip") if isinstance(seg, dict) else None
        if isinstance(clip, dict):
            transform = clip.get("transform") if isinstance(clip.get("transform"), dict) else {}
            scale = clip.get("scale") if isinstance(clip.get("scale"), dict) else {}
            flip = clip.get("flip") if isinstance(clip.get("flip"), dict) else {}
            clip_settings = {
                "alpha": float(clip.get("alpha", 1.0) or 1.0),
                "rotation": float(clip.get("rotation", 0.0) or 0.0),
                "transform_x": float(transform.get("x", 0.0) or 0.0),
                "transform_y": float(transform.get("y", 0.0) or 0.0),
                "scale_x": float(scale.get("x", 1.0) or 1.0),
                "scale_y": float(scale.get("y", 1.0) or 1.0),
                "flip_horizontal": bool(flip.get("horizontal")),
                "flip_vertical": bool(flip.get("vertical")),
            }

        font = (mat.get("font_name") or "").strip()
        if not font:
            font = (mat.get("font_title") or "").strip()
        if font.lower() == "none":
            font = None

        return {
            "content": content,
            "font": font,
            "style": style or None,
            "border": border,
            "background": background,
            "clip_settings": clip_settings,
        }

    # segments (preserve track order and basic clip settings)
    def _trange_str(tr):
        if not isinstance(tr, dict):
            return None
        start = float(tr.get("start", 0)) / 1_000_000
        duration = float(tr.get("duration", 0)) / 1_000_000
        return f"{start}s-{duration}s"

    if attachment_entries:
        track_name = track_name_by_index.get(0, "video_main")
        cursor = 0.0
        for seg_index, entry in enumerate(attachment_entries):
            path = _lookup_material_override(
                material_replacements,
                material_name=entry.get("name"),
                material_id=entry.get("material_id"),
            )
            if not path:
                summary["warnings"].append(f"attachment slot missing replacement: {entry.get('name')}")
                continue
            if not os.path.exists(path):
                summary["warnings"].append(f"attachment slot path missing: {path}")
                continue
            duration = _estimate_media_duration(path, default_duration=3.0)
            target_timerange = f"{cursor:.3f}s-{duration:.3f}s"
            source_timerange = f"0.000s-{duration:.3f}s"
            apply_micro = bool(micro_cfg) and (not micro_indexes or seg_index in micro_indexes)
            resp = svc.add_video_segment(
                draft_id,
                path,
                target_timerange,
                source_timerange=source_timerange,
                track_name=track_name,
            )
            resp_data = _resp_data(resp)
            if _resp_ok(resp) and resp_data:
                video_segment_ids.append(resp_data.get("video_segment_id"))
                video_segment_track[len(video_segment_ids) - 1] = track_name
                video_segment_meta.append({
                    "duration": duration,
                    "track": track_name,
                    "apply_micro": apply_micro,
                })
                cursor += duration
    else:
        for idx, track in enumerate(data.get("tracks", [])):
            ttype = track.get("type")
            if ttype not in ("video", "audio", "text"):
                continue
            track_name = track_name_by_index.get(idx)
            for seg in track.get("segments", []):
                mid = seg.get("material_id")
                if ttype == "video":
                    mat = video_mats.get(mid)
                    if not mat:
                        continue
                    path = mat.get("path") or mat.get("file_path")
                    override_path = _lookup_material_override(
                        material_replacements,
                        material_name=mat.get("material_name") or mat.get("name"),
                        material_path=path,
                        material_id=mid,
                    )
                    if override_path:
                        path = override_path
                    else:
                        path = _resolve_template_media_path(path)
                    if not path:
                        continue
                    seg_index = len(video_segment_ids)
                    target_timerange = _trange_str(seg.get("target_timerange", {}))
                    if not target_timerange:
                        continue
                    source_timerange = _trange_str(seg.get("source_timerange", {}))
                    clip_settings = seg.get("clip_settings") or seg.get("clip")
                    speed = seg.get("speed")
                    volume = seg.get("volume", 1.0)
                    change_pitch = seg.get("change_pitch", False)

                    apply_micro = bool(micro_cfg) and (not micro_indexes or seg_index in micro_indexes)
                    if apply_micro:
                        speed_cfg = micro_cfg.get("speed") or {}
                        rand_speed = _rand_between(speed_cfg.get("min"), speed_cfg.get("max"))
                        if rand_speed:
                            base_speed = float(speed) if speed is not None else 1.0
                            speed = max(0.1, base_speed * rand_speed)
                            micro_applied = True

                        clip_map = dict(clip_settings) if isinstance(clip_settings, dict) else {}
                        transform_cfg = micro_cfg.get("transform") or {}
                        rand_scale = _rand_between(transform_cfg.get("scale_min"), transform_cfg.get("scale_max"))
                        if rand_scale:
                            base_sx = float(clip_map.get("scale_x", 1.0) or 1.0)
                            base_sy = float(clip_map.get("scale_y", 1.0) or 1.0)
                            clip_map["scale_x"] = base_sx * rand_scale
                            clip_map["scale_y"] = base_sy * rand_scale
                            micro_applied = True
                        pos_x = transform_cfg.get("pos_x")
                        try:
                            pos_x_val = float(pos_x)
                        except Exception:
                            pos_x_val = None
                        if pos_x_val is not None:
                            offset_x = _rand_between(-abs(pos_x_val), abs(pos_x_val))
                            if offset_x is not None:
                                base_x = float(clip_map.get("transform_x", 0.0) or 0.0)
                                clip_map["transform_x"] = base_x + offset_x
                                micro_applied = True
                        pos_y = transform_cfg.get("pos_y")
                        try:
                            pos_y_val = float(pos_y)
                        except Exception:
                            pos_y_val = None
                        if pos_y_val is not None:
                            offset_y = _rand_between(-abs(pos_y_val), abs(pos_y_val))
                            if offset_y is not None:
                                base_y = float(clip_map.get("transform_y", 0.0) or 0.0)
                                clip_map["transform_y"] = base_y + offset_y
                                micro_applied = True
                        rot_range = transform_cfg.get("rotation")
                        try:
                            rot_val = float(rot_range)
                        except Exception:
                            rot_val = None
                        if rot_val is not None:
                            offset_r = _rand_between(-abs(rot_val), abs(rot_val))
                            if offset_r is not None:
                                base_r = float(clip_map.get("rotation", 0.0) or 0.0)
                                clip_map["rotation"] = base_r + offset_r
                                micro_applied = True

                        mirror_cfg = micro_cfg.get("mirror") or {}
                        if mirror_cfg.get("horizontal"):
                            clip_map["flip_horizontal"] = random.choice([True, False])
                            micro_applied = True
                        if mirror_cfg.get("vertical"):
                            clip_map["flip_vertical"] = random.choice([True, False])
                            micro_applied = True

                        clip_settings = clip_map if clip_map else clip_settings

                    resp = svc.add_video_segment(
                        draft_id,
                        path,
                        target_timerange,
                        source_timerange=source_timerange,
                        speed=speed,
                        volume=volume,
                        change_pitch=change_pitch,
                        clip_settings=clip_settings if isinstance(clip_settings, dict) else None,
                        track_name=track_name,
                    )
                    resp_data = _resp_data(resp)
                    if _resp_ok(resp) and resp_data:
                        video_segment_ids.append(resp_data.get("video_segment_id"))
                        video_segment_track[len(video_segment_ids) - 1] = track_name
                        video_segment_meta.append({
                            "duration": _duration_from_tr(seg.get("target_timerange", {})),
                            "track": track_name,
                            "apply_micro": apply_micro,
                        })
                    else:
                        summary["warnings"].append(f"video segment rebuild failed: {mid}")
                    continue

                if ttype == "audio":
                    mat = audio_mats.get(mid)
                    if not mat:
                        continue
                    path = mat.get("path") or mat.get("file_path")
                    override_path = _lookup_material_override(
                        material_replacements,
                        material_name=mat.get("material_name") or mat.get("name"),
                        material_path=path,
                        material_id=mid,
                    )
                    if override_path:
                        path = override_path
                    else:
                        path = _resolve_template_media_path(path)
                    if not path:
                        continue
                    target_range_data = seg.get("target_timerange", {})
                    target_timerange = _trange_str(target_range_data)
                    if not target_timerange:
                        continue
                    source_timerange = _trange_str(seg.get("source_timerange", {}))
                    speed = seg.get("speed")
                    volume = seg.get("volume", 1.0)
                    change_pitch = seg.get("change_pitch", False)
                    if override_path:
                        audio_duration = _estimate_media_duration(path, default_duration=3.0)
                        if audio_duration > 0:
                            try:
                                target_start = float(target_range_data.get("start", 0)) / 1_000_000
                            except Exception:
                                target_start = 0.0
                            requested_duration = _duration_from_tr(target_range_data) or audio_duration
                            effective_duration = min(requested_duration, audio_duration)
                            target_timerange = f"{target_start:.3f}s-{effective_duration:.3f}s"
                            source_timerange = f"0.000s-{effective_duration:.3f}s"
                    resp = svc.add_audio_segment(
                        draft_id,
                        path,
                        target_timerange,
                        source_timerange=source_timerange,
                        speed=speed,
                        volume=volume,
                        change_pitch=change_pitch,
                        track_name=track_name,
                    )
                    resp_data = _resp_data(resp)
                    if _resp_ok(resp) and resp_data:
                        audio_segment_ids.append(resp_data.get("audio_segment_id"))
                        audio_segment_track[len(audio_segment_ids) - 1] = track_name
                    else:
                        summary["warnings"].append(f"audio segment rebuild failed: {mid}")
                    continue

                mat = text_mats.get(mid)
                if not mat:
                    continue
                text_index = len(text_segment_ids)
                replacement_text = text_replacements.get(text_index)
                text_params = _extract_text_segment_params(mat, seg, replacement_text=replacement_text)
                content = text_params.get("content") or ""
                target_timerange = _trange_str(seg.get("target_timerange", {}))
                if not target_timerange:
                    continue
                resp = svc.add_text_segment(
                    draft_id,
                    content,
                    target_timerange,
                    font=text_params.get("font"),
                    style=text_params.get("style"),
                    clip_settings=text_params.get("clip_settings"),
                    border=text_params.get("border"),
                    background=text_params.get("background"),
                    track_name=track_name,
                )
                resp_data = _resp_data(resp)
                if _resp_ok(resp) and resp_data:
                    text_segment_ids.append(resp_data.get("text_segment_id"))
                    text_segment_track[len(text_segment_ids) - 1] = track_name
                else:
                    summary["warnings"].append(f"text segment rebuild failed: {mid}")


    def _normalize_list(val):
        if val is None:
            return []
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            return [val]
        return []

    def _ids_by_track(ids, item, track_name_map):
        tname = item.get('track')
        if not tname:
            return _ids_by_index(ids, item)
        selected = []
        for i, sid in enumerate(ids):
            if track_name_map.get(i) == tname:
                selected.append(sid)
        if 'indexes' in item and isinstance(item['indexes'], list):
            return [selected[i] for i in item['indexes'] if 0 <= i < len(selected)]
        if 'index' in item and isinstance(item['index'], int):
            i = item['index']
            return [selected[i]] if 0 <= i < len(selected) else []
        return selected

    def _ids_by_index(ids, item):
        if "indexes" in item and isinstance(item["indexes"], list):
            return [ids[i] for i in item["indexes"] if 0 <= i < len(ids)]
        if "index" in item:
            i = item["index"]
            if isinstance(i, int) and 0 <= i < len(ids):
                return [ids[i]]
        return ids

    video_cfg = effects_config.get("video", {})
    text_cfg = effects_config.get("text", {})
    audio_cfg = effects_config.get("audio", {})
    duo_cfg = {}
    if duo_config:
        try:
            from app.services.duo_video_service import DuoVideoService
            duo_svc = DuoVideoService()
            duo_mapped = duo_svc.build_effects_config(duo_config)
            # merge duo into effects_config
            for k in ("filters", "effects", "animations", "transitions", "masks", "keyframes", "background"):
                if duo_mapped["video"].get(k):
                    video_cfg.setdefault(k, [])
                    video_cfg[k].extend(duo_mapped["video"].get(k))
            for k in ("animations", "bubbles", "effects"):
                if duo_mapped["text"].get(k):
                    text_cfg.setdefault(k, [])
                    text_cfg[k].extend(duo_mapped["text"].get(k))
            for k in ("effects", "fades", "keyframes"):
                if duo_mapped["audio"].get(k):
                    audio_cfg.setdefault(k, [])
                    audio_cfg[k].extend(duo_mapped["audio"].get(k))
            duo_cfg = duo_mapped.get("_duo", {})
        except Exception as e:
            summary["warnings"].append(f"duo config map failed: {e}")

    existing_tracks = set(track_name_by_index.values())
    has_mcp_effects = any([
        video_cfg.get('filters'), video_cfg.get('effects'), video_cfg.get('animations'), video_cfg.get('transitions'), video_cfg.get('masks'), video_cfg.get('background'), video_cfg.get('keyframes'),
        text_cfg.get('animations'), text_cfg.get('bubbles'), text_cfg.get('effects'),
        audio_cfg.get('effects'), audio_cfg.get('fades'), audio_cfg.get('keyframes')
    ])
    has_duo_pre = any([duo_cfg.get('green_screen'), duo_cfg.get('reverse'), duo_cfg.get('lut'), duo_cfg.get('text_styles')])
    if not has_mcp_effects and has_duo_pre and not duo_cfg.get('stickers'):
        _apply_duo_preprocess(duo_cfg, data)
        _apply_text_char_styles(duo_cfg.get('text_styles'))
        summary['applied'].append('duo_preprocess_only')
        return summary

    if duo_cfg.get('stickers'):
        # create overlay track for stickers
        resp = svc.create_track(draft_id, 'video', 'sticker_overlay')
        if resp and getattr(resp, 'ok', False) and resp.data and resp.data.get('track_name'):
            overlay_track_name = resp.data.get('track_name')
        else:
            overlay_track_name = 'sticker_overlay'

    # stickers overlay
    if duo_cfg.get('stickers') and overlay_track_name:
        try:
            from app.services.duo_video_service import DuoVideoService
            duo_svc = DuoVideoService()
        except Exception:
            duo_svc = None
        for item in duo_cfg.get('stickers') or []:
            path = item.get('path')
            url = item.get('url')
            if not path and url and duo_svc:
                path = duo_svc.download_resource(url)
            if not path:
                summary['warnings'].append('sticker asset missing')
                continue
            timerange = item.get('timerange') or '0s-3s'
            clip_settings = item.get('clip_settings') if isinstance(item.get('clip_settings'), dict) else None
            track = item.get('track') or overlay_track_name
            if track and track not in existing_tracks:
                resp_track = svc.create_track(draft_id, 'video', track)
                if resp_track and getattr(resp_track, 'ok', False) and resp_track.data and resp_track.data.get('track_name'):
                    track = resp_track.data.get('track_name')
                existing_tracks.add(track)
            resp = svc.add_video_segment(draft_id, path, timerange, clip_settings=clip_settings, track_name=track)
            _record(resp, 'sticker')

    def _dedupe(items):
        seen = set()
        result = []
        for item in items or []:
            try:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            except Exception:
                key = str(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    for k in ("filters", "effects", "animations", "transitions", "masks", "background", "keyframes"):
        if isinstance(video_cfg.get(k), list):
            video_cfg[k] = _dedupe(video_cfg.get(k))
    for k in ("animations", "bubbles", "effects"):
        if isinstance(text_cfg.get(k), list):
            text_cfg[k] = _dedupe(text_cfg.get(k))
    for k in ("effects", "fades", "keyframes"):
        if isinstance(audio_cfg.get(k), list):
            audio_cfg[k] = _dedupe(audio_cfg.get(k))

    def _apply_text_char_styles(text_styles):
        if not text_styles:
            return
        try:
            with open(draft_content, 'r', encoding='utf-8') as f:
                local_data = json.load(f)
        except Exception:
            return
        active_local_data = _resolve_active_draft_payload(local_data)
        text_mats_local = {m.get('id'): m for m in active_local_data.get('materials', {}).get('texts', []) if isinstance(m, dict)}
        for item in text_styles:
            idx = item.get('index')
            styles = item.get('styles')
            if idx is None or not isinstance(styles, list):
                continue
            target = None
            if isinstance(idx, int):
                track_ids = []
                for tr in active_local_data.get('tracks', []):
                    if tr.get('type') != 'text':
                        continue
                    for seg in tr.get('segments', []):
                        if seg.get('material_id'):
                            track_ids.append(seg.get('material_id'))
                if 0 <= idx < len(track_ids):
                    target = text_mats_local.get(track_ids[idx])
            if not target:
                continue
            content = target.get('content')
            if not content:
                continue
            try:
                content_json = json.loads(content)
            except Exception:
                continue
            content_json['styles'] = styles
            target['content'] = json.dumps(content_json, ensure_ascii=False)
        try:
            with open(draft_content, 'w', encoding='utf-8') as f:
                json.dump(local_data, f, ensure_ascii=False)
        except Exception:
            return

    def _apply_duo_preprocess(duo_cfg, draft_data):
        if not duo_cfg:
            return
        active_draft_data = _resolve_active_draft_payload(draft_data)
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            if duo_cfg.get('reverse'):
                summary['warnings'].append('reverse requested: ffmpeg not found')
            if duo_cfg.get('lut'):
                summary['warnings'].append('lut requested: ffmpeg not found')
            if duo_cfg.get('green_screen'):
                summary['warnings'].append('green_screen requested: ffmpeg not found')
            return

        def _material_by_index(video_index):
            track_ids = []
            for tr in active_draft_data.get('tracks', []):
                if tr.get('type') != 'video':
                    continue
                for seg in tr.get('segments', []):
                    if seg.get('material_id'):
                        track_ids.append(seg.get('material_id'))
            if isinstance(video_index, int) and 0 <= video_index < len(track_ids):
                return track_ids[video_index]
            return None

        def _replace_material_path(mat_id, new_path):
            for m in active_draft_data.get('materials', {}).get('videos', []):
                if m.get('id') == mat_id:
                    m['path'] = new_path
                    if 'file_path' in m:
                        m['file_path'] = new_path
                    return True
            return False

        def _run(cmd):
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    **_quiet_subprocess_kwargs(),
                )
                return True
            except Exception as e:
                summary['warnings'].append(f'ffmpeg failed: {e}')
                return False

        # reverse
        for item in duo_cfg.get('reverse') or []:
            idx = item.get('video_index')
            mid = item.get('material_id') or _material_by_index(idx)
            if not mid:
                summary['warnings'].append('reverse: target not found')
                continue
            m = next((x for x in active_draft_data.get('materials', {}).get('videos', []) if x.get('id') == mid), None)
            if not m:
                continue
            src = m.get('path') or m.get('file_path')
            if not src:
                continue
            out_path = os.path.join(os.path.dirname(src), f'rev_{os.path.basename(src)}')
            cmd = [ffmpeg, '-y', '-i', src, '-vf', 'reverse', '-af', 'areverse', out_path]
            if _run(cmd):
                _replace_material_path(mid, out_path)
                summary['applied'].append('reverse')

        # lut
        for item in duo_cfg.get('lut') or []:
            idx = item.get('video_index')
            mid = item.get('material_id') or _material_by_index(idx)
            lut_path = item.get('lut_path')
            if not mid or not lut_path:
                summary['warnings'].append('lut: target or lut missing')
                continue
            m = next((x for x in active_draft_data.get('materials', {}).get('videos', []) if x.get('id') == mid), None)
            if not m:
                continue
            src = m.get('path') or m.get('file_path')
            if not src:
                continue
            out_path = os.path.join(os.path.dirname(src), f'lut_{os.path.basename(src)}')
            cmd = [ffmpeg, '-y', '-i', src, '-vf', f'lut3d={lut_path}', out_path]
            if _run(cmd):
                _replace_material_path(mid, out_path)
                summary['applied'].append('lut')

        # green screen (chroma key)
        for item in duo_cfg.get('green_screen') or []:
            idx = item.get('video_index')
            mid = item.get('material_id') or _material_by_index(idx)
            bg_path = item.get('bg_path')
            key_color = item.get('key_color', '0x00FF00')
            similarity = item.get('tolerance', 0.2)
            blend = item.get('feather', 0.1)
            if not mid or not bg_path:
                summary['warnings'].append('green_screen: target or background missing')
                continue
            m = next((x for x in active_draft_data.get('materials', {}).get('videos', []) if x.get('id') == mid), None)
            if not m:
                continue
            src = m.get('path') or m.get('file_path')
            if not src:
                continue
            out_path = os.path.join(os.path.dirname(src), f'ck_{os.path.basename(src)}')
            filter_complex = f"[0:v]chromakey={key_color}:{similarity}:{blend}[ck];[1:v][ck]overlay=format=auto"
            cmd = [ffmpeg, '-y', '-i', src, '-i', bg_path, '-filter_complex', filter_complex, out_path]
            if _run(cmd):
                _replace_material_path(mid, out_path)
                summary['applied'].append('green_screen')

        try:
            with open(draft_content, 'w', encoding='utf-8') as f:
                json.dump(draft_data, f, ensure_ascii=False)
        except Exception as e:
            summary['warnings'].append(f'draft_content write failed: {e}')



    def _record(result, label):
        try:
            if result and getattr(result, "ok", False):
                summary["applied"].append(label)
            else:
                summary["warnings"].append(f"failed: {label}")
        except Exception:
            summary["warnings"].append(f"failed: {label}")

    if not video_segment_ids and (video_cfg.get("filters") or video_cfg.get("effects") or video_cfg.get("animations") or video_cfg.get("transitions") or video_cfg.get("masks") or video_cfg.get("background") or video_cfg.get("keyframes")):
        summary["warnings"].append("no video segments to apply video effects")
    if not audio_segment_ids and (audio_cfg.get("effects") or audio_cfg.get("fades") or audio_cfg.get("keyframes")):
        summary["warnings"].append("no audio segments to apply audio effects")
    if not text_segment_ids and (text_cfg.get("animations") or text_cfg.get("bubbles") or text_cfg.get("effects")):
        summary["warnings"].append("no text segments to apply text effects")

    # duo preprocess (best-effort)
    _apply_duo_preprocess(duo_cfg, data)
    _apply_text_char_styles(duo_cfg.get('text_styles'))

    # video filters
    for item in _normalize_list(video_cfg.get("filters")):
        ftype = item.get("type")
        intensity = float(item.get("intensity", 80))
        if not ftype:
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_filter(draft_id, sid, ftype, intensity), f"video_filter:{ftype}")

    # video effects
    for item in _normalize_list(video_cfg.get("effects")):
        etype = item.get("type")
        params = item.get("params")
        if not etype:
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_effect(draft_id, sid, etype, params), f"video_effect:{etype}")

    # video animations
    for item in _normalize_list(video_cfg.get("animations")):
        atype = item.get("type")
        name = item.get("name")
        duration = item.get("duration")
        if not (atype and name):
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_animation(draft_id, sid, atype, name, duration), f"video_anim:{atype}:{name}")

    # video transitions
    for item in _normalize_list(video_cfg.get("transitions")):
        ttype = item.get("type")
        duration = item.get("duration")
        if not ttype:
            continue
        targets = _ids_by_track(video_segment_ids, item, video_segment_track)
        # default: from second segment
        if targets == video_segment_ids:
            targets = video_segment_ids[1:]
        for sid in targets:
            _record(svc.add_video_transition(draft_id, sid, ttype, duration), f"transition:{ttype}")

    # video masks
    for item in _normalize_list(video_cfg.get("masks")):
        mtype = item.get("type")
        if not mtype:
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_mask(
                draft_id,
                sid,
                mtype,
                item.get("center_x", 0.0),
                item.get("center_y", 0.0),
                item.get("size", 0.5),
                item.get("rotation", 0.0),
                item.get("feather", 0.0),
                item.get("invert", False),
                item.get("rect_width"),
                item.get("round_corner"),
            ), f"mask:{mtype}")

    # video background filling
    for item in _normalize_list(video_cfg.get("background")):
        ftype = item.get("type")
        if not ftype:
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_background_filling(
                draft_id,
                sid,
                ftype,
                item.get("blur", 0.0625),
                item.get("color", "#00000000"),
            ), f"background:{ftype}")

    # video keyframes
    for item in _normalize_list(video_cfg.get("keyframes")):
        prop = item.get("property")
        time_offset = item.get("time")
        value = item.get("value")
        if prop is None or time_offset is None or value is None:
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_keyframe(draft_id, sid, prop, time_offset, value), f"video_keyframe:{prop}@{time_offset}")

    # micro adjust shake keyframes
    if micro_cfg and video_segment_ids:
        shake_cfg = micro_cfg.get("shake") or {}
        try:
            interval = float(shake_cfg.get("interval", 0.2))
        except Exception:
            interval = 0.2
        try:
            max_keys = int(shake_cfg.get("max_keys", 12))
        except Exception:
            max_keys = 12
        try:
            intensity_x = float(shake_cfg.get("intensity_x", shake_cfg.get("intensity", 0)))
        except Exception:
            intensity_x = 0.0
        try:
            intensity_y = float(shake_cfg.get("intensity_y", shake_cfg.get("intensity", 0)))
        except Exception:
            intensity_y = 0.0
        if interval > 0 and max_keys > 0 and (intensity_x > 0 or intensity_y > 0):
            for idx, sid in enumerate(video_segment_ids):
                meta = video_segment_meta[idx] if idx < len(video_segment_meta) else {}
                if meta.get("apply_micro") is False:
                    continue
                duration = meta.get("duration") or 0
                if duration <= 0:
                    continue
                times = []
                t = 0.0
                while t < duration and len(times) < max_keys:
                    times.append(t)
                    t += interval
                if not times:
                    times = [0.0]
                for t in times:
                    t_str = f"{t:.3f}s"
                    if intensity_x > 0:
                        value = random.uniform(-intensity_x, intensity_x)
                        _record(svc.add_video_keyframe(draft_id, sid, "position_x", t_str, value, track_name=meta.get("track")),
                                f"micro_shake_x@{t_str}")
                        micro_applied = True
                    if intensity_y > 0:
                        value = random.uniform(-intensity_y, intensity_y)
                        _record(svc.add_video_keyframe(draft_id, sid, "position_y", t_str, value, track_name=meta.get("track")),
                                f"micro_shake_y@{t_str}")
                        micro_applied = True

    # text animations
    for item in _normalize_list(text_cfg.get("animations")):
        atype = item.get("type")
        name = item.get("name")
        duration = item.get("duration")
        if not (atype and name):
            continue
        for sid in _ids_by_track(text_segment_ids, item, text_segment_track):
            _record(svc.add_text_animation(draft_id, sid, atype, name, duration), f"text_anim:{atype}:{name}")

    # text bubbles
    for item in _normalize_list(text_cfg.get("bubbles")):
        effect_id = item.get("effect_id")
        resource_id = item.get("resource_id")
        if not (effect_id and resource_id):
            continue
        for sid in _ids_by_track(text_segment_ids, item, text_segment_track):
            _record(svc.add_text_bubble(draft_id, sid, effect_id, resource_id), f"text_bubble:{effect_id}")

    # text effects
    for item in _normalize_list(text_cfg.get("effects")):
        effect_id = item.get("effect_id")
        if not effect_id:
            continue
        for sid in _ids_by_track(text_segment_ids, item, text_segment_track):
            _record(svc.add_text_effect(draft_id, sid, effect_id), f"text_effect:{effect_id}")

    # audio effects
    for item in _normalize_list(audio_cfg.get("effects")):
        etype = item.get("type")
        name = item.get("name")
        params = item.get("params")
        if not (etype and name):
            continue
        for sid in _ids_by_track(audio_segment_ids, item, audio_segment_track):
            _record(svc.add_audio_effect(draft_id, sid, etype, name, params), f"audio_effect:{etype}:{name}")

    # audio fades
    for item in _normalize_list(audio_cfg.get("fades")):
        in_dur = item.get("in")
        out_dur = item.get("out")
        if not (in_dur and out_dur):
            continue
        for sid in _ids_by_track(audio_segment_ids, item, audio_segment_track):
            _record(svc.add_audio_fade(draft_id, sid, in_dur, out_dur), "audio_fade")

    # audio keyframes
    for item in _normalize_list(audio_cfg.get("keyframes")):
        time_offset = item.get("time")
        volume = item.get("volume")
        if time_offset is None or volume is None:
            continue
        for sid in _ids_by_track(audio_segment_ids, item, audio_segment_track):
            _record(svc.add_audio_keyframe(draft_id, sid, time_offset, volume), f"audio_keyframe@{time_offset}")

    if micro_applied and "micro_adjust" not in summary["applied"]:
        summary["applied"].append("micro_adjust")

    if expected_video_segments > 0 and not video_segment_ids:
        raise RuntimeError("MCP rebuild produced no video segments")
    if expected_audio_segments > 0 and not audio_segment_ids:
        summary["warnings"].append("MCP rebuild produced no audio segments")

    # export
    export_target = str(output_path or "").strip() or os.getenv("OUTPUT_PATH")
    if force_export and not export_target:
        summary["warnings"].append("export skipped: output path missing")
    elif export_target:
        result = svc.export_draft(draft_id, jianying_draft_path=export_target)
        if result.ok and result.data:
            print(f"[DEBUG] MCP 效果草稿已导出: {result.data.get('draft_name')}")
            summary["applied"].append(f"export:{result.data.get('draft_name')}")
            summary["exported_draft_name"] = result.data.get("draft_name")
            summary["export_output"] = result.data.get("output")
        else:
            summary["warnings"].append("export failed")

    return summary


def generate_ai_task(task_id: str, user_id: int, key_id: int, task_type: str, payload: dict, save_text_file: bool = False):
    app = create_app()
    with app.app_context():
        from app.models.ai_task import AITask
        from app.models.user import User
        from app.models.user_api_key import UserApiKey
        from app.services.ai_service import generate_with_key
        from app.views.api import _resolve_ai_runtime_key, _apply_quota_charge, _quota_has_unlimited_access
        from app.services.user_quota_service import get_or_create_quota

        task = AITask.query.get(task_id)
        if not task:
            return
        task.status = "started"
        db.session.add(task)
        db.session.commit()

        key = None
        if int(key_id or 0) > 0:
            key = UserApiKey.query.filter_by(id=key_id, user_id=user_id).first()
        else:
            user = User.query.get(user_id)
            if user:
                key = _resolve_ai_runtime_key(user, task_type, None)
        if not key:
            task.status = "failed"
            task.error_msg = "没有可用的 AI 账号或系统预设 Key"
            db.session.add(task)
            db.session.commit()
            return

        result = generate_with_key(key, task_type, payload, save_text_file=save_text_file)
        if not result.get("ok"):
            task.status = "failed"
            task.error_msg = result.get("error") or "生成失败"
        else:
            task.status = "success"
            task.result_path = result.get("path")
            if task_type == "text":
                task.result_text = result.get("text") or ""
            quota_cost = int(payload.get("quota_cost") or 0)
            quota_reason = str(payload.get("quota_reason") or "").strip()
            if quota_cost > 0 and quota_reason:
                quota = get_or_create_quota(user_id)
                if not _quota_has_unlimited_access(quota):
                    _apply_quota_charge(quota, user_id, quota_cost, quota_reason, project_id=task_id)
        db.session.add(task)
        db.session.commit()
