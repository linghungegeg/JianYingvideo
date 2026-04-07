import json
import os
import ctypes
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from app.services.jianying.local_draft_service import (
    load_json_file_with_encodings,
    normalize_draft_project_path,
)
from app.services.jianying import official_draft_codec as official_codec
from app.services.jianying.draft_replacement_strategy import (
    copy_into_cache_target as _strategy_copy_into_cache_target,
    path_requires_preserved_image_target_name,
    payload_has_selfbuilt_draftpath_semantics,
    replace_materials,
)
from app.utils.ffmpeg_utils import find_ffmpeg
from app.utils.helpers import get_drafts_folder
from app.utils.runtime_paths import app_resource_path
from app.utils.jianying_mcp.utils.media_parser import parse_media_info


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".m4v"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
_GG_ASSISTANT_SOFTWARE_KEY = "gg-jy-assistant"
_OFFICIAL_READER_RUNTIME_DIRNAME = "official_reader"
_OFFICIAL_READER_RUNTIME_MODE_ENV = "VF_OFFICIAL_READER_RUNTIME_MODE"
_OFFICIAL_READER_ALLOW_GG_FALLBACK_ENV = "VF_OFFICIAL_READER_ALLOW_GG_FALLBACK"
_OFFICIAL_DRAFT_CONTENT_EMBEDDED_KEY_OFFSETS = official_codec.OFFICIAL_DRAFT_CONTENT_EMBEDDED_KEY_OFFSETS
_OFFICIAL_DRAFT_CONTENT_EMBEDDED_IV_OFFSETS = official_codec.OFFICIAL_DRAFT_CONTENT_EMBEDDED_IV_OFFSETS


def _copy_into_cache_target(source_path: str, target_path: str) -> str:
    return _strategy_copy_into_cache_target(source_path, target_path, _IMAGE_EXTS)


def _quiet_subprocess_kwargs() -> dict:
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
        value = contents[0]
        if value is None:
            continue
        replacements[idx] = str(value)
    return replacements


def _normalize_material_replacement_map(material_replacements):
    normalized = {}
    if not isinstance(material_replacements, dict):
        return normalized
    for key, value in material_replacements.items():
        norm_key = str(key or "").strip().lower()
        norm_value = str(value or "").strip()
        if not norm_key or not norm_value:
            continue
        normalized[norm_key] = norm_value
    return normalized


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
        value = material_replacements.get(key)
        if value:
            return value
    return None


def _detect_media_kind(path: str) -> str:
    ext = os.path.splitext(str(path or ""))[1].lower()
    if ext in _IMAGE_EXTS:
        return "images"
    if ext in _AUDIO_EXTS:
        return "audios"
    if ext in _VIDEO_EXTS:
        return "videos"
    return ""


def _parse_replacement_media_info(path_value: str) -> dict:
    source_path = str(path_value or "").strip()
    info = parse_media_info(source_path) or {}
    if not os.path.isfile(source_path):
        return info
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in _IMAGE_EXTS:
        return info
    if isinstance(info.get("width"), int) and info.get("width") > 0 and isinstance(info.get("height"), int) and info.get("height") > 0:
        return info
    try:
        from PIL import Image

        with Image.open(source_path) as img:
            width, height = img.size
        if width > 0:
            info["width"] = int(width)
        if height > 0:
            info["height"] = int(height)
    except Exception:
        return info
    return info


def _clone_draft_tree(template_path: str, output_root: Optional[str], draft_name: str) -> tuple[str, str]:
    normalized_template_path = normalize_draft_project_path(template_path)
    if not normalized_template_path or not os.path.isdir(normalized_template_path):
        raise ValueError("template_path is invalid")

    drafts_root = str(output_root or get_drafts_folder() or "").strip()
    if not drafts_root:
        drafts_root = os.path.dirname(normalized_template_path.rstrip("\\/"))
    if not drafts_root:
        raise ValueError("drafts folder is not configured")

    os.makedirs(drafts_root, exist_ok=True)
    final_path = os.path.join(drafts_root, draft_name)
    if os.path.exists(final_path):
        raise FileExistsError(f"draft already exists: {final_path}")
    staging_root = tempfile.mkdtemp(prefix="vf_official_stage_")
    staging_path = os.path.join(staging_root, draft_name)
    shutil.copytree(normalized_template_path, staging_path)
    return staging_path, final_path


def _map_path_between_roots(path_value: str, old_root: str, new_root: str) -> str:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return raw_path
    try:
        old_norm = _norm_abs(old_root)
        path_norm = _norm_abs(raw_path)
        if path_norm == old_norm or path_norm.startswith(old_norm + os.sep):
            rel_path = os.path.relpath(path_norm, old_norm)
            return os.path.join(new_root, rel_path)
    except Exception:
        return raw_path
    return raw_path


def _publish_generated_draft(staging_path: str, final_path: str) -> str:
    if not staging_path or not final_path:
        raise ValueError("staging_path/final_path is required")
    final_parent = os.path.dirname(final_path)
    if final_parent:
        os.makedirs(final_parent, exist_ok=True)
    if os.path.exists(final_path):
        raise FileExistsError(f"draft already exists: {final_path}")
    shutil.move(staging_path, final_path)
    staging_root = os.path.dirname(staging_path)
    try:
        if staging_root and os.path.isdir(staging_root) and not os.listdir(staging_root):
            os.rmdir(staging_root)
    except Exception:
        pass
    return final_path


def _update_draft_meta_info(cloned_draft_path: str, draft_name: str) -> None:
    meta_path = os.path.join(cloned_draft_path, "draft_meta_info.json")
    if not os.path.exists(meta_path):
        return
    meta, is_plain = _load_draft_meta_info_payload(meta_path)
    if not isinstance(meta, dict):
        return

    now_us = int(time.time() * 1000000)
    meta["draft_name"] = draft_name
    meta["draft_fold_path"] = _normalize_path_slashes(cloned_draft_path)
    if "draft_id" in meta:
        meta["draft_id"] = str(uuid.uuid4()).upper()
    meta["tm_draft_create"] = now_us
    meta["tm_draft_modified"] = now_us
    normalized = _normalize_generated_draft_meta(meta, cloned_draft_path, draft_name)
    _write_draft_meta_info_payload(meta_path, normalized, is_plain)


def _update_draft_meta_info_with_info_path(cloned_draft_path: str, draft_name: str, info_path: str) -> None:
    meta_path = os.path.join(cloned_draft_path, "draft_meta_info.json")
    if not os.path.exists(meta_path):
        return

    meta, is_plain = _load_draft_meta_info_payload(meta_path)
    if not isinstance(meta, dict):
        return

    now_us = int(time.time() * 1000000)
    meta["draft_name"] = draft_name
    meta["draft_fold_path"] = _normalize_path_slashes(cloned_draft_path)
    if "draft_json_file" in meta:
        meta["draft_json_file"] = str(info_path or "").strip() or meta.get("draft_json_file")
    meta["tm_draft_create"] = now_us
    meta["tm_draft_modified"] = now_us
    normalized = _normalize_generated_draft_meta(meta, cloned_draft_path, draft_name, info_path)
    _write_draft_meta_info_payload(meta_path, normalized, is_plain)


def _load_draft_meta_info_payload(meta_path: str) -> tuple[Optional[dict], bool]:
    if not meta_path or not os.path.exists(meta_path):
        return None, True
    if _looks_like_plain_json(meta_path):
        loaded, err = load_json_file_with_encodings(meta_path)
        if err is None and isinstance(loaded, dict):
            return loaded, True
        return None, True
    try:
        loaded, _diag = _load_official_encrypted_draft_content(meta_path)
    except Exception:
        return None, False
    if isinstance(loaded, dict):
        return loaded, False
    return None, False


def _write_draft_meta_info_payload(meta_path: str, meta: dict, is_plain: bool) -> None:
    if not meta_path or not isinstance(meta, dict):
        return
    try:
        if is_plain:
            with open(meta_path, "w", encoding="utf-8") as handle:
                json.dump(meta, handle, ensure_ascii=False, indent=2)
            return
        official_codec.write_official_draft_payload(meta_path, meta)
    except Exception:
        return


def _sum_directory_file_sizes(path_value: str) -> int:
    total = 0
    try:
        for path_obj in Path(path_value).rglob("*"):
            if path_obj.is_file():
                total += int(path_obj.stat().st_size or 0)
    except Exception:
        return 0
    return total


def _iter_payload_material_paths(payload: dict, material_keys: tuple[str, ...] = ("videos", "audios")):
    if not isinstance(payload, dict):
        return
    materials = payload.get("materials") or {}
    if isinstance(materials, dict):
        for material_key in material_keys:
            for item in materials.get(material_key) or []:
                if not isinstance(item, dict):
                    continue
                path_value = str(item.get("path") or item.get("file_path") or "").strip()
                if path_value:
                    yield path_value
    for value in payload.values():
        if isinstance(value, dict):
            yield from _iter_payload_material_paths(value, material_keys)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, dict):
                    yield from _iter_payload_material_paths(child, material_keys)


def _estimate_generated_timeline_materials_size(payload: dict, cloned_draft_path: str) -> int:
    draft_total = _sum_directory_file_sizes(cloned_draft_path)
    if not isinstance(payload, dict):
        return draft_total

    draft_root_norm = _norm_abs(cloned_draft_path)
    external_total = 0
    counted_paths: set[str] = set()
    for raw_path in _iter_payload_material_paths(payload):
        resolved_path = (
            raw_path
            if os.path.isabs(raw_path)
            else os.path.join(cloned_draft_path, raw_path.replace("/", os.sep))
        )
        if not os.path.isfile(resolved_path):
            continue
        norm_path = _norm_abs(resolved_path)
        if norm_path == draft_root_norm or norm_path.startswith(draft_root_norm + os.sep):
            continue
        lowered = norm_path.replace("\\", "/").lower()
        if "/cache/effect/" in lowered:
            continue
        if norm_path in counted_paths:
            continue
        counted_paths.add(norm_path)
        try:
            external_total += int(os.path.getsize(resolved_path) or 0)
        except Exception:
            continue

    return draft_total + external_total


def _normalize_generated_draft_meta(
    meta: dict,
    cloned_draft_path: str,
    draft_name: str,
    info_path: str = "",
    payload: Optional[dict] = None,
) -> dict:
    normalized = dict(meta or {})
    now_us = int(time.time() * 1000000)
    draft_content_path = str(info_path or os.path.join(cloned_draft_path, "draft_content.json")).strip()
    draft_file_size = 0
    draft_duration = 0
    try:
        if draft_content_path and os.path.isfile(draft_content_path):
            payload, err = load_json_file_with_encodings(draft_content_path)
            if err is None and isinstance(payload, dict):
                draft_duration = int(payload.get("duration") or 0)
    except Exception:
        draft_duration = 0

    draft_file_size = _estimate_generated_timeline_materials_size(payload or {}, cloned_draft_path)

    normalized["draft_id"] = str(normalized.get("draft_id") or "").strip() or str(uuid.uuid4()).upper()
    normalized["draft_name"] = draft_name
    normalized["draft_fold_path"] = _normalize_path_slashes(cloned_draft_path)
    normalized["draft_root_path"] = _normalize_path_slashes(os.path.dirname(cloned_draft_path))
    normalized["draft_json_file"] = None
    normalized["draft_cover"] = "draft_cover.jpg"
    normalized["draft_need_rename_folder"] = False
    normalized["draft_is_invisible"] = False
    normalized["cloud_draft_cover"] = False
    normalized["cloud_draft_sync"] = False
    normalized["draft_cloud_last_action_download"] = False
    normalized["draft_cloud_purchase_info"] = ""
    normalized["draft_cloud_template_id"] = ""
    normalized["draft_cloud_tutorial_info"] = ""
    normalized["draft_cloud_videocut_purchase_info"] = ""
    normalized["tm_draft_cloud_completed"] = ""
    normalized["tm_draft_cloud_entry_id"] = -1
    normalized["tm_draft_cloud_modified"] = 0
    normalized["tm_draft_cloud_parent_entry_id"] = -1
    normalized["tm_draft_cloud_space_id"] = -1
    normalized["tm_draft_cloud_user_id"] = -1
    normalized["draft_timeline_materials_size_"] = draft_file_size
    if draft_duration > 0:
        normalized["tm_duration"] = draft_duration
    normalized["tm_draft_create"] = now_us
    normalized["tm_draft_modified"] = now_us
    if not str(normalized.get("draft_removable_storage_device") or "").strip():
        drive, _tail = os.path.splitdrive(cloned_draft_path)
        normalized["draft_removable_storage_device"] = drive or ""
    return normalized


def _build_generated_root_meta_entry(meta: dict, cloned_draft_path: str, info_path: str) -> dict:
    draft_size = int(meta.get("draft_timeline_materials_size_") or 0)
    return {
        "cloud_draft_cover": bool(meta.get("cloud_draft_cover", False)),
        "cloud_draft_sync": bool(meta.get("cloud_draft_sync", False)),
        "draft_cloud_last_action_download": bool(meta.get("draft_cloud_last_action_download", False)),
        "draft_cloud_purchase_info": str(meta.get("draft_cloud_purchase_info") or ""),
        "draft_cloud_template_id": str(meta.get("draft_cloud_template_id") or ""),
        "draft_cloud_tutorial_info": str(meta.get("draft_cloud_tutorial_info") or ""),
        "draft_cloud_videocut_purchase_info": str(meta.get("draft_cloud_videocut_purchase_info") or ""),
        "draft_cover": _normalize_path_slashes(os.path.join(cloned_draft_path, "draft_cover.jpg")),
        "draft_fold_path": _normalize_path_slashes(cloned_draft_path),
        "draft_id": str(meta.get("draft_id") or "").strip(),
        "draft_is_ai_shorts": bool(meta.get("draft_is_ai_shorts", False)),
        "draft_is_cloud_temp_draft": bool(meta.get("draft_is_cloud_temp_draft", False)),
        "draft_is_invisible": bool(meta.get("draft_is_invisible", False)),
        "draft_is_web_article_video": bool(meta.get("draft_is_web_article_video", False)),
        "draft_json_file": _normalize_path_slashes(info_path),
        "draft_name": str(meta.get("draft_name") or os.path.basename(cloned_draft_path.rstrip("\\/"))),
        "draft_new_version": str(meta.get("draft_new_version") or ""),
        "draft_root_path": _normalize_path_slashes(str(meta.get("draft_root_path") or os.path.dirname(cloned_draft_path))),
        "draft_timeline_materials_size": draft_size,
        "draft_type": str(meta.get("draft_type") or ""),
        "draft_web_article_video_enter_from": str(meta.get("draft_web_article_video_enter_from") or ""),
        "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": meta.get("tm_draft_cloud_completed") or "",
        "tm_draft_cloud_entry_id": int(meta.get("tm_draft_cloud_entry_id") or -1),
        "tm_draft_cloud_modified": int(meta.get("tm_draft_cloud_modified") or 0),
        "tm_draft_cloud_parent_entry_id": int(meta.get("tm_draft_cloud_parent_entry_id") or -1),
        "tm_draft_cloud_space_id": int(meta.get("tm_draft_cloud_space_id") or -1),
        "tm_draft_cloud_user_id": int(meta.get("tm_draft_cloud_user_id") or -1),
        "tm_draft_create": int(meta.get("tm_draft_create") or 0),
        "tm_draft_modified": int(meta.get("tm_draft_modified") or 0),
        "tm_draft_removed": int(meta.get("tm_draft_removed") or 0),
        "tm_duration": int(meta.get("tm_duration") or 0),
    }


def _sync_generated_root_meta_index(cloned_draft_path: str, info_path: str, meta: dict) -> None:
    if not isinstance(meta, dict):
        return
    draft_id = str(meta.get("draft_id") or "").strip()
    draft_fold_path = _normalize_path_slashes(cloned_draft_path)
    draft_json_file = _normalize_path_slashes(info_path)
    entry = _build_generated_root_meta_entry(meta, cloned_draft_path, info_path)
    for root_meta_path in _candidate_root_meta_paths():
        if not os.path.exists(root_meta_path):
            continue
        payload, err = load_json_file_with_encodings(root_meta_path)
        if err is not None or not isinstance(payload, dict):
            continue
        entries = payload.get("all_draft_store") or []
        if not isinstance(entries, list):
            entries = []
        filtered_entries = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            item_draft_id = str(item.get("draft_id") or "").strip()
            item_fold_path = _normalize_path_slashes(str(item.get("draft_fold_path") or "").strip())
            item_json_file = _normalize_path_slashes(str(item.get("draft_json_file") or "").strip())
            if draft_id and item_draft_id == draft_id:
                continue
            if item_fold_path and item_fold_path == draft_fold_path:
                continue
            if item_json_file and item_json_file == draft_json_file:
                continue
            filtered_entries.append(item)
        filtered_entries.append(entry)
        filtered_entries.sort(
            key=lambda item: int(item.get("tm_draft_modified") or item.get("tm_draft_create") or 0),
            reverse=True,
        )
        payload["all_draft_store"] = filtered_entries
        payload["draft_ids"] = len(filtered_entries)
        payload["root_path"] = _normalize_path_slashes(
            str(payload.get("root_path") or os.path.dirname(root_meta_path))
        )
        with open(root_meta_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)


def _finalize_generated_draft_meta_and_root_index(
    cloned_draft_path: str,
    draft_name: str,
    info_path: str,
    payload: Optional[dict],
) -> dict:
    meta_path = os.path.join(cloned_draft_path, "draft_meta_info.json")
    if not os.path.exists(meta_path):
        return {}
    meta, is_plain = _load_draft_meta_info_payload(meta_path)
    if not isinstance(meta, dict):
        return {}
    normalized = _normalize_generated_draft_meta(
        meta,
        cloned_draft_path,
        draft_name,
        info_path,
        payload,
    )
    _write_draft_meta_info_payload(meta_path, normalized, is_plain)
    _sync_generated_root_meta_index(cloned_draft_path, info_path, normalized)
    return normalized


def _resolve_primary_draft_content_path(cloned_draft_path: str) -> str:
    return os.path.join(cloned_draft_path, "draft_content.json")


def _candidate_root_meta_paths() -> list[str]:
    home = Path.home()
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
    candidates = [
        local_app_data / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft" / "root_meta_info.json",
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        norm = os.path.normpath(str(item))
        lowered = norm.lower()
        if not norm or lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(norm)
    return deduped


def _candidate_jianying_visual_cache_dirs() -> list[str]:
    home = Path.home()
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
    candidates = [
        local_app_data / "JianyingPro" / "User Data" / "Cache" / "frameThumbnail",
        local_app_data / "JianyingPro" / "User Data" / "Cache" / "segmentPrerenderCache",
        local_app_data / "JianyingPro" / "User Data" / "Cache" / "prerender",
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        norm = os.path.normpath(str(item))
        lowered = norm.lower()
        if not norm or lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(norm)
    return deduped


def _clear_directory_children(path_value: str) -> dict:
    path_text = os.path.normpath(str(path_value or "").strip())
    result = {
        "path": path_text,
        "exists": os.path.isdir(path_text),
        "deleted": 0,
        "failed": [],
    }
    if not result["exists"]:
        return result
    try:
        children = os.listdir(path_text)
    except Exception as exc:
        result["failed"].append({"target": path_text, "error": str(exc)})
        return result

    for child_name in children:
        child_path = os.path.join(path_text, child_name)
        try:
            if os.path.isdir(child_path) and not os.path.islink(child_path):
                shutil.rmtree(child_path)
            else:
                os.remove(child_path)
            result["deleted"] += 1
        except Exception as exc:
            result["failed"].append({"target": child_path, "error": str(exc)})
    return result


def _clear_jianying_frame_thumbnail_cache() -> dict:
    reports = []
    for path in _candidate_jianying_visual_cache_dirs():
        if os.path.basename(os.path.normpath(path)).lower() != "framethumbnail":
            continue
        reports.append(_clear_directory_children(path))
    deleted_entries = sum(int(item.get("deleted") or 0) for item in reports)
    failed_entries = sum(len(item.get("failed") or []) for item in reports)
    return {
        "ok": failed_entries == 0,
        "deleted_entries": deleted_entries,
        "failed_entries": failed_entries,
        "paths": reports,
    }


def _deep_clone_json_like(data):
    try:
        return json.loads(json.dumps(data, ensure_ascii=False))
    except Exception:
        return data


def _normalize_path_slashes(path_value: str) -> str:
    return str(path_value or "").replace("\\", "/")


def _iter_path_replacement_variants(path_value: str) -> list[str]:
    raw = str(path_value or "").strip()
    if not raw:
        return []
    variants: list[str] = []
    seen = set()
    for candidate in (
        raw,
        raw.replace("\\", "/"),
        raw.replace("/", "\\"),
        _normalize_path_slashes(raw),
    ):
        if candidate and candidate not in seen:
            seen.add(candidate)
            variants.append(candidate)
    return variants


def _replace_string_path_tokens(text: str, replacements: dict[str, str]) -> str:
    value = str(text or "")
    if not value or not isinstance(replacements, dict):
        return value
    ordered = sorted(
        ((str(old or ""), str(new or "")) for old, new in replacements.items() if str(old or "") and str(new or "")),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    for old_path, new_path in ordered:
        new_norm = _normalize_path_slashes(new_path)
        new_back = new_norm.replace("/", "\\")
        for old_variant in _iter_path_replacement_variants(old_path):
            if old_variant in value:
                replacement = new_back if "\\" in old_variant and "/" not in old_variant else new_norm
                value = value.replace(old_variant, replacement)
    return value


def _apply_recursive_string_replacements(node, replacements: dict[str, str]):
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if isinstance(value, str):
                node[key] = _replace_string_path_tokens(value, replacements)
            else:
                _apply_recursive_string_replacements(value, replacements)
    elif isinstance(node, list):
        for index, value in enumerate(list(node)):
            if isinstance(value, str):
                node[index] = _replace_string_path_tokens(value, replacements)
            else:
                _apply_recursive_string_replacements(value, replacements)


def _local_appdata_jianying_dir() -> Path:
    home = Path.home()
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
    return local_app_data / "JianyingPro" / "User Data"


def _template_draft_cache_root() -> Path:
    return _local_appdata_jianying_dir() / "Resources" / "templateDraft"


def _artist_effect_cache_root() -> Path:
    return _local_appdata_jianying_dir() / "Cache" / "artistEffect"


def _is_path_within_root(path_value: str, root_value: str) -> bool:
    try:
        path_norm = _normalize_abs_path(path_value)
        root_norm = _normalize_abs_path(root_value)
    except Exception:
        return False
    if not path_norm or not root_norm:
        return False
    return path_norm == root_norm or path_norm.startswith(root_norm + os.sep)


def _clone_tree_once(source_dir: str, target_dir: str) -> str:
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)
    os.makedirs(os.path.dirname(target_dir), exist_ok=True)
    shutil.copytree(source_dir, target_dir)
    return target_dir


def _clone_template_draft_cache_dir(source_dir: str) -> str:
    source = str(source_dir or "").strip()
    if not source or not os.path.isdir(source):
        return ""
    target_root = _template_draft_cache_root()
    target_root.mkdir(parents=True, exist_ok=True)
    target_dir = target_root / f"vf{uuid.uuid4().hex}"
    return _clone_tree_once(source, str(target_dir))


def _clone_artist_effect_dir(effect_dir: str) -> str:
    source = str(effect_dir or "").strip()
    if not source or not os.path.isdir(source):
        return ""
    source_path = Path(source)
    effect_group = source_path.parent.name
    target_root = _artist_effect_cache_root() / effect_group
    target_root.mkdir(parents=True, exist_ok=True)
    target_dir = target_root / f"vf{uuid.uuid4().hex}"
    return _clone_tree_once(str(source_path), str(target_dir))


def _resolve_nested_cache_semantic_path(cache_root: str, raw_value: str) -> str:
    raw = str(raw_value or "").strip()
    root = str(cache_root or "").strip()
    if not raw or not root:
        return raw
    if os.path.isabs(raw):
        return _normalize_path_slashes(raw)

    rel = raw.replace("\\", "/").lstrip("/")
    basename = os.path.basename(rel)
    lower_rel = rel.lower()
    candidates: list[str] = []

    def add_candidate(*parts: str) -> None:
        candidate = os.path.join(root, *parts)
        if candidate not in candidates:
            candidates.append(candidate)

    if lower_rel.startswith("materials/video/"):
        tail = rel.split("/", 2)[2] if rel.count("/") >= 2 else basename
        if basename:
            add_candidate("video", basename)
            add_candidate("video", "cover", basename)
        if tail:
            add_candidate("video", tail)
    elif lower_rel.startswith("materials/retouch_cover/"):
        tail = rel.split("/", 2)[2] if rel.count("/") >= 2 else basename
        if tail:
            add_candidate("retouch_cover", tail)
    elif lower_rel.startswith("materials/audio/"):
        tail = rel.split("/", 2)[2] if rel.count("/") >= 2 else basename
        if tail:
            add_candidate("audio", tail)
    elif lower_rel.startswith("materials/beat/"):
        tail = rel.split("/", 2)[2] if rel.count("/") >= 2 else basename
        if tail:
            add_candidate("beats", tail)
            add_candidate("beat", tail)
    elif lower_rel.startswith("video/") or lower_rel.startswith("image/") or lower_rel.startswith("audio/") or lower_rel.startswith("retouch_cover/") or lower_rel.startswith("beat/") or lower_rel.startswith("beats/"):
        add_candidate(*rel.split("/"))
    elif basename:
        add_candidate(basename)
        add_candidate("video", basename)
        add_candidate("video", "cover", basename)
        add_candidate("retouch_cover", basename)

    add_candidate(*rel.split("/"))

    for candidate in candidates:
        if os.path.exists(candidate):
            return _normalize_path_slashes(candidate)
    if candidates:
        return _normalize_path_slashes(candidates[0])
    return raw


def _canonicalize_nested_cache_semantic_paths(current_nested: dict, cache_root: str) -> int:
    changed = 0
    root = str(cache_root or "").strip()
    if not root or not os.path.isdir(root) or not isinstance(current_nested, dict):
        return changed

    current_nested["path"] = _normalize_path_slashes(root)

    def rewrite_string_field(obj: dict, key: str) -> None:
        nonlocal changed
        if not isinstance(obj, dict):
            return
        value = obj.get(key)
        if not isinstance(value, str) or not value.strip():
            return
        rewritten = _resolve_nested_cache_semantic_path(root, value)
        if rewritten != value:
            obj[key] = rewritten
            changed += 1

    rewrite_string_field(current_nested, "static_cover_image_path")
    static_cover_value = str(current_nested.get("static_cover_image_path") or "").strip()
    static_cover_base = os.path.basename(static_cover_value.replace("\\", "/"))
    if static_cover_base.lower().startswith("image_"):
        desired_static_cover = _normalize_path_slashes(os.path.join(root, "video", static_cover_base))
        if static_cover_value != desired_static_cover:
            current_nested["static_cover_image_path"] = desired_static_cover
            changed += 1

    retouch_cover = current_nested.get("retouch_cover")
    if isinstance(retouch_cover, dict):
        rewrite_string_field(retouch_cover, "retouch_path")
        rewrite_string_field(retouch_cover, "image_path")
        if str(retouch_cover.get("retouch_path") or "").strip():
            desired_keys = {"retouch_path", "frame_segment_id", "frame_timestamp", "image_crop", "report_extras"}
            for key in list(retouch_cover.keys()):
                if key not in desired_keys:
                    retouch_cover.pop(key, None)
                    changed += 1
            if retouch_cover.get("image_crop") not in ({}, None):
                retouch_cover["image_crop"] = {}
                changed += 1

    materials = current_nested.get("materials")
    if isinstance(materials, dict):
        for media_type in ("videos", "images", "audios"):
            for item in materials.get(media_type) or []:
                if not isinstance(item, dict):
                    continue
                rewrite_string_field(item, "path")
                rewrite_string_field(item, "file_path")
                rewrite_string_field(item, "material_path")

        mutable_materials = (current_nested.get("mutable_config") or {}).get("mutable_materials") or []
        for item in mutable_materials:
            if not isinstance(item, dict):
                continue
            rewrite_string_field(item, "cover_path")
            if item.get("is_user_modified") is not False:
                item["is_user_modified"] = False
                changed += 1

    return changed


def _iter_nested_draft_pairs(source_payload: dict, current_payload: dict):
    if not isinstance(source_payload, dict) or not isinstance(current_payload, dict):
        return
    source_materials = source_payload.get("materials") or {}
    current_materials = current_payload.get("materials") or {}
    source_drafts = source_materials.get("drafts") or []
    current_drafts = current_materials.get("drafts") or []
    for source_item, current_item in zip(source_drafts, current_drafts):
        if not isinstance(source_item, dict) or not isinstance(current_item, dict):
            continue
        source_nested = source_item.get("draft")
        current_nested = current_item.get("draft")
        if not isinstance(source_nested, dict) or not isinstance(current_nested, dict):
            continue
        yield source_item, source_nested, current_item, current_nested
        yield from _iter_nested_draft_pairs(source_nested, current_nested)


def _collect_material_items_by_id(payload: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    materials = payload.get("materials") or {}
    if not isinstance(materials, dict):
        return result
    for media_type in ("videos", "images", "audios"):
        for item in materials.get(media_type) or []:
            if not isinstance(item, dict):
                continue
            material_id = str(item.get("id") or "").strip()
            if material_id:
                result[material_id] = item
    return result


def _resolve_media_source_for_cache_copy(path_value: str, cloned_draft_path: str, old_root: str = "") -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    if raw.startswith("materials/beat/"):
        beat_tail = raw.split("/", 2)[2] if raw.count("/") >= 2 else ""
        if beat_tail:
            for rel in (os.path.join("beats", beat_tail), os.path.join("beat", beat_tail), raw.replace("/", os.sep)):
                candidate = os.path.join(cloned_draft_path, rel)
                if os.path.isfile(candidate):
                    return candidate
    if raw.startswith("materials/") or raw.startswith("video/") or raw.startswith("audio/") or raw.startswith("beat/") or raw.startswith("beats/"):
        candidate = os.path.join(cloned_draft_path, raw.replace("/", os.sep))
        if os.path.isfile(candidate):
            return candidate
    if old_root and os.path.isabs(raw):
        try:
            rel = os.path.relpath(raw, old_root)
        except ValueError:
            rel = ""
        if rel:
            candidate = os.path.join(old_root, rel)
            if os.path.isfile(candidate):
                return candidate
    return ""


def _refresh_artist_effect_content(effect_dir: str, replacement_values: list[str]) -> int:
    effect_root = str(effect_dir or "").strip()
    if not effect_root or not os.path.isdir(effect_root):
        return 0
    content_path = os.path.join(effect_root, "content.json")
    changed = 0
    texts = [str(v or "") for v in replacement_values if str(v or "").strip()]
    if not texts:
        return 0
    content_path = os.path.join(effect_root, "content.json")
    if os.path.isfile(content_path):
        try:
            payload = json.loads(Path(content_path).read_text(encoding="utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            text_index = 0

            def walk(node):
                nonlocal changed, text_index
                if isinstance(node, dict):
                    for key, value in list(node.items()):
                        if key == "richText" and isinstance(value, str) and text_index < len(texts):
                            replaced = re.sub(r">[^<>]*</font>", f">{texts[text_index]}</font>", value, count=1)
                            if replaced != value:
                                node[key] = replaced
                                changed += 1
                                text_index += 1
                        else:
                            walk(value)
                elif isinstance(node, list):
                    for item in node:
                        walk(item)

            walk(payload)
            if changed:
                Path(content_path).write_text(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )

    extra_path = os.path.join(effect_root, "extra.json")
    if os.path.isfile(extra_path):
        try:
            extra_payload = json.loads(Path(extra_path).read_text(encoding="utf-8"))
        except Exception:
            extra_payload = None
        if isinstance(extra_payload, dict):
            original_texts = extra_payload.get("texts")
            if isinstance(original_texts, list) and original_texts:
                new_values = list(original_texts)
                local_changed = 0
                for idx in range(min(len(new_values), len(texts))):
                    if str(new_values[idx] or "") != texts[idx]:
                        new_values[idx] = texts[idx]
                        local_changed += 1
                if local_changed:
                    extra_payload["texts"] = new_values
                    Path(extra_path).write_text(
                        json.dumps(extra_payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    changed += local_changed
    return changed


def _is_template_draft_cache_path(path_value: str) -> bool:
    raw = str(path_value or "").strip()
    if not raw or not os.path.isabs(raw):
        return False
    normalized = raw.replace("\\", "/").lower()
    return "/templateDraft/".lower() in normalized


def _payload_has_official_nested_cache_semantics(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    for current_payload in _iter_draft_payloads(payload):
        if current_payload is payload:
            continue
        nested_root = str(current_payload.get("path") or "").strip()
        if _is_template_draft_cache_path(nested_root):
            return True
    return False


def _externalize_nested_official_cache_semantics(
    current_payload: dict,
    source_payload: dict,
    cloned_draft_path: str,
    text_replacements: dict,
    *,
    template_root_cache: Optional[dict[str, str]] = None,
    artist_effect_cache: Optional[dict[str, str]] = None,
) -> dict:
    diagnostics = {
        "template_draft_clones": 0,
        "artist_effect_clones": 0,
        "material_paths_externalized": 0,
        "artist_effect_text_refreshes": 0,
        "canonicalized_nested_paths": 0,
        "template_draft_roots": [],
        "artist_effect_roots": [],
    }
    template_root_cache = template_root_cache if isinstance(template_root_cache, dict) else {}
    artist_effect_cache = artist_effect_cache if isinstance(artist_effect_cache, dict) else {}

    for source_item, source_nested, current_item, current_nested in _iter_nested_draft_pairs(source_payload, current_payload):
        old_template_root = str(source_nested.get("path") or "").strip()
        if not old_template_root or not os.path.isabs(old_template_root) or not os.path.isdir(old_template_root):
            continue
        path_replacements: dict[str, str] = {}
        if old_template_root not in template_root_cache:
            new_template_root = _clone_template_draft_cache_dir(old_template_root)
            if not new_template_root:
                continue
            template_root_cache[old_template_root] = new_template_root
            diagnostics["template_draft_clones"] += 1
            diagnostics["template_draft_roots"].append(_normalize_path_slashes(new_template_root))
        new_template_root = template_root_cache[old_template_root]
        path_replacements[old_template_root] = new_template_root
        current_nested["path"] = _normalize_path_slashes(new_template_root)
        if "draft_cover_path" in current_item or "draft_cover_path" in source_item:
            current_item["draft_cover_path"] = None

        source_items = _collect_material_items_by_id(source_nested)
        current_items = _collect_material_items_by_id(current_nested)
        for material_id, current_material in current_items.items():
            source_material = source_items.get(material_id)
            if not isinstance(source_material, dict):
                continue
            source_material_path = str(source_material.get("path") or source_material.get("file_path") or "").strip()
            if not source_material_path or not _is_path_within_root(source_material_path, old_template_root):
                continue
            rel_path = os.path.relpath(source_material_path, old_template_root)
            current_material_path = str(current_material.get("path") or current_material.get("file_path") or "").strip()
            copy_source = _resolve_media_source_for_cache_copy(current_material_path, cloned_draft_path, old_root=old_template_root) or source_material_path
            target_abs = os.path.join(new_template_root, rel_path)
            keep_source_name_shape = (
                source_material_path
                and "##_material_placeholder_" in os.path.basename(source_material_path)
                and os.path.splitext(source_material_path)[1].lower() in _IMAGE_EXTS
            )
            if (
                copy_source
                and not keep_source_name_shape
                and os.path.splitext(copy_source)[1].lower() != os.path.splitext(target_abs)[1].lower()
            ):
                target_abs = os.path.join(os.path.dirname(target_abs), os.path.basename(copy_source))
            written = _copy_into_cache_target(copy_source, target_abs)
            if not written:
                continue
            current_material["path"] = _normalize_path_slashes(written)
            if "file_path" in current_material:
                current_material["file_path"] = _normalize_path_slashes(written)
            diagnostics["material_paths_externalized"] += 1

        source_cover = str(source_nested.get("static_cover_image_path") or "").strip()
        current_cover = str(current_nested.get("static_cover_image_path") or "").strip()
        if source_cover and _is_path_within_root(source_cover, old_template_root):
            rel_cover = os.path.relpath(source_cover, old_template_root)
            cover_source = _resolve_media_source_for_cache_copy(current_cover, cloned_draft_path, old_root=old_template_root) or source_cover
            cover_target = os.path.join(new_template_root, rel_cover)
            written_cover = _copy_into_cache_target(cover_source, cover_target)
            if written_cover:
                current_nested["static_cover_image_path"] = _normalize_path_slashes(written_cover)

        nested_text_replacements: dict[str, str] = {}
        ordered_material_ids = _collect_text_material_ids_in_track_order(current_nested)
        for idx, material_id in enumerate(ordered_material_ids):
            if idx in text_replacements:
                nested_text_replacements[material_id] = str(text_replacements[idx] or "")

        source_text_templates = ((source_nested.get("materials") or {}).get("text_templates") or [])
        current_text_templates = ((current_nested.get("materials") or {}).get("text_templates") or [])
        for source_tt, current_tt in zip(source_text_templates, current_text_templates):
            if not isinstance(source_tt, dict) or not isinstance(current_tt, dict):
                continue
            old_tt_path = str(source_tt.get("path") or "").strip()
            old_tt_dir = old_tt_path if os.path.isdir(old_tt_path) else os.path.dirname(old_tt_path)
            if not old_tt_path or not os.path.isabs(old_tt_path) or not os.path.isdir(old_tt_dir):
                continue
            if old_tt_dir not in artist_effect_cache:
                new_tt_dir = _clone_artist_effect_dir(old_tt_dir)
                if not new_tt_dir:
                    continue
                artist_effect_cache[old_tt_dir] = new_tt_dir
                diagnostics["artist_effect_clones"] += 1
                diagnostics["artist_effect_roots"].append(_normalize_path_slashes(new_tt_dir))
            new_tt_dir = artist_effect_cache[old_tt_dir]
            path_replacements[old_tt_dir] = new_tt_dir
            current_tt["path"] = _normalize_path_slashes(new_tt_dir)
            material_id = str(current_tt.get("id") or "").strip()
            replacement_text = nested_text_replacements.get(material_id)
            if replacement_text:
                current_tt["name"] = replacement_text
                diagnostics["artist_effect_text_refreshes"] += _refresh_artist_effect_content(new_tt_dir, [replacement_text])

        if path_replacements:
            _apply_recursive_string_replacements(current_nested, path_replacements)
            _apply_recursive_string_replacements(current_item, path_replacements)

        diagnostics["canonicalized_nested_paths"] += _canonicalize_nested_cache_semantic_paths(
            current_nested,
            new_template_root,
        )

    return diagnostics


def _norm_abs(path_value: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path_value or "").strip())))


def _resolve_source_info_path_from_root_meta(template_path: str) -> tuple[str, dict]:
    normalized_template_path = normalize_draft_project_path(template_path) or template_path
    template_norm = _norm_abs(normalized_template_path)
    diagnostics = {
        "root_meta_path": "",
        "matched_by": "",
        "matched_draft_name": "",
        "source_info_path": "",
    }
    if not template_norm:
        return "", diagnostics

    for root_meta_path in _candidate_root_meta_paths():
        if not os.path.exists(root_meta_path):
            continue
        payload, err = load_json_file_with_encodings(root_meta_path)
        if err is not None or not isinstance(payload, dict):
            continue
        entries = payload.get("all_draft_store") or []
        if not isinstance(entries, list):
            continue

        matched = None
        for item in entries:
            if not isinstance(item, dict):
                continue
            fold_path = str(item.get("draft_fold_path") or "").strip()
            json_file = str(item.get("draft_json_file") or "").strip()
            if not fold_path or not json_file:
                continue
            try:
                fold_norm = _norm_abs(fold_path)
            except Exception:
                continue
            if fold_norm == template_norm:
                matched = (item, "draft_fold_path")
                break

        if matched is None:
            target_name = os.path.basename(template_norm.rstrip("\\/"))
            for item in entries:
                if not isinstance(item, dict):
                    continue
                json_file = str(item.get("draft_json_file") or "").strip()
                draft_name = str(item.get("draft_name") or "").strip()
                if not json_file:
                    continue
                if draft_name and draft_name == target_name:
                    matched = (item, "draft_name")
                    break

        if matched is None:
            continue

        item, matched_by = matched
        source_info_path = str(item.get("draft_json_file") or "").strip()
        if source_info_path:
            diagnostics["root_meta_path"] = root_meta_path
            diagnostics["matched_by"] = matched_by
            diagnostics["matched_draft_name"] = str(item.get("draft_name") or "").strip()
            diagnostics["source_info_path"] = source_info_path
            return source_info_path, diagnostics

    return "", diagnostics


def _resolve_cloned_info_path(cloned_draft_path: str, source_info_path: str, source_draft_root: str = "") -> str:
    raw_source = str(source_info_path or "").strip()
    raw_root = str(source_draft_root or "").strip()
    if raw_source and raw_root:
        try:
            source_norm = _norm_abs(raw_source)
            root_norm = _norm_abs(raw_root)
            rel_path = os.path.relpath(source_norm, root_norm)
            if rel_path and not rel_path.startswith(".."):
                candidate = os.path.join(cloned_draft_path, rel_path)
                if os.path.exists(candidate):
                    return candidate
        except Exception:
            pass

    source_basename = os.path.basename(raw_source)
    if source_basename:
        candidate = os.path.join(cloned_draft_path, source_basename)
        if os.path.exists(candidate):
            return candidate
    for fallback_name in ("draft_content.json", "template.json", "template.tmp"):
        candidate = os.path.join(cloned_draft_path, fallback_name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(cloned_draft_path, "draft_content.json")


def _load_timeline_ids(cloned_draft_path: str) -> list[str]:
    project_path = os.path.join(cloned_draft_path, "Timelines", "project.json")
    if not os.path.exists(project_path):
        return []

    try:
        with open(project_path, "r", encoding="utf-8") as handle:
            project = json.load(handle)
    except Exception:
        return []

    timeline_ids = []
    main_timeline_id = project.get("main_timeline_id")
    if isinstance(main_timeline_id, str) and main_timeline_id.strip():
        timeline_ids.append(main_timeline_id.strip())

    for item in project.get("timelines") or []:
        if not isinstance(item, dict):
            continue
        timeline_id = str(item.get("id") or "").strip()
        if timeline_id and timeline_id not in timeline_ids:
            timeline_ids.append(timeline_id)

    return timeline_ids


def _write_json_file(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _write_compact_json_file(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))


def _write_payload_file_preserving_container(path: str, data: dict) -> None:
    file_name = os.path.basename(str(path or "")).lower()
    if file_name in {"draft_content.json", "draft_content.json.bak", "template-2.tmp"}:
        official_codec.write_official_draft_payload(path, data)
        return
    _write_json_file(path, data)


def _looks_like_plain_json(path: str) -> bool:
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, "rb") as handle:
            head = handle.read(64)
    except Exception:
        return False
    if not head:
        return False
    text = head.decode("utf-8", errors="ignore").lstrip("\ufeff\x00\r\n\t ")
    return bool(text[:1] in "{[")


def _payload_activity_score(data: dict) -> tuple[int, int, int, int, int]:
    if not isinstance(data, dict):
        return (-1, -1, -1, -1, -1)

    tracks = data.get("tracks")
    track_count = len(tracks) if isinstance(tracks, list) else 0
    segment_count = 0
    if isinstance(tracks, list):
        for track in tracks:
            if isinstance(track, dict):
                segment_count += len(track.get("segments") or [])

    materials = data.get("materials") if isinstance(data.get("materials"), dict) else {}
    video_count = len(materials.get("videos") or [])
    image_count = len(materials.get("images") or [])
    audio_count = len(materials.get("audios") or [])
    text_count = len(materials.get("texts") or [])
    draft_count = len(materials.get("drafts") or [])
    replaceable = video_count + image_count + audio_count + text_count
    return (replaceable, segment_count, track_count, draft_count, 1 if data.get("path") is not None else 0)


def _classify_payload_shape(data: dict) -> str:
    if not isinstance(data, dict):
        return "unknown"
    tracks = data.get("tracks")
    track_count = len(tracks) if isinstance(tracks, list) else 0
    segment_count = 0
    if isinstance(tracks, list):
        for track in tracks:
            if isinstance(track, dict):
                segment_count += len(track.get("segments") or [])
    materials = data.get("materials") if isinstance(data.get("materials"), dict) else {}
    replaceable = (
        len(materials.get("videos") or [])
        + len(materials.get("images") or [])
        + len(materials.get("audios") or [])
        + len(materials.get("texts") or [])
    )
    has_shellish_config = isinstance(data.get("config"), dict) and "cover" in data
    if replaceable > 0 or segment_count > 0:
        return "active"
    if has_shellish_config and track_count == 0 and replaceable == 0:
        return "shell"
    return "unknown"


def _load_plain_json(path: str) -> tuple[Optional[dict], Optional[Exception]]:
    if not path or not os.path.exists(path) or not _looks_like_plain_json(path):
        return None, ValueError("not plain json")
    data, err = load_json_file_with_encodings(path)
    if err is not None or not isinstance(data, dict):
        return None, err or ValueError("invalid json payload")
    return data, None


def _iter_plain_payload_targets(cloned_draft_path: str) -> list[str]:
    names = ("template.json", "template.tmp")
    targets: list[str] = []
    for name in names:
        p = os.path.join(cloned_draft_path, name)
        if os.path.exists(p) and _looks_like_plain_json(p):
            targets.append(p)
    for timeline_id in _load_timeline_ids(cloned_draft_path):
        timeline_root = os.path.join(cloned_draft_path, "Timelines", timeline_id)
        for name in names:
            p = os.path.join(timeline_root, name)
            if os.path.exists(p) and _looks_like_plain_json(p):
                targets.append(p)
    deduped = []
    seen = set()
    for p in targets:
        n = os.path.normcase(os.path.normpath(p))
        if n in seen:
            continue
        seen.add(n)
        deduped.append(p)
    return deduped


def _iter_draft_content_targets(cloned_draft_path: str) -> list[str]:
    targets: list[str] = []
    root_candidate = os.path.join(cloned_draft_path, "draft_content.json")
    if os.path.exists(root_candidate):
        targets.append(root_candidate)
    for timeline_id in _load_timeline_ids(cloned_draft_path):
        candidate = os.path.join(cloned_draft_path, "Timelines", timeline_id, "draft_content.json")
        if os.path.exists(candidate):
            targets.append(candidate)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in targets:
        norm = os.path.normcase(os.path.normpath(item))
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(item)
    return deduped


def _load_active_payload_with_fallback(primary_path: str, cloned_draft_path: str) -> tuple[dict, dict]:
    primary_path = os.path.normpath(str(primary_path or "").strip()) if primary_path else ""
    cloned_draft_path = os.path.normpath(str(cloned_draft_path or "").strip()) if cloned_draft_path else ""
    diagnostics = {
        "requested_primary_path": primary_path,
        "read_path": "",
        "read_mode": "",
        "attempts": [],
    }

    if primary_path and os.path.exists(primary_path):
        if _looks_like_plain_json(primary_path):
            data, err = load_json_file_with_encodings(primary_path)
            diagnostics["attempts"].append({"path": primary_path, "mode": "plain", "ok": err is None and isinstance(data, dict)})
            if err is None and isinstance(data, dict):
                diagnostics["read_path"] = primary_path
                diagnostics["read_mode"] = "plain_primary"
                return data, diagnostics
        elif os.path.basename(primary_path).lower().startswith("draft_content"):
            try:
                data, decrypt_diag = _load_official_encrypted_draft_content(primary_path)
                diagnostics["attempts"].append({"path": primary_path, "mode": "encrypted", "ok": isinstance(data, dict)})
                if isinstance(data, dict):
                    diagnostics["read_path"] = primary_path
                    diagnostics["read_mode"] = "encrypted_primary"
                    diagnostics.update(decrypt_diag or {})
                    return data, diagnostics
            except Exception as exc:
                diagnostics["attempts"].append({"path": primary_path, "mode": "encrypted", "ok": False, "error": str(exc)})

    for target in _iter_plain_payload_targets(cloned_draft_path):
        data, err = _load_plain_json(target)
        if err is not None or not isinstance(data, dict):
            diagnostics["attempts"].append({"path": target, "mode": "plain_fallback", "ok": False, "error": str(err)})
            continue
        diagnostics["attempts"].append(
            {
                "path": target,
                "mode": "plain_fallback",
                "ok": True,
                "shape": _classify_payload_shape(data),
                "score": list(_payload_activity_score(data)),
            }
        )
        diagnostics["read_path"] = target
        diagnostics["read_mode"] = "plain_fallback_first_available"
        return data, diagnostics
    raise ValueError("draft content read failed: no usable payload source")


def _select_best_plain_shell_payload(cloned_draft_path: str) -> tuple[Optional[dict], str]:
    best_data = None
    best_path = ""
    best_score = (-1, -1, -1, -1, -1)
    for target in _iter_plain_payload_targets(cloned_draft_path):
        data, err = _load_plain_json(target)
        if err is not None or not isinstance(data, dict):
            continue
        if _classify_payload_shape(data) != "shell":
            continue
        score = _payload_activity_score(data)
        if score > best_score:
            best_score = score
            best_data = data
            best_path = target
    return best_data, best_path


def _choose_payload_for_existing_file(target_path: str, active_payload: dict, shell_payload: Optional[dict]) -> Optional[dict]:
    existing, err = _load_plain_json(target_path)
    if err is not None or not isinstance(existing, dict):
        return None
    shape = _classify_payload_shape(existing)
    if shape == "active":
        return active_payload
    if shape == "shell":
        return shell_payload if isinstance(shell_payload, dict) else existing
    file_name = os.path.basename(target_path).lower()
    if file_name == "template.tmp":
        return active_payload
    if file_name == "template.json":
        return shell_payload if isinstance(shell_payload, dict) else existing
    return None


def _write_plain_payload_targets(active_payload: dict, shell_payload: Optional[dict], cloned_draft_path: str) -> list[str]:
    written_paths: list[str] = []
    for target_path in _iter_plain_payload_targets(cloned_draft_path):
        payload = _choose_payload_for_existing_file(target_path, active_payload, shell_payload)
        if not isinstance(payload, dict):
            continue
        _write_json_file(target_path, payload)
        written_paths.append(target_path)
    return written_paths


def _merge_unique_paths(*path_lists: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for items in path_lists:
        for item in items or []:
            norm = os.path.normcase(os.path.normpath(str(item)))
            if not norm or norm in seen:
                continue
            seen.add(norm)
            merged.append(item)
    return merged


def _safe_material_folder_name(name: str, fallback: str) -> str:
    raw = str(name or "")
    raw = re.sub(r"[\r\n\t]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", raw).strip(" .")
    return cleaned or fallback


def _localize_material_replacements_for_draft(material_replacements: dict, cloned_draft_path: str) -> dict:
    if not isinstance(material_replacements, dict) or not material_replacements:
        return {}

    localized: dict[str, str] = {}
    copied_by_key_source: dict[tuple[str, str], str] = {}
    target_root = os.path.join(cloned_draft_path, "materialResources")
    os.makedirs(target_root, exist_ok=True)

    for key, source_path in material_replacements.items():
        source_text = str(source_path or "").strip()
        if not source_text:
            continue
        source_abs = os.path.abspath(source_text)
        if not os.path.isfile(source_abs):
            localized[key] = source_text
            continue

        source_norm = _normalize_abs_path(source_abs)
        folder_name = _safe_material_folder_name(
            os.path.splitext(str(key or "").strip())[0],
            "_vf_replacements",
        )
        copy_key = (str(key or "").strip().lower(), source_norm)
        if copy_key in copied_by_key_source:
            localized[key] = copied_by_key_source[copy_key]
            continue

        slot_root = os.path.join(target_root, folder_name)
        os.makedirs(slot_root, exist_ok=True)
        base_name = os.path.basename(source_abs) or f"{uuid.uuid4().hex}.bin"
        dst_path = os.path.join(slot_root, base_name)
        if os.path.exists(dst_path):
            stem, ext = os.path.splitext(base_name)
            dst_path = os.path.join(slot_root, f"{stem}_{uuid.uuid4().hex[:8]}{ext}")
        try:
            shutil.copy2(source_abs, dst_path)
            resolved = os.path.abspath(dst_path)
        except Exception:
            resolved = source_abs
        copied_by_key_source[copy_key] = resolved
        localized[key] = resolved

    return localized


def _write_by_info_path_with_main_timeline_mirror(read_path: str, data: dict, cloned_draft_path: str) -> list[str]:
    if not read_path:
        return []
    if os.path.basename(read_path).lower() == "draft_content.json":
        _write_compact_json_file(read_path, data)
    else:
        _write_payload_file_preserving_container(read_path, data)
    written = [read_path]

    file_name = os.path.basename(read_path)
    project_json_path = os.path.join(cloned_draft_path, "Timelines", "project.json")
    main_timeline_id = _load_main_timeline_id(project_json_path)
    if not main_timeline_id:
        return written
    mirror_path = os.path.join(cloned_draft_path, "Timelines", main_timeline_id, file_name)
    if os.path.normcase(os.path.normpath(mirror_path)) == os.path.normcase(os.path.normpath(read_path)):
        return written
    os.makedirs(os.path.dirname(mirror_path), exist_ok=True)
    if file_name.lower() == "draft_content.json":
        _write_compact_json_file(mirror_path, data)
    else:
        _write_payload_file_preserving_container(mirror_path, data)
    written.append(mirror_path)
    return written


def _write_draft_content_targets(data: dict, cloned_draft_path: str) -> list[str]:
    written: list[str] = []
    for target in _iter_draft_content_targets(cloned_draft_path):
        _write_payload_file_preserving_container(target, data)
        written.append(target)
    return written


def _iter_draft_payloads(draft_data: dict):
    if not isinstance(draft_data, dict):
        return

    stack = [draft_data]
    seen_ids: set[int] = set()
    while stack:
        current = stack.pop()
        if not isinstance(current, dict):
            continue
        marker = id(current)
        if marker in seen_ids:
            continue
        seen_ids.add(marker)
        yield current

        materials = current.get("materials")
        if not isinstance(materials, dict):
            continue
        nested_drafts = materials.get("drafts") or []
        if not isinstance(nested_drafts, list):
            continue
        for item in nested_drafts:
            if not isinstance(item, dict):
                continue
            nested = item.get("draft")
            if isinstance(nested, dict):
                stack.append(nested)


def _normalize_abs_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.normpath(text))


def _map_template_draft_absolute_to_materials(path_value: str) -> str:
    raw = str(path_value or "").strip()
    if not raw or not os.path.isabs(raw):
        return raw
    normalized = raw.replace("\\", "/")
    marker = "/templateDraft/"
    idx = normalized.lower().find(marker.lower())
    if idx < 0:
        return raw
    tail = normalized[idx + len(marker):]
    parts = [p for p in tail.split("/") if p]
    if len(parts) < 2:
        return raw
    # parts[0] is template draft hash folder
    rel_parts = parts[1:]
    if not rel_parts:
        return raw
    head = rel_parts[0].lower()
    if head == "materials":
        return "/".join(rel_parts)
    # Keep official template cache roots aligned with JianYing's original layout.
    # In practice, nested official drafts are more stable when video/audio/beat assets
    # remain under direct roots like video/* instead of being rewritten to materials/*.
    if head in {"video", "image", "audio", "retouch_cover", "beat"}:
        return "/".join(rel_parts)
    return raw


def _rebase_source_internal_path_value(path_value: str, source_root: str) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return raw
    if "://" in raw:
        return raw
    template_draft_mapped = _map_template_draft_absolute_to_materials(raw)
    if template_draft_mapped != raw:
        return template_draft_mapped
    if raw.startswith("materials/") or raw.startswith("materials\\"):
        return raw.replace("\\", "/")
    if not os.path.isabs(raw):
        return raw

    source_norm = _normalize_abs_path(source_root)
    value_norm = _normalize_abs_path(raw)
    if not source_norm or not value_norm:
        return raw
    if value_norm == source_norm:
        return ""
    if not value_norm.startswith(source_norm + os.sep):
        return raw

    rel = os.path.relpath(os.path.normpath(raw), os.path.normpath(source_root))
    if not rel or rel == ".":
        return ""
    return rel.replace("\\", "/")


def _rebase_source_internal_paths(payload: dict, source_root: str, cloned_draft_path: str) -> int:
    if not isinstance(payload, dict):
        return 0
    changed = 0
    source_norm = _normalize_abs_path(source_root)
    if not source_norm:
        return 0
    asset_copy_pairs: list[tuple[str, str]] = []

    def rebase_field(obj: dict, key: str) -> None:
        nonlocal changed
        if not isinstance(obj, dict):
            return
        value = obj.get(key)
        if not isinstance(value, str):
            return
        rebased = _rebase_source_internal_path_value(value, source_root)
        if rebased != value:
            obj[key] = rebased
            changed += 1
            rebased_rel = str(rebased or "").strip().replace("\\", "/")
            if os.path.isabs(str(value or "").strip()) and rebased_rel and not os.path.isabs(rebased_rel):
                asset_copy_pairs.append((str(value or "").strip(), str(rebased or "").strip().replace("\\", "/")))

    def rebase_nested_path_fields(node) -> None:
        if isinstance(node, dict):
            nested_payload_path = node.get("path")
            if (
                node is not payload
                and isinstance(nested_payload_path, str)
                and os.path.isabs(nested_payload_path)
                and os.path.isdir(nested_payload_path)
            ):
                return
            for key, value in list(node.items()):
                if isinstance(value, (dict, list)):
                    rebase_nested_path_fields(value)
                    continue
                if not isinstance(value, str):
                    continue
                if key == "path" or key in {"file_path", "material_path"} or key.endswith("_path"):
                    rebase_field(node, key)
        elif isinstance(node, list):
            for item in node:
                rebase_nested_path_fields(item)

    for current_payload in _iter_draft_payloads(payload):
        if not isinstance(current_payload, dict):
            continue

        payload_path = current_payload.get("path")
        nested_official_payload = (
            current_payload is not payload
            and isinstance(payload_path, str)
            and os.path.isabs(payload_path)
            and os.path.isdir(payload_path)
        )

        if nested_official_payload:
            # Official nested templateDraft payloads carry their own private root/path
            # semantics. Rewriting them into draft-relative paths breaks the unresolved
            # main-video binding chain when that slot is not being replaced.
            continue

        if isinstance(payload_path, str) and os.path.isabs(payload_path):
            payload_norm = _normalize_abs_path(payload_path)
            if payload_norm == source_norm:
                current_payload["path"] = str(cloned_draft_path).replace("\\", "/")
                changed += 1

        rebase_field(current_payload, "static_cover_image_path")

        retouch_cover = current_payload.get("retouch_cover")
        if isinstance(retouch_cover, dict):
            for key in ("retouch_path", "image_path"):
                rebase_field(retouch_cover, key)

        materials = current_payload.get("materials")
        if not isinstance(materials, dict):
            continue

        for media_type in ("videos", "images", "audios"):
            for item in materials.get(media_type) or []:
                if not isinstance(item, dict):
                    continue
                for key, value in list(item.items()):
                    if not isinstance(value, str):
                        continue
                    if key in {"path", "file_path", "material_path"} or key.endswith("_path"):
                        rebased = _rebase_source_internal_path_value(value, source_root)
                        if rebased != value:
                            item[key] = rebased
                            changed += 1
                            rebased_rel = str(rebased or "").strip().replace("\\", "/")
                            if os.path.isabs(str(value or "").strip()) and rebased_rel and not os.path.isabs(rebased_rel):
                                asset_copy_pairs.append((str(value or "").strip(), str(rebased or "").strip().replace("\\", "/")))

        for draft_item in materials.get("drafts") or []:
            if not isinstance(draft_item, dict):
                continue
            for key, value in list(draft_item.items()):
                if not isinstance(value, str):
                    continue
                if key in {"draft_cover_path", "draft_file_path", "draft_config_path"} or key.endswith("_path"):
                    rebased = _rebase_source_internal_path_value(value, source_root)
                    if rebased != value:
                        draft_item[key] = rebased
                        changed += 1
                        rebased_rel = str(rebased or "").strip().replace("\\", "/")
                        if os.path.isabs(str(value or "").strip()) and rebased_rel and not os.path.isabs(rebased_rel):
                            asset_copy_pairs.append((str(value or "").strip(), str(rebased or "").strip().replace("\\", "/")))

        rebase_nested_path_fields(current_payload)

    # Ensure rebased materials/* paths are physically present in cloned draft.
    dedup: set[tuple[str, str]] = set()
    for src_abs, rel_dst in asset_copy_pairs:
        key = (_normalize_abs_path(src_abs), rel_dst.lower())
        if key in dedup:
            continue
        dedup.add(key)
        if not os.path.isfile(src_abs):
            continue
        dst_abs = os.path.join(cloned_draft_path, rel_dst.replace("/", os.sep))
        try:
            os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
            shutil.copy2(src_abs, dst_abs)
        except Exception:
            # Keep replacement flow resilient even if optional cache assets cannot be copied.
            continue

    return changed


def _candidate_jianying_cache_music_roots() -> list[str]:
    roots: list[str] = []
    local_appdata = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local_appdata:
        roots.append(os.path.join(local_appdata, "JianyingPro", "User Data", "Cache", "music"))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in roots:
        norm = _normalize_abs_path(item)
        if not norm or norm in seen or not os.path.isdir(item):
            continue
        seen.add(norm)
        deduped.append(item)
    return deduped


def _hydrate_missing_materials_from_payload_roots(payload: dict, cloned_draft_path: str, source_root: str = "") -> int:
    copied = 0
    seen_pairs: set[tuple[str, str]] = set()
    source_root_text = str(source_root or "").strip()
    source_root_dirs: list[str] = []
    if source_root_text and os.path.isdir(source_root_text):
        source_root_dirs.append(source_root_text)
    cache_music_roots = _candidate_jianying_cache_music_roots()

    def try_copy_from_payload_root(payload_root: str, rel_path: str) -> None:
        nonlocal copied
        if not payload_root or not rel_path:
            return
        rel_norm = rel_path.replace("\\", "/")
        dst_abs = os.path.join(cloned_draft_path, rel_norm.replace("/", os.sep))
        if os.path.isfile(dst_abs):
            return

        lower_rel = rel_norm.lower()
        tail = rel_norm
        if tail.lower().startswith("materials/"):
            tail = tail.split("/", 1)[1] if "/" in tail else ""

        candidates = []
        for base_root in [payload_root, *source_root_dirs]:
            if not base_root:
                continue
            candidates.append(os.path.join(base_root, rel_norm.replace("/", os.sep)))
            if tail:
                candidates.append(os.path.join(base_root, tail.replace("/", os.sep)))
            if lower_rel.startswith("materials/beat/"):
                beat_tail = rel_norm.split("/", 2)[2].replace("/", os.sep) if rel_norm.count("/") >= 2 else ""
                if beat_tail:
                    candidates.append(os.path.join(base_root, "beats", beat_tail))
                    candidates.append(os.path.join(base_root, "beat", beat_tail))
            elif lower_rel.startswith("beat/"):
                beat_tail = rel_norm.split("/", 1)[1].replace("/", os.sep) if "/" in rel_norm else ""
                if beat_tail:
                    candidates.append(os.path.join(base_root, "beats", beat_tail))
            elif lower_rel.startswith("beats/"):
                beat_tail = rel_norm.split("/", 1)[1].replace("/", os.sep) if "/" in rel_norm else ""
                if beat_tail:
                    candidates.append(os.path.join(base_root, "beat", beat_tail))

        if lower_rel.startswith("materials/audio/"):
            file_name = os.path.basename(rel_norm)
            for cache_root in cache_music_roots:
                candidates.append(os.path.join(cache_root, file_name))

        for src_abs in candidates:
            if not src_abs or not os.path.isfile(src_abs):
                continue
            pair_key = (_normalize_abs_path(src_abs), _normalize_abs_path(dst_abs))
            if pair_key in seen_pairs:
                return
            seen_pairs.add(pair_key)
            try:
                os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
                shutil.copy2(src_abs, dst_abs)
                copied += 1
            except Exception:
                pass
            return

    def _iter_relative_path_values(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    yield from _iter_relative_path_values(value)
                    continue
                if not isinstance(value, str):
                    continue
                text = value.strip()
                if not text or os.path.isabs(text) or "://" in text:
                    continue
                if key == "path" or key in {"file_path", "material_path", "beats_path", "audio_file_path"} or key.endswith("_path"):
                    yield text
        elif isinstance(node, list):
            for item in node:
                yield from _iter_relative_path_values(item)

    for current_payload in _iter_draft_payloads(payload):
        if not isinstance(current_payload, dict):
            continue
        payload_root = str(current_payload.get("path") or "").strip()
        candidate_roots = []
        if payload_root and os.path.isabs(payload_root) and os.path.isdir(payload_root):
            candidate_roots.append(payload_root)
        candidate_roots.extend(source_root_dirs)
        if not candidate_roots:
            continue

        static_cover = str(current_payload.get("static_cover_image_path") or "").strip()
        if static_cover and not os.path.isabs(static_cover):
            for root_candidate in candidate_roots:
                try_copy_from_payload_root(root_candidate, static_cover)

        retouch_cover = current_payload.get("retouch_cover")
        if isinstance(retouch_cover, dict):
            for key in ("retouch_path", "image_path"):
                value = str(retouch_cover.get(key) or "").strip()
                if value and not os.path.isabs(value):
                    for root_candidate in candidate_roots:
                        try_copy_from_payload_root(root_candidate, value)

        materials = current_payload.get("materials")
        if not isinstance(materials, dict):
            continue
        for media_type in ("videos", "images", "audios"):
            for item in materials.get(media_type) or []:
                if not isinstance(item, dict):
                    continue
                for key in ("path", "file_path", "material_path"):
                    value = str(item.get(key) or "").strip()
                    if value and not os.path.isabs(value):
                        for root_candidate in candidate_roots:
                            try_copy_from_payload_root(root_candidate, value)
        for item in materials.get("beats") or []:
            if not isinstance(item, dict):
                continue
            for value in _iter_relative_path_values(item):
                for root_candidate in candidate_roots:
                    try_copy_from_payload_root(root_candidate, value)
    return copied


def _sanitize_missing_cover_paths(payload: dict, cloned_draft_path: str) -> int:
    fixed = 0

    def _path_exists(path_value: str) -> bool:
        text = str(path_value or "").strip()
        if not text:
            return False
        if os.path.isabs(text):
            return os.path.exists(text)
        candidate = os.path.join(cloned_draft_path, text.replace("/", os.sep).replace("\\", os.sep))
        return os.path.exists(candidate)

    for current_payload in _iter_draft_payloads(payload):
        if not isinstance(current_payload, dict):
            continue
        nested_root = str(current_payload.get("path") or "").strip()
        if nested_root and os.path.isabs(nested_root) and os.path.isdir(nested_root):
            # Official nested templateDraft payloads keep their own root-relative cover semantics.
            continue
        static_cover = current_payload.get("static_cover_image_path")
        if isinstance(static_cover, str) and static_cover.strip() and not _path_exists(static_cover):
            current_payload["static_cover_image_path"] = ""
            fixed += 1

        retouch_cover = current_payload.get("retouch_cover")
        if isinstance(retouch_cover, dict):
            for key in ("retouch_path", "image_path"):
                value = retouch_cover.get(key)
                if isinstance(value, str) and value.strip() and not _path_exists(value):
                    retouch_cover[key] = ""
                    fixed += 1
    return fixed


def _is_locked_track(track: dict) -> bool:
    if not isinstance(track, dict):
        return False
    try:
        attr = int(track.get("attribute") or 0)
    except Exception:
        return False
    return ((attr - (attr % 4)) // 4) % 2 == 1


def _material_name_is_excluded(material_item: dict) -> bool:
    if not isinstance(material_item, dict):
        return False
    name = str(material_item.get("material_name") or "").strip()
    if not name:
        path_value = str(material_item.get("path") or material_item.get("file_path") or "").strip()
        name = os.path.basename(path_value)
    lowered = name.lower()
    return (
        lowered.startswith("_")
        or lowered.startswith("ignoreme")
        or lowered.startswith("复合片段")
        or lowered.startswith("compound clip")
    )


def _is_combination_segment(segment: dict, payload: dict) -> bool:
    if not isinstance(segment, dict) or not isinstance(payload, dict):
        return False
    materials = payload.get("materials") or {}
    if not isinstance(materials, dict):
        return False
    draft_items = materials.get("drafts") or []
    if not isinstance(draft_items, list) or not draft_items:
        return False
    draft_ids = set()
    for item in draft_items:
        if not isinstance(item, dict):
            continue
        draft_id = str(item.get("id") or "").strip()
        if draft_id:
            draft_ids.add(draft_id)
    if not draft_ids:
        return False
    for ref in segment.get("extra_material_refs") or []:
        if str(ref or "").strip() in draft_ids:
            return True
    return False


def _collect_referenced_material_ids(payload: dict, track_type: str) -> set[str]:
    ids: set[str] = set()
    tracks = payload.get("tracks") or []
    if not isinstance(tracks, list):
        return ids
    for track in tracks:
        if not isinstance(track, dict):
            continue
        if str(track.get("type") or "").strip().lower() != track_type:
            continue
        if _is_locked_track(track):
            continue
        for segment in track.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            if track_type == "video" and _is_combination_segment(segment, payload):
                continue
            material_id = str(segment.get("material_id") or "").strip()
            if material_id:
                ids.add(material_id)
    return ids


def _collect_text_material_ids_in_track_order(payload: dict) -> list[str]:
    ordered: list[str] = []
    tracks = payload.get("tracks") or []
    if not isinstance(tracks, list):
        return ordered
    for track in tracks:
        if not isinstance(track, dict):
            continue
        if str(track.get("type") or "").strip().lower() != "text":
            continue
        if _is_locked_track(track):
            continue
        for segment in track.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            material_id = str(segment.get("material_id") or "").strip()
            if material_id:
                ordered.append(material_id)
    return ordered


def _extract_text_content(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    content = item.get("content")
    if not isinstance(content, str):
        return ""
    try:
        parsed = json.loads(content)
    except Exception:
        parsed = None
    if isinstance(parsed, dict) and "text" in parsed:
        return str(parsed.get("text") or "")
    return str(item.get("recognize_text") or "")


def _write_text_content(item: dict, new_text: str) -> None:
    content = item.get("content")
    updated = False
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and "text" in parsed:
            parsed["text"] = new_text
            styles = parsed.get("styles")
            if isinstance(styles, list) and styles and isinstance(styles[0], dict):
                if isinstance(styles[0].get("range"), list) and len(styles[0]["range"]) == 2:
                    styles[0]["range"] = [0, len(new_text)]
            item["content"] = json.dumps(parsed, ensure_ascii=False)
            updated = True
    if not updated:
        item["content"] = new_text
    if "recognize_text" in item:
        item["recognize_text"] = new_text


def _get_private_reader_runtime_mode() -> str:
    raw = str(os.environ.get(_OFFICIAL_READER_RUNTIME_MODE_ENV) or "").strip().lower()
    if raw in {"legacy_0330", "legacy-0330", "0330", "legacy"}:
        return "legacy_0330"
    return "current"


def _allow_legacy_gg_reader_fallback() -> bool:
    raw = str(os.environ.get(_OFFICIAL_READER_ALLOW_GG_FALLBACK_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _candidate_gg_roots(runtime_mode: Optional[str] = None) -> list[str]:
    mode = runtime_mode or _get_private_reader_runtime_mode()
    candidates = []

    bundled_root = app_resource_path("runtime_tools", _OFFICIAL_READER_RUNTIME_DIRNAME)
    env_root = str(os.environ.get("GG_JY_ASSISTANT_ROOT") or "").strip()
    external_roots = [
        r"D:\gg-jy-assistant",
        r"E:\gg-jy-assistant",
    ]
    if mode == "legacy_0330":
        if env_root:
            candidates.append(env_root)
        candidates.extend(external_roots)
        if bundled_root.exists():
            candidates.append(str(bundled_root))
    else:
        if bundled_root.exists():
            candidates.append(str(bundled_root))
        if env_root:
            candidates.append(env_root)
        # External GG installs are dev/debug fallbacks only. Packaged builds should
        # always resolve the bundled official_reader runtime above first.
        candidates.extend(external_roots)

    deduped = []
    seen = set()
    for item in candidates:
        norm = os.path.normpath(str(item or "").strip())
        if not norm or norm in seen:
            continue
        seen.add(norm)
        deduped.append(norm)
    return deduped


def _resolve_reader_utils_path(root: str) -> str:
    packaged_semantic = os.path.join(root, "resources", "app.asar", "build", "electron", "utils")
    if os.path.exists(os.path.join(root, "resources", "app.asar")):
        return packaged_semantic

    unpacked_semantic = os.path.join(root, "resources", "app.asar.unpacked", "build", "electron", "utils")
    if os.path.isdir(unpacked_semantic):
        return unpacked_semantic

    source_utils = os.path.join(root, "resources", "app_source", "build", "electron", "utils")
    if os.path.isdir(source_utils):
        return source_utils

    return packaged_semantic


def _candidate_reader_config_paths(root: str, runtime_mode: Optional[str] = None) -> list[Path]:
    mode = runtime_mode or _get_private_reader_runtime_mode()
    home = Path.home()
    roaming_config = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / _GG_ASSISTANT_SOFTWARE_KEY / "config.json"
    bundled_candidates = [
        Path(root) / "userdata" / _GG_ASSISTANT_SOFTWARE_KEY / "config.json",
        Path(root) / "user_data" / "config.json",
        Path(root) / "config.json",
    ]
    if mode == "legacy_0330":
        candidates = [roaming_config, *bundled_candidates]
    else:
        candidates = [*bundled_candidates, roaming_config]
    deduped: list[Path] = []
    seen = set()
    for item in candidates:
        norm = str(item).strip().lower()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        deduped.append(item)
    return deduped


def _compute_gg_timeline_root_dirname(k6: str) -> str:
    k6_text = str(k6 or "")
    if len(k6_text) < 10:
        return "Timelines"
    try:
        mid = chr(int(k6_text[9:15]) + 9)
        tail = chr(114 + (int(k6_text[1]) % 2))
    except Exception:
        return "Timelines"

    # Mirrors gg-jy-assistant p._____ obfuscated dirname synthesis.
    return (
        ("true"[0].upper())
        + "i"
        + mid
        + "undefined"[3]
        + "l"
        + "i"
        + "undefined"[1]
        + "true"[3]
        + tail
    )


def _load_main_timeline_id(project_json_path: str) -> str:
    if not project_json_path or not os.path.exists(project_json_path):
        return ""
    try:
        with open(project_json_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return ""
    return str((data or {}).get("main_timeline_id") or "").strip()


def _reconcile_timeline_project_files(cloned_draft_path: str) -> dict:
    diagnostics = {
        "project_json_rewritten_from_bak": False,
        "project_json_main_timeline_id": "",
        "project_json_bak_main_timeline_id": "",
        "timeline_layout_rewritten": False,
    }
    if not cloned_draft_path or not os.path.isdir(cloned_draft_path):
        return diagnostics

    project_json_path = os.path.join(cloned_draft_path, "Timelines", "project.json")
    project_json_bak_path = os.path.join(cloned_draft_path, "Timelines", "project.json.bak")
    if not (os.path.isfile(project_json_path) and os.path.isfile(project_json_bak_path)):
        return diagnostics

    try:
        project = json.loads(Path(project_json_path).read_text(encoding="utf-8"))
        project_bak = json.loads(Path(project_json_bak_path).read_text(encoding="utf-8"))
    except Exception:
        return diagnostics
    if not (isinstance(project, dict) and isinstance(project_bak, dict)):
        return diagnostics

    main_timeline_id = str(project.get("main_timeline_id") or "").strip()
    bak_main_timeline_id = str(project_bak.get("main_timeline_id") or "").strip()
    diagnostics["project_json_main_timeline_id"] = main_timeline_id
    diagnostics["project_json_bak_main_timeline_id"] = bak_main_timeline_id
    if not bak_main_timeline_id or bak_main_timeline_id == main_timeline_id:
        return diagnostics

    bak_timeline_dir = os.path.join(cloned_draft_path, "Timelines", bak_main_timeline_id)
    if not os.path.isdir(bak_timeline_dir):
        return diagnostics

    _write_json_file(project_json_path, project_bak)
    diagnostics["project_json_rewritten_from_bak"] = True
    diagnostics["project_json_main_timeline_id"] = bak_main_timeline_id
    timeline_layout_path = os.path.join(cloned_draft_path, "timeline_layout.json")
    if os.path.isfile(timeline_layout_path):
        try:
            timeline_layout = json.loads(Path(timeline_layout_path).read_text(encoding="utf-8"))
        except Exception:
            timeline_layout = None
        if isinstance(timeline_layout, dict):
            changed = False
            dock_items = timeline_layout.get("dockItems") or []
            if isinstance(dock_items, list):
                for dock_item in dock_items:
                    if not isinstance(dock_item, dict):
                        continue
                    timeline_ids = dock_item.get("timelineIds")
                    if isinstance(timeline_ids, list) and timeline_ids:
                        if any(str(item or "").strip() != bak_main_timeline_id for item in timeline_ids):
                            dock_item["timelineIds"] = [bak_main_timeline_id]
                            changed = True
            if changed:
                _write_json_file(timeline_layout_path, timeline_layout)
                diagnostics["timeline_layout_rewritten"] = True
    return diagnostics


def _compute_totalmem_parity_digits() -> tuple[str, str]:
    total_mem = 0
    try:
        if os.name == "nt":
            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                total_mem = int(status.ullTotalPhys)
        else:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            phys_pages = int(os.sysconf("SC_PHYS_PAGES"))
            total_mem = page_size * phys_pages
    except Exception:
        total_mem = 0

    even_count = 0
    odd_count = 0
    for char in str(total_mem or ""):
        if not char.isdigit():
            continue
        if int(char) % 2 == 0:
            even_count += 1
        else:
            odd_count += 1
    return str(even_count % 10), str(odd_count % 10)


def _refresh_private_reader_g6_token(raw_g6: str) -> str:
    text = "".join(ch for ch in str(raw_g6 or "").strip() if ch.isdigit())
    if len(text) < 26:
        return str(raw_g6 or "").strip()

    chars = list(text[:26])
    chars[0:10] = list(f"{int(time.time()):010d}"[-10:])
    parity_even, parity_odd = _compute_totalmem_parity_digits()
    chars[16] = parity_even
    chars[17] = parity_odd
    return "".join(chars)


def _summarize_private_reader_runtime(runtime: dict) -> dict:
    if not isinstance(runtime, dict):
        return {}
    return {
        "runtime_mode": str(runtime.get("runtime_mode") or "").strip(),
        "root": str(runtime.get("root") or "").replace("\\", "/"),
        "config_path": str(runtime.get("config_path") or "").replace("\\", "/"),
        "user_data_path": str(runtime.get("user_data_path") or "").replace("\\", "/"),
        "utils_path": str(runtime.get("utils_path") or "").replace("\\", "/"),
        "cppreader_path": str(runtime.get("cppreader_path") or "").replace("\\", "/"),
        "k6": str(runtime.get("k6") or "").strip(),
        "g6_prefix": str(runtime.get("g6_value") or "").strip()[:10],
        "g6_token_length": len(str(runtime.get("g6_token") or "").strip()),
        "timeline_root_name": _compute_gg_timeline_root_dirname(str(runtime.get("k6") or "").strip()),
    }


def _resolve_private_reader_runtime(runtime_mode: Optional[str] = None) -> dict:
    mode = runtime_mode or _get_private_reader_runtime_mode()
    selection_report = {
        "runtime_mode": mode,
        "roots": [],
    }
    for root in _candidate_gg_roots(mode):
        cppreader_path = os.path.join(root, "resources", "enhance", "win32", "x64", "cppreader.exe")
        utils_path = _resolve_reader_utils_path(root)
        has_reader_context = (
            os.path.exists(os.path.join(root, "resources", "app.asar"))
            or os.path.exists(os.path.join(root, "resources", "app.asar.unpacked"))
            or os.path.isdir(utils_path)
        )
        root_report = {
            "root": str(root).replace("\\", "/"),
            "cppreader_exists": os.path.exists(cppreader_path),
            "utils_path": str(utils_path).replace("\\", "/"),
            "has_reader_context": has_reader_context,
            "config_attempts": [],
        }
        selection_report["roots"].append(root_report)
        if not (os.path.exists(cppreader_path) and has_reader_context):
            continue

        for config_path in _candidate_reader_config_paths(root, mode):
            config_report = {
                "config_path": str(config_path).replace("\\", "/"),
                "exists": config_path.exists(),
            }
            root_report["config_attempts"].append(config_report)
            if not config_path.exists():
                continue
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                config_report["parse_ok"] = False
                continue
            if not isinstance(config, dict):
                config_report["parse_ok"] = False
                continue
            config_report["parse_ok"] = True

            g6 = _refresh_private_reader_g6_token(str(config.get("g6") or "").strip())
            k6 = str(config.get("k6") or "").strip()
            k6p_raw = str(config.get("k6p") or "").strip()
            config_report["k6"] = k6
            config_report["g6_prefix"] = g6[:10]
            if len(g6) < 11 or not k6 or not k6p_raw:
                config_report["usable"] = False
                continue
            try:
                api_param = json.loads(json.dumps(k6p_raw))
                api_param = __import__("base64").b64decode(api_param).decode("utf-8")
            except Exception:
                config_report["usable"] = False
                continue
            if len(api_param) < 20:
                config_report["usable"] = False
                continue
            config_report["usable"] = True

            user_data_path = str(config_path.parent).replace("\\", "/")
            if os.path.basename(user_data_path).lower() == "user_data":
                bundled_userdata = Path(root) / "userdata" / _GG_ASSISTANT_SOFTWARE_KEY
                if bundled_userdata.is_dir():
                    user_data_path = str(bundled_userdata).replace("\\", "/")
            runtime = {
                "runtime_mode": mode,
                "root": root,
                "cppreader_path": cppreader_path,
                "utils_path": utils_path,
                "g6_token": g6[10:],
                "g6_value": g6,
                "k6": k6,
                "api_param": api_param,
                "user_data_path": user_data_path,
                "config_path": str(config_path),
                "selection_report": selection_report,
            }
            selection_report["selected"] = _summarize_private_reader_runtime(runtime)
            return runtime

    raise ValueError("private gg reader runtime not found")


def _path_has_non_ascii(value: str) -> bool:
    text = str(value or "")
    try:
        text.encode("ascii")
        return False
    except Exception:
        return True


def _build_ascii_reader_shadow_root(source_root: str) -> str:
    base_dir = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "VideoFactoryDesktop" / "official_reader_shadow"
    digest = hashlib.sha1(os.path.abspath(str(source_root or "")).encode("utf-8", errors="ignore")).hexdigest()[:12]
    shadow_root = base_dir / f"src_{digest}"
    if shadow_root.exists():
        shutil.rmtree(shadow_root, ignore_errors=True)
    shadow_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, shadow_root)
    return str(shadow_root)


def _run_private_pjs_reader_to_payload(draft_content_path: str, runtime: dict) -> tuple[dict, dict]:
    read_script = r"""
const fs = require("fs");
const path = require("path");
const Module = require("module");
const os = require("os");

const utilsPath = process.argv[1];
const configPath = process.argv[2];
const userDataPath = process.argv[3];
const cppreaderSource = process.argv[4];
const infoPath = process.argv[5];
const freshG6 = process.argv[6];

function buildStoreKeyMap() {
  return {
    TRIAL_TIME_LEFT: "t",
    LATEST_INTERNET_TIMESTAMP_S: "lits",
    LATEST_INTERNET_TIMESTAMP_S_CHECK_FAIL_COUNT: "litscfc",
    NOT_SHOW_NOTICE_INFO_AGAIN_WORDS: "nsniaw",
    OFFLINE_ACTIVATION: "oa",
    DISABLED: "d",
    CONTACT: "c",
    FIRST_PROJECT_CLICK_DEVIATION: "fpcd",
    FIRST_PROJECT_CLICK_ABS: "fpca",
    PROJECT_INIT_CLICK_FOCUS: "picf",
    OPENPATH_JY: "oj",
    JY_PATH: "jyp",
    BATCH_REPLACE_CLICK_EXPORT_WINDOW: "brcew",
    IS_3_EXIT_WINDOW: "i3ew",
    PRESET_OPTIONS: "po",
    DISABLE_GPU: "dg",
    THNTEN: "thnten",
    REPLACEMENT_PATH: "rp",
    LET_ME_CREATE_REPLACEMENT: "lmcr",
    MATCHERDATA_PATH: "mdp",
    PROFESSIONALDATA_PATH: "pdp",
    K6: "k6",
    K6_TRIAL_USING_PRODUCT_CODE: "k6p",
    G6: "g6",
    BIG_MODEL_MEDIUM: "bmm",
    BIG_MODEL_SOURCE: "bms",
    BIG_MODEL_URL: "bmu",
    BIG_MODEL_NAME: "bmn",
    BIG_MODEL_API_KEY: "bmak",
  };
}

class SimpleStore {
  constructor() {
    this.data = JSON.parse(fs.readFileSync(configPath, "utf8"));
    if (freshG6) {
      this.data.g6 = freshG6;
    }
    this.data.lits = Math.floor(Date.now() / 1000);
    this.data.litscfc = 0;
    this.data.oa = true;
    this.data.d = false;
  }
  get(key) {
    return this.data[key];
  }
  set(key, value) {
    this.data[key] = value;
  }
}

function installStubs() {
  const storeKeys = buildStoreKeyMap();
  const originalLoad = Module._load;
  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "electron") {
      return {
        app: {
          isPackaged: true,
          getPath(name) {
            if (name === "userData") {
              return userDataPath;
            }
            return "";
          },
          getVersion() {
            return "2.4.3";
          },
          getName() {
            return "gg-jy-assistant";
          },
          focus() {},
        },
        screen: {
          getPrimaryDisplay() {
            return { size: { width: 1920, height: 1080 } };
          },
        },
        dialog: {},
      };
    }
    if (request === "./const" && parent && /utils\\p\.js$/i.test(parent.filename)) {
      return {
        IS_EN: false,
        STORE_KEY: storeKeys,
        SOFTWARE_KEYNAME: "gg-jy-assistant",
      };
    }
    if (
      request === "../methods/activation" ||
      request === "../activation" ||
      request === "../../methods/activation"
    ) {
      return {
        getApiParamK() {
          return "12548043886245103004";
        },
        handleGetActivationStatus() {
          return { status: "official", tier: "vip", isForever: true, gt: 1893456000 };
        },
        getMacAddrPure() {
          return "00-00-00-00-00-00";
        },
      };
    }
    if (request === "ffmpeg-static") {
      return "C:/Windows/System32/where.exe";
    }
    if (request === "semver") {
      return {
        gte() {
          return true;
        },
      };
    }
    if (request === "electron-store") {
      return SimpleStore;
    }
    if (request === "json-bigint") {
      return { parse: JSON.parse, stringify: JSON.stringify };
    }
    if (request === "../../robot" || request === "../robot" || request === "./robot") {
      return {
        robot: {
          keyTap() {},
        },
        rbClick() {},
      };
    }
    if (request === "chokidar") {
      return {
        watch() {
          return { on() { return this; }, close() {} };
        },
      };
    }
    return originalLoad.apply(this, arguments);
  };
}

function ensureCppreaderMirror() {
  const mirrorPath = path.join(utilsPath, "enhance", "win32", "x64", "cppreader.exe");
  fs.mkdirSync(path.dirname(mirrorPath), { recursive: true });
  if (!fs.existsSync(mirrorPath) && fs.existsSync(cppreaderSource)) {
    fs.copyFileSync(cppreaderSource, mirrorPath);
  }
}

async function main() {
  installStubs();
  ensureCppreaderMirror();
  const pmod = require(path.join(utilsPath, "p.js"));
  const readResult = await pmod.p({ infoPath });
  if (!readResult || readResult.status !== "success") {
    process.stderr.write(JSON.stringify(readResult || { status: "error", data: "empty result" }));
    process.exit(3);
  }
  process.stdout.write(readResult.data || "");
}

main().catch((error) => {
  process.stderr.write(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            read_script,
            runtime["utils_path"],
            runtime["config_path"],
            runtime["user_data_path"],
            runtime["cppreader_path"],
            draft_content_path,
            runtime.get("g6_value") or "",
        ],
        capture_output=True,
        check=False,
        **_quiet_subprocess_kwargs(),
    )
    stdout_text = (result.stdout or b"").decode("utf-8", errors="ignore").strip()
    stderr_text = (result.stderr or b"").decode("utf-8", errors="ignore").strip()
    if result.returncode != 0:
        raise ValueError(stderr_text or stdout_text or f"private gg pjs reader failed ({result.returncode})")
    try:
        data = json.loads(stdout_text)
    except Exception as exc:
        raise ValueError(f"private gg pjs reader json parse failed: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("private gg pjs reader returned non-object payload")

    diagnostics = {
        "reader": "private_gg_pjs_reader",
        "cppreader_path": runtime["cppreader_path"],
        "config_path": runtime["config_path"],
        "matched_candidate": draft_content_path,
        "reader_utils_path": runtime["utils_path"],
        "reader_user_data_path": runtime["user_data_path"],
    }
    return data, diagnostics


def _run_private_reader_to_payload(draft_content_path: str, runtime: dict) -> tuple[dict, dict]:
    rec_path = f"{draft_content_path}.rec"
    try:
        if os.path.exists(rec_path):
            os.remove(rec_path)
    except Exception:
        pass

    attempts = [
        [
            runtime["cppreader_path"],
            runtime["k6"],
            runtime["api_param"],
            draft_content_path,
            runtime["g6_token"],
            _GG_ASSISTANT_SOFTWARE_KEY,
            runtime["utils_path"],
            runtime["user_data_path"],
        ],
        [
            runtime["cppreader_path"],
            runtime["k6"],
            runtime["api_param"],
            draft_content_path,
            runtime["g6_token"],
            _GG_ASSISTANT_SOFTWARE_KEY,
            runtime["utils_path"].replace("\\", "/"),
            runtime["user_data_path"].replace("\\", "/"),
        ],
    ]
    last_error = ""
    for argv in attempts:
        result = subprocess.run(
            argv,
            capture_output=True,
            check=False,
            **_quiet_subprocess_kwargs(),
        )
        stderr = (result.stderr or b"").decode("utf-8", errors="ignore").strip()
        stdout = (result.stdout or b"").decode("utf-8", errors="ignore").strip()
        if result.returncode != 0:
            last_error = stderr or stdout or f"private reader failed ({result.returncode})"
            continue
        if os.path.exists(rec_path):
            break
        last_error = "private reader did not produce .rec payload"
    else:
        raise ValueError(last_error or "private reader failed")

    try:
        data = _decode_rec_payload_via_node(rec_path, runtime["k6"])
        data = _apply_gg_polyfill_defaults(data, runtime["k6"])
    finally:
        try:
            if os.path.exists(rec_path):
                os.remove(rec_path)
        except Exception:
            pass

    diagnostics = {
        "reader": "private_gg_cppreader",
        "cppreader_path": runtime["cppreader_path"],
        "config_path": runtime["config_path"],
        "matched_candidate": draft_content_path,
        "reader_utils_path": runtime["utils_path"],
        "reader_user_data_path": runtime["user_data_path"],
    }
    return data, diagnostics


def _decode_rec_payload_via_node(rec_path: str, k6: str) -> dict:
    script = r"""
const fs = require('fs');
const crypto = require('crypto');
const recPath = process.argv[1];
const key = process.argv[2];
const rec = fs.readFileSync(recPath, 'utf8').trim();
const decipher = crypto.createDecipheriv(
  'aes-128-ecb',
  crypto.createHash('md5').update(key, 'utf8').digest(),
  null
);
decipher.setAutoPadding(true);
const plain = Buffer.concat([decipher.update(rec, 'hex'), decipher.final()]).toString('utf8');
process.stdout.write(plain);
"""
    result = subprocess.run(
        ["node", "-e", script, rec_path, k6],
        capture_output=True,
        check=False,
        **_quiet_subprocess_kwargs(),
    )
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="ignore").strip()
        stdout = (result.stdout or b"").decode("utf-8", errors="ignore").strip()
        raise ValueError((stderr or stdout or "node decrypt failed").strip())
    try:
        payload = (result.stdout or b"").decode("utf-8", errors="ignore")
        data = json.loads(payload)
    except Exception as exc:
        raise ValueError(f"node decrypt json parse failed: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("node decrypt returned non-object draft payload")
    return data


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _apply_gg_polyfill_defaults(data: dict, k6: str) -> dict:
    if not isinstance(data, dict):
        return data
    if data.get("tm_draft_create") is not None:
        return data

    n = _safe_int(str(k6 or "")[1:2], 0)
    o = _safe_int(str(k6 or "")[12:13], 0)
    c = _safe_int(str(k6 or "")[13:14], 0)

    if data.get("duration") is None:
        data["duration"] = c
    if not isinstance(data.get("tracks"), list):
        data["tracks"] = []
    if data.get("fps") is None:
        data["fps"] = (2 - o) * (29 + o)

    for track in data.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        if track.get("attribute") is None:
            track["attribute"] = o - 1
        if not isinstance(track.get("segments"), list):
            track["segments"] = []
        for seg in track.get("segments") or []:
            if not isinstance(seg, dict):
                continue
            tr = seg.get("target_timerange")
            if isinstance(tr, dict):
                if tr.get("start") is None:
                    tr["start"] = int(1e7 * (o - (n % 2)))
                if tr.get("duration") is None:
                    tr["duration"] = int(1e7 * (1 - o))
            sr = seg.get("source_timerange")
            if isinstance(sr, dict):
                if sr.get("start") is None:
                    sr["start"] = int(1e7 * (o - 1))
                if sr.get("duration") is None:
                    sr["duration"] = int(1e7 * (1 - (n % 2)))
            if seg.get("extra_material_refs") is None:
                seg["extra_material_refs"] = []

            ttype = str(track.get("type") or "").lower()
            if ttype in ("video", "audio"):
                if seg.get("speed") is None:
                    seg["speed"] = o + c
                if seg.get("volume") is None:
                    seg["volume"] = (n % 2) - c

            if ttype == "video":
                if not isinstance(seg.get("clip"), dict):
                    seg["clip"] = {}
                clip = seg["clip"]
                if not isinstance(clip.get("scale"), dict):
                    clip["scale"] = {}
                if clip["scale"].get("x") is None:
                    clip["scale"]["x"] = o
                if clip["scale"].get("y") is None:
                    clip["scale"]["y"] = n % 2
                if not isinstance(clip.get("transform"), dict):
                    clip["transform"] = {}
                if clip["transform"].get("x") is None:
                    clip["transform"]["x"] = o - (n % 2)
                if clip["transform"].get("y") is None:
                    clip["transform"]["y"] = (n % 2) - o
                if clip.get("rotation") is None:
                    clip["rotation"] = c
                if not isinstance(clip.get("flip"), dict):
                    clip["flip"] = {}
                if clip["flip"].get("horizontal") is None:
                    clip["flip"]["horizontal"] = False
                if not isinstance(seg.get("uniform_scale"), dict):
                    seg["uniform_scale"] = {}
                if seg["uniform_scale"].get("on") is None:
                    seg["uniform_scale"]["on"] = False
                if seg.get("common_keyframes") is None:
                    seg["common_keyframes"] = []
            elif ttype == "audio":
                if not isinstance(seg.get("clip"), dict):
                    seg["clip"] = {}
                clip = seg["clip"]
                if not isinstance(clip.get("scale"), dict):
                    clip["scale"] = {}
                if clip["scale"].get("x") is None:
                    clip["scale"]["x"] = o
                if clip["scale"].get("y") is None:
                    clip["scale"]["y"] = n % 2
                if not isinstance(clip.get("transform"), dict):
                    clip["transform"] = {}
                if clip["transform"].get("x") is None:
                    clip["transform"]["x"] = o - (n % 2)
                if clip["transform"].get("y") is None:
                    clip["transform"]["y"] = (n % 2) - o
                if not isinstance(clip.get("flip"), dict):
                    clip["flip"] = {}

    if not isinstance(data.get("materials"), dict):
        data["materials"] = {}
    materials = data["materials"]
    defaults = (
        "audios",
        "speeds",
        "audio_fades",
        "beats",
        "sound_channel_mappings",
        "loudnesses",
        "vocal_separations",
        "canvases",
        "videos",
        "texts",
        "drafts",
        "video_effects",
        "effects",
        "stickers",
        "transitions",
        "material_animations",
    )
    for key in defaults:
        if not isinstance(materials.get(key), list):
            materials[key] = []
    return data


def _load_official_encrypted_draft_content(draft_content_path: str) -> tuple[dict, dict]:
    try:
        return official_codec.load_official_draft_payload(draft_content_path)
    except Exception:
        if not _allow_legacy_gg_reader_fallback():
            raise

    runtime = _resolve_private_reader_runtime()
    try:
        try:
            data, diagnostics = _run_private_pjs_reader_to_payload(draft_content_path, runtime)
        except Exception:
            data, diagnostics = _run_private_reader_to_payload(draft_content_path, runtime)
        diagnostics["reader_runtime"] = _summarize_private_reader_runtime(runtime)
        diagnostics["reader_runtime_selection"] = runtime.get("selection_report") or {}
        return data, diagnostics
    except Exception as primary_exc:
        source_root = os.path.dirname(str(draft_content_path or "").strip())
        if not source_root or not os.path.isdir(source_root) or not _path_has_non_ascii(source_root):
            raise
        shadow_root = ""
        try:
            shadow_root = _build_ascii_reader_shadow_root(source_root)
            shadow_path = os.path.join(shadow_root, os.path.basename(draft_content_path))
            try:
                data, diagnostics = _run_private_pjs_reader_to_payload(shadow_path, runtime)
            except Exception:
                data, diagnostics = _run_private_reader_to_payload(shadow_path, runtime)
            diagnostics["matched_candidate"] = draft_content_path
            diagnostics["shadow_read_path"] = shadow_path
            diagnostics["shadow_read_mode"] = "ascii_shadow_copy"
            diagnostics["primary_error"] = str(primary_exc)
            diagnostics["reader_runtime"] = _summarize_private_reader_runtime(runtime)
            diagnostics["reader_runtime_selection"] = runtime.get("selection_report") or {}
            return data, diagnostics
        finally:
            if shadow_root:
                shutil.rmtree(shadow_root, ignore_errors=True)


def _replace_texts(payload: dict, texts_input) -> int:
    replacements = _build_text_replacement_map(texts_input)
    if not replacements:
        return 0

    replaced = 0
    for current_payload in _iter_draft_payloads(payload):
        materials = current_payload.get("materials") or {}
        if not isinstance(materials, dict):
            continue
        text_items = materials.get("texts") or []
        text_template_items = materials.get("text_templates") or []
        if not isinstance(text_items, list):
            continue
        ordered_text_items = [item for item in text_items if isinstance(item, dict)]
        for idx in sorted(replacements.keys()):
            if idx < 0 or idx >= len(ordered_text_items):
                continue
            item = ordered_text_items[idx]
            new_text = replacements[idx]
            old_text = _extract_text_content(item)
            if old_text != new_text:
                _write_text_content(item, new_text)
                replaced += 1
        text_by_id = {}
        for item in text_items:
            if not isinstance(item, dict):
                continue
            material_id = str(item.get("id") or "").strip()
            if material_id:
                text_by_id[material_id] = item
        text_template_by_id = {}
        if isinstance(text_template_items, list):
            for item in text_template_items:
                if not isinstance(item, dict):
                    continue
                material_id = str(item.get("id") or "").strip()
                if material_id:
                    text_template_by_id[material_id] = item
        ordered_material_ids = _collect_text_material_ids_in_track_order(current_payload)
        if not ordered_material_ids:
            continue
        for idx, material_id in enumerate(ordered_material_ids):
            if idx not in replacements:
                continue
            new_text = replacements[idx]
            item = text_by_id.get(material_id)
            if isinstance(item, dict):
                old_text = _extract_text_content(item)
                if old_text != new_text and old_text != "":
                    _write_text_content(item, new_text)
                    replaced += 1

            template_item = text_template_by_id.get(material_id)
            if isinstance(template_item, dict):
                template_item["name"] = new_text
                template_path = str(template_item.get("path") or "").strip()
                template_dir = template_path if os.path.isdir(template_path) else os.path.dirname(template_path)
                if template_dir and os.path.isdir(template_dir):
                    basename = os.path.basename(template_dir).lower()
                    if not basename.startswith("vf"):
                        cloned_dir = _clone_artist_effect_dir(template_dir)
                        if cloned_dir:
                            template_dir = cloned_dir
                            template_item["path"] = _normalize_path_slashes(cloned_dir)
                    _refresh_artist_effect_content(template_dir, [new_text])
                    replaced += 1
    return replaced


def _resolve_payload_media_path(path_value: str, cloned_draft_path: str, payload_root: str = "") -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    if os.path.isabs(raw):
        return raw if os.path.isfile(raw) else ""

    rel = raw.replace("/", os.sep).replace("\\", os.sep)
    candidates = [os.path.join(cloned_draft_path, rel)]
    if payload_root and os.path.isabs(payload_root):
        candidates.append(os.path.join(payload_root, rel))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return ""


def _find_visual_material_by_id(current_payload: dict, material_id: str) -> Optional[dict]:
    materials = current_payload.get("materials") or {}
    if not isinstance(materials, dict):
        return None
    target = str(material_id or "").strip()
    if not target:
        return None
    for media_type in ("videos", "images"):
        for item in materials.get(media_type) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip() == target:
                return item
    return None


def _iter_video_segments_in_order(current_payload: dict):
    tracks = current_payload.get("tracks") or []
    if not isinstance(tracks, list):
        return
    for track in tracks:
        if not isinstance(track, dict):
            continue
        if str(track.get("type") or "").strip().lower() != "video":
            continue
        for segment in track.get("segments") or []:
            if isinstance(segment, dict):
                yield segment


def _select_nested_visual_cover_source(current_payload: dict, cloned_draft_path: str) -> tuple[str, int]:
    payload_root = str(current_payload.get("path") or "").strip()
    retouch_cover = current_payload.get("retouch_cover")
    preferred_segment_id = ""
    preferred_timestamp = 0
    if isinstance(retouch_cover, dict):
        preferred_segment_id = str(retouch_cover.get("frame_segment_id") or "").strip()
        try:
            preferred_timestamp = max(0, int(retouch_cover.get("frame_timestamp") or 0))
        except Exception:
            preferred_timestamp = 0

    for preview_path in (
        current_payload.get("static_cover_image_path"),
        retouch_cover.get("image_path") if isinstance(retouch_cover, dict) else "",
    ):
        source_path = _resolve_payload_media_path(
            preview_path,
            cloned_draft_path,
            payload_root=payload_root,
        )
        if source_path and os.path.isfile(source_path):
            return source_path, preferred_timestamp

    preferred_segment = None
    fallback_segment = None
    for segment in _iter_video_segments_in_order(current_payload):
        if fallback_segment is None:
            fallback_segment = segment
        if preferred_segment_id and str(segment.get("id") or "").strip() == preferred_segment_id:
            preferred_segment = segment
            break

    for segment, timestamp_us in (
        (preferred_segment, preferred_timestamp),
        (fallback_segment, 0),
    ):
        if not isinstance(segment, dict):
            continue
        material = _find_visual_material_by_id(current_payload, segment.get("material_id"))
        if not isinstance(material, dict):
            continue
        source_path = _resolve_payload_media_path(
            material.get("path") or material.get("file_path"),
            cloned_draft_path,
            payload_root=payload_root,
        )
        if source_path and os.path.isfile(source_path):
            return source_path, timestamp_us

    materials = current_payload.get("materials") or {}
    if not isinstance(materials, dict):
        return "", 0
    for media_type in ("images", "videos"):
        for item in materials.get(media_type) or []:
            if not isinstance(item, dict):
                continue
            source_path = _resolve_payload_media_path(
                item.get("path") or item.get("file_path"),
                cloned_draft_path,
                payload_root=payload_root,
            )
            if source_path and os.path.isfile(source_path):
                return source_path, 0
    return "", 0


def _write_visual_cover_image(source_path: str, target_path: str, timestamp_us: int = 0) -> bool:
    source = str(source_path or "").strip()
    target = str(target_path or "").strip()
    if not source or not target or not os.path.isfile(source):
        return False
    if os.path.normcase(os.path.normpath(source)) == os.path.normcase(os.path.normpath(target)):
        return False
    os.makedirs(os.path.dirname(target), exist_ok=True)

    def normalize_image_to_target(source_image_path: str) -> bool:
        try:
            from PIL import Image, ImageOps

            target_size = None
            target_mode = ""
            target_alpha = None
            if os.path.isfile(target):
                with Image.open(target) as existing_img:
                    target_size = existing_img.size
                    target_mode = str(existing_img.mode or "")
                    if "A" in target_mode:
                        target_alpha = existing_img.convert("RGBA").getchannel("A")

            with Image.open(source_image_path) as src_img:
                output_img = src_img
                if target_size:
                    output_img = ImageOps.fit(output_img, target_size)
                if target_mode:
                    if "A" in target_mode:
                        output_img = output_img.convert("RGBA")
                        if target_alpha is not None:
                            output_img.putalpha(target_alpha)
                        output_img = output_img.convert(target_mode)
                    else:
                        output_img = output_img.convert(target_mode)
                elif os.path.splitext(target)[1].lower() in {".jpg", ".jpeg"}:
                    output_img = output_img.convert("RGB")

                if os.path.splitext(target)[1].lower() in {".jpg", ".jpeg"}:
                    if output_img.mode not in {"RGB", "L"}:
                        output_img = output_img.convert("RGB")
                    output_img.save(target, format="JPEG", quality=90)
                else:
                    output_img.save(target)
            return True
        except Exception:
            return False

    ext = os.path.splitext(source)[1].lower()
    target_ext = os.path.splitext(target)[1].lower()
    if ext in _IMAGE_EXTS:
        if normalize_image_to_target(source):
            return True
        if ext == target_ext:
            try:
                shutil.copy2(source, target)
                return True
            except Exception:
                return False
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return False
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                source,
                target,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            **_quiet_subprocess_kwargs(),
        )
        return result.returncode == 0 and os.path.isfile(target) and os.path.getsize(target) > 0

    if ext not in _VIDEO_EXTS:
        return False
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False
    temp_frame_path = ""
    if os.path.isfile(target) and target_ext in _IMAGE_EXTS:
        temp_frame_path = f"{target}.vf_cover_frame.tmp.png"
    cmd = [ffmpeg, "-y"]
    if timestamp_us > 0:
        cmd.extend(["-ss", f"{timestamp_us / 1000000.0:.6f}"])
    cmd.extend(
        [
            "-i",
            source,
            "-frames:v",
            "1",
            temp_frame_path or target,
        ]
    )
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        **_quiet_subprocess_kwargs(),
    )
    if result.returncode != 0:
        if temp_frame_path and os.path.isfile(temp_frame_path):
            try:
                os.remove(temp_frame_path)
            except Exception:
                pass
        return False
    if temp_frame_path:
        ok = normalize_image_to_target(temp_frame_path)
        try:
            os.remove(temp_frame_path)
        except Exception:
            pass
        return ok and os.path.isfile(target) and os.path.getsize(target) > 0
    return os.path.isfile(target) and os.path.getsize(target) > 0


def _iter_draft_cover_targets(cloned_draft_path: str) -> list[str]:
    targets = [
        os.path.join(cloned_draft_path, "draft_cover.jpg"),
        os.path.join(cloned_draft_path, "cover.jpg"),
    ]
    timelines_root = os.path.join(cloned_draft_path, "Timelines")
    if os.path.isdir(timelines_root):
        for timeline_name in os.listdir(timelines_root):
            timeline_dir = os.path.join(timelines_root, timeline_name)
            if os.path.isdir(timeline_dir):
                targets.append(os.path.join(timeline_dir, "draft_cover.jpg"))
    return _merge_unique_paths(targets)


def _sync_cover_targets(primary_path: str, cloned_draft_path: str) -> int:
    if not primary_path or not os.path.isfile(primary_path):
        return 0
    synced = 0
    primary_norm = os.path.normcase(os.path.normpath(primary_path))
    for target_path in _iter_draft_cover_targets(cloned_draft_path):
        target_norm = os.path.normcase(os.path.normpath(target_path))
        if target_norm == primary_norm:
            continue
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(primary_path, target_path)
            synced += 1
        except Exception:
            continue
    return synced


def _build_nested_cover_relative_path(current_payload: dict) -> str:
    existing = str(current_payload.get("static_cover_image_path") or "").strip().replace("\\", "/")
    if existing and not os.path.isabs(existing):
        rel = existing.lstrip("/")
        if rel.lower().startswith("materials/"):
            base, ext = os.path.splitext(rel)
            return rel if ext else f"{base}.png"
    current_id = str(current_payload.get("id") or "").strip() or uuid.uuid4().hex
    return f"materials/video/cover_{current_id}.png"


def _refresh_nested_combination_visual_covers(payload: dict, cloned_draft_path: str) -> int:
    if not isinstance(payload, dict):
        return 0

    refreshed = 0
    for current_payload in _iter_draft_payloads(payload):
        if current_payload is payload:
            continue
        source_path, timestamp_us = _select_nested_visual_cover_source(current_payload, cloned_draft_path)
        if not source_path:
            continue
        nested_root = str(current_payload.get("path") or "").strip()
        if nested_root and os.path.isabs(nested_root) and os.path.isdir(nested_root):
            # Official nested templateDraft thumbnails have extra private semantics that
            # are not fully reversed yet. Do not mutate those cache files in the stable
            # replacement path; keep this branch disabled until the display-cache rules
            # are reconstructed separately.
            continue

        cover_rel = _build_nested_cover_relative_path(current_payload)
        cover_target = os.path.join(cloned_draft_path, cover_rel.replace("/", os.sep))
        if _write_visual_cover_image(source_path, cover_target, timestamp_us):
            current_payload["static_cover_image_path"] = _normalize_path_slashes(cover_rel)
            refreshed += 1

    return refreshed


def _refresh_draft_cover_from_visuals(payload: dict, cloned_draft_path: str) -> bool:
    if not isinstance(payload, dict):
        return False
    target_path = os.path.join(cloned_draft_path, "draft_cover.jpg")
    for current_payload in _iter_draft_payloads(payload):
        if current_payload is payload:
            continue
        source_path, timestamp_us = _select_nested_visual_cover_source(current_payload, cloned_draft_path)
        if not source_path:
            continue
        if _write_visual_cover_image(source_path, target_path, timestamp_us):
            _sync_cover_targets(target_path, cloned_draft_path)
            return True

    image_candidates: list[str] = []
    image_like_video_candidates: list[str] = []
    video_candidates: list[str] = []
    for current_payload in _iter_draft_payloads(payload):
        materials = current_payload.get("materials") or {}
        if not isinstance(materials, dict):
            continue
        for item in materials.get("images") or []:
            if not isinstance(item, dict):
                continue
            path_value = str(item.get("path") or item.get("file_path") or "").strip()
            if not path_value:
                continue
            if os.path.isabs(path_value):
                image_candidates.append(path_value)
            else:
                image_candidates.append(os.path.join(cloned_draft_path, path_value.replace("/", os.sep)))
        for item in materials.get("videos") or []:
            if not isinstance(item, dict):
                continue
            path_value = str(item.get("path") or item.get("file_path") or "").strip()
            if not path_value:
                continue
            material_kind = str(item.get("type") or "").strip().lower()
            path_ext = os.path.splitext(path_value)[1].lower()
            candidate_path = path_value if os.path.isabs(path_value) else os.path.join(cloned_draft_path, path_value.replace("/", os.sep))
            if material_kind in {"photo", "image", "gif"} or path_ext in _IMAGE_EXTS:
                image_like_video_candidates.append(candidate_path)
                continue
            if os.path.isabs(path_value):
                video_candidates.append(path_value)
            else:
                video_candidates.append(os.path.join(cloned_draft_path, path_value.replace("/", os.sep)))
    for src in _merge_unique_paths(image_candidates, image_like_video_candidates):
        if not os.path.isfile(src):
            continue
        try:
            from PIL import Image
            with Image.open(src) as img:
                rgb = img.convert("RGB")
                rgb.save(target_path, format="JPEG", quality=90)
            _sync_cover_targets(target_path, cloned_draft_path)
            return True
        except Exception:
            try:
                shutil.copy2(src, target_path)
                _sync_cover_targets(target_path, cloned_draft_path)
                return True
            except Exception:
                continue
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False
    for src in video_candidates:
        if not os.path.isfile(src):
            continue
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                src,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                target_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            **_quiet_subprocess_kwargs(),
        )
        if result.returncode == 0 and os.path.isfile(target_path) and os.path.getsize(target_path) > 0:
            _sync_cover_targets(target_path, cloned_draft_path)
            return True
    root_cover_path = os.path.join(cloned_draft_path, "cover.jpg")
    if os.path.isfile(root_cover_path) and os.path.getsize(root_cover_path) > 0:
        try:
            shutil.copy2(root_cover_path, target_path)
            _sync_cover_targets(target_path, cloned_draft_path)
            return True
        except Exception:
            return False
    return False


def _regenerate_combination_material_ids(payload: dict) -> int:
    if not isinstance(payload, dict):
        return 0
    materials = payload.get("materials") or {}
    drafts = materials.get("drafts") if isinstance(materials, dict) else None
    if not isinstance(drafts, list):
        return 0
    refreshed = 0
    for item in drafts:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() != "combination":
            continue
        old_value = str(item.get("combination_id") or "").strip()
        if not old_value:
            continue
        item["combination_id"] = str(uuid.uuid4()).upper()
        refreshed += 1
    return refreshed


def replace_official_draft(
    template_path: str,
    draft_name: str,
    texts_input=None,
    material_replacements=None,
    output_root: Optional[str] = None,
):
    material_replacements = _normalize_material_replacement_map(material_replacements)
    source_info_path, source_info_diag = _resolve_source_info_path_from_root_meta(template_path)
    source_info_path = os.path.normpath(str(source_info_path or "").strip()) if source_info_path else ""
    normalized_template_path = os.path.normpath(normalize_draft_project_path(template_path) or template_path)
    source_primary_path = os.path.normpath(source_info_path or _resolve_primary_draft_content_path(normalized_template_path))
    source_draft_root = os.path.normpath(os.path.dirname(source_primary_path) or normalized_template_path)
    source_payload, diagnostics = _load_active_payload_with_fallback(source_primary_path, source_draft_root)

    staging_draft_path, final_draft_path = _clone_draft_tree(template_path, output_root, draft_name)
    cloned_draft_path = staging_draft_path
    _update_draft_meta_info(cloned_draft_path, draft_name)
    source_read_path = str((diagnostics or {}).get("read_path") or "").strip() or source_primary_path
    working_path = _resolve_cloned_info_path(
        cloned_draft_path,
        source_read_path,
        source_draft_root=source_draft_root,
    )
    source_payload_snapshot = _deep_clone_json_like(source_payload)
    working_payload = source_payload

    _update_draft_meta_info_with_info_path(cloned_draft_path, draft_name, working_path)
    localized_material_replacements = _localize_material_replacements_for_draft(material_replacements, cloned_draft_path)

    diagnostics = diagnostics or {}
    summary = {
        "draft_path": cloned_draft_path,
        "draft_content_path": working_path,
        "text_replaced": 0,
        "material_replaced": 0,
        "warnings": [],
        "diagnostics": diagnostics,
    }
    diagnostics["source_info_path"] = source_info_path
    diagnostics["source_primary_path"] = source_primary_path
    diagnostics["source_read_path"] = source_read_path
    diagnostics["source_info_resolution"] = source_info_diag
    diagnostics["write_info_path"] = working_path
    diagnostics["source_draft_root"] = source_draft_root
    shell_payload, shell_payload_path = _select_best_plain_shell_payload(cloned_draft_path)
    diagnostics["shell_payload_path"] = shell_payload_path

    summary["text_replaced"] = _replace_texts(working_payload, texts_input)
    text_replacements = _build_text_replacement_map(texts_input)
    summary["material_replaced"] = replace_materials(
        working_payload,
        localized_material_replacements,
        cloned_draft_path=cloned_draft_path,
        image_exts=_IMAGE_EXTS,
        detect_media_kind=_detect_media_kind,
        normalize_abs_path=_normalize_abs_path,
        collect_referenced_material_ids=_collect_referenced_material_ids,
        material_name_is_excluded=_material_name_is_excluded,
        lookup_material_override=_lookup_material_override,
        parse_replacement_media_info=_parse_replacement_media_info,
        safe_int=_safe_int,
    )
    diagnostics["localized_material_replacements"] = len(localized_material_replacements or {})
    diagnostics["cache_clone_semantics"] = {}
    if _payload_has_official_nested_cache_semantics(working_payload) and isinstance(source_payload_snapshot, dict):
        diagnostics["cache_clone_semantics"] = _externalize_nested_official_cache_semantics(
            working_payload,
            source_payload_snapshot,
            cloned_draft_path,
            text_replacements,
        )
        diagnostics["rebased_internal_paths"] = 0
    else:
        diagnostics["rebased_internal_paths"] = _rebase_source_internal_paths(
            working_payload,
            source_draft_root,
            cloned_draft_path,
        )
    diagnostics["hydrated_payload_materials"] = 0
    diagnostics["sanitized_missing_cover_paths"] = 0
    diagnostics["nested_visual_covers_refreshed"] = 0
    diagnostics["combination_ids_regenerated"] = _regenerate_combination_material_ids(working_payload)
    diagnostics["cover_refreshed"] = _refresh_draft_cover_from_visuals(working_payload, cloned_draft_path)

    if not summary["text_replaced"] and texts_input:
        summary["warnings"].append("no text material matched")
    if not summary["material_replaced"] and localized_material_replacements:
        summary["warnings"].append("no media material matched")

    info_written_paths = _write_by_info_path_with_main_timeline_mirror(working_path, working_payload, cloned_draft_path)
    diagnostics["write_mode"] = (
        "encrypted_source_rewritten_to_info_path_with_main_timeline_mirror"
        if str(diagnostics.get("read_mode") or "").strip().startswith("encrypted")
        else "info_path_with_main_timeline_mirror"
    )
    diagnostics["timeline_project_reconciliation"] = _reconcile_timeline_project_files(cloned_draft_path)
    published_draft_path = _publish_generated_draft(cloned_draft_path, final_draft_path)
    published_info_path = _map_path_between_roots(working_path, cloned_draft_path, published_draft_path)
    published_written_paths = [
        _map_path_between_roots(path_value, cloned_draft_path, published_draft_path)
        for path_value in info_written_paths
    ]
    summary["draft_path"] = published_draft_path
    summary["draft_content_path"] = published_info_path
    summary["written_paths"] = _merge_unique_paths(published_written_paths)
    finalized_meta = _finalize_generated_draft_meta_and_root_index(
        published_draft_path,
        draft_name,
        published_info_path,
        working_payload,
    )
    diagnostics["final_draft_timeline_materials_size"] = int(
        (finalized_meta or {}).get("draft_timeline_materials_size_") or 0
    )
    diagnostics["frame_thumbnail_cache_cleared"] = _clear_jianying_frame_thumbnail_cache()

    return summary
