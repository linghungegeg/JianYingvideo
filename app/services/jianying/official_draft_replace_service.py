import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
import hashlib
from pathlib import Path
from typing import Optional

from app.services.jianying.local_draft_service import (
    load_json_file_with_encodings,
    normalize_draft_project_path,
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


def _clone_draft_tree(template_path: str, output_root: Optional[str], draft_name: str) -> str:
    normalized_template_path = normalize_draft_project_path(template_path)
    if not normalized_template_path or not os.path.isdir(normalized_template_path):
        raise ValueError("template_path is invalid")

    drafts_root = str(output_root or get_drafts_folder() or "").strip()
    if not drafts_root:
        drafts_root = os.path.dirname(normalized_template_path.rstrip("\\/"))
    if not drafts_root:
        raise ValueError("drafts folder is not configured")

    os.makedirs(drafts_root, exist_ok=True)
    target_path = os.path.join(drafts_root, draft_name)
    if os.path.exists(target_path):
        raise FileExistsError(f"draft already exists: {target_path}")
    shutil.copytree(normalized_template_path, target_path)
    return target_path


def _update_draft_meta_info(cloned_draft_path: str, draft_name: str) -> None:
    meta_path = os.path.join(cloned_draft_path, "draft_meta_info.json")
    if not os.path.exists(meta_path):
        return
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except Exception:
        return
    if not isinstance(meta, dict):
        return

    now_ms = int(time.time() * 1000)
    meta["draft_name"] = draft_name
    meta["draft_fold_path"] = cloned_draft_path
    meta["tm_draft_create"] = now_ms
    meta["tm_draft_modified"] = now_ms
    try:
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False, indent=2)
    except Exception:
        return


def _update_draft_meta_info_with_info_path(cloned_draft_path: str, draft_name: str, info_path: str) -> None:
    meta_path = os.path.join(cloned_draft_path, "draft_meta_info.json")
    if not os.path.exists(meta_path):
        return

    meta = None
    if _looks_like_plain_json(meta_path):
        loaded, err = load_json_file_with_encodings(meta_path)
        if err is None and isinstance(loaded, dict):
            meta = loaded
    else:
        # Keep consistent with gg flow: metadata may also be encrypted.
        try:
            loaded, _diag = _load_official_encrypted_draft_content(meta_path)
            if isinstance(loaded, dict):
                meta = loaded
        except Exception:
            meta = None

    if not isinstance(meta, dict):
        return

    now_ms = int(time.time() * 1000)
    meta["draft_name"] = draft_name
    meta["draft_fold_path"] = cloned_draft_path
    meta["draft_json_file"] = str(info_path or "").strip() or meta.get("draft_json_file")
    meta["tm_draft_create"] = now_ms
    meta["tm_draft_modified"] = now_ms
    try:
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False, indent=2)
    except Exception:
        return


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


def _candidate_jianying_frame_thumbnail_dirs() -> list[str]:
    home = Path.home()
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
    candidates = [
        local_app_data / "JianyingPro" / "User Data" / "Cache" / "frameThumbnail",
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
    reports = [_clear_directory_children(path) for path in _candidate_jianying_frame_thumbnail_dirs()]
    deleted_entries = sum(int(item.get("deleted") or 0) for item in reports)
    failed_entries = sum(len(item.get("failed") or []) for item in reports)
    return {
        "ok": failed_entries == 0,
        "deleted_entries": deleted_entries,
        "failed_entries": failed_entries,
        "paths": reports,
    }


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


def _select_best_plain_active_payload(cloned_draft_path: str) -> tuple[Optional[dict], str]:
    best_data = None
    best_path = ""
    best_score = (-1, -1, -1, -1, -1)
    for target in _iter_plain_payload_targets(cloned_draft_path):
        data, err = _load_plain_json(target)
        if err is not None or not isinstance(data, dict):
            continue
        if _classify_payload_shape(data) != "active":
            continue
        score = _payload_activity_score(data)
        if score > best_score:
            best_score = score
            best_data = data
            best_path = target
    return best_data, best_path


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
    file_name = os.path.basename(target_path).lower()
    if file_name == "template.tmp":
        return active_payload
    if file_name == "template.json":
        return shell_payload if isinstance(shell_payload, dict) else existing
    shape = _classify_payload_shape(existing)
    if shape == "active":
        return active_payload
    if shape == "shell":
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


def _localize_material_replacements_for_draft(material_replacements: dict, cloned_draft_path: str) -> dict:
    if not isinstance(material_replacements, dict) or not material_replacements:
        return {}

    localized: dict[str, str] = {}
    copied_by_source: dict[str, str] = {}
    target_root = os.path.join(cloned_draft_path, "materialResources", "_vf_replacements")
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
        if source_norm in copied_by_source:
            localized[key] = copied_by_source[source_norm]
            continue

        base_name = os.path.basename(source_abs) or f"{uuid.uuid4().hex}.bin"
        dst_path = os.path.join(target_root, base_name)
        if os.path.exists(dst_path):
            stem, ext = os.path.splitext(base_name)
            dst_path = os.path.join(target_root, f"{stem}_{uuid.uuid4().hex[:8]}{ext}")
        try:
            shutil.copy2(source_abs, dst_path)
            resolved = os.path.abspath(dst_path)
        except Exception:
            resolved = source_abs
        copied_by_source[source_norm] = resolved
        localized[key] = resolved

    return localized


def _write_by_info_path_with_main_timeline_mirror(read_path: str, data: dict, cloned_draft_path: str) -> list[str]:
    if not read_path:
        return []
    _write_json_file(read_path, data)
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
    _write_json_file(mirror_path, data)
    written.append(mirror_path)
    return written


def _write_draft_content_targets(data: dict, cloned_draft_path: str) -> list[str]:
    written: list[str] = []
    for target in _iter_draft_content_targets(cloned_draft_path):
        _write_json_file(target, data)
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
    if rel_parts[0].lower() == "materials":
        return "/".join(rel_parts)
    if rel_parts[0].lower() in {"video", "image", "audio", "retouch_cover"}:
        return "materials/" + "/".join(rel_parts)
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
            if os.path.isabs(str(value or "").strip()) and str(rebased or "").strip().replace("\\", "/").startswith("materials/"):
                asset_copy_pairs.append((str(value or "").strip(), str(rebased or "").strip().replace("\\", "/")))

    for current_payload in _iter_draft_payloads(payload):
        if not isinstance(current_payload, dict):
            continue

        payload_path = current_payload.get("path")
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
                            if os.path.isabs(str(value or "").strip()) and str(rebased or "").strip().replace("\\", "/").startswith("materials/"):
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
                        if os.path.isabs(str(value or "").strip()) and str(rebased or "").strip().replace("\\", "/").startswith("materials/"):
                            asset_copy_pairs.append((str(value or "").strip(), str(rebased or "").strip().replace("\\", "/")))

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


def _hydrate_missing_materials_from_payload_roots(payload: dict, cloned_draft_path: str) -> int:
    copied = 0
    seen_pairs: set[tuple[str, str]] = set()

    def try_copy_from_payload_root(payload_root: str, rel_path: str, item: dict | None = None, media_type: str = "") -> None:
        nonlocal copied
        if not payload_root or not rel_path:
            return
        rel_norm = rel_path.replace("\\", "/")
        dst_abs = os.path.join(cloned_draft_path, rel_norm.replace("/", os.sep))
        if os.path.isfile(dst_abs):
            return

        tail = rel_norm
        if tail.lower().startswith("materials/"):
            tail = tail.split("/", 1)[1] if "/" in tail else ""
        basename = os.path.basename(rel_norm)
        candidates = [
            os.path.join(payload_root, rel_norm.replace("/", os.sep)),
            os.path.join(payload_root, tail.replace("/", os.sep)) if tail else "",
        ]
        if media_type == "videos" and basename and "_water_mark" in basename.lower():
            candidates.append(os.path.join(payload_root, "video", "cover", basename))
        if media_type == "audios" and isinstance(item, dict):
            for key in ("effect_id", "music_id", "local_material_id", "resource_id"):
                value = str(item.get(key) or "").strip()
                if not value:
                    continue
                ext = os.path.splitext(basename)[1] or ".mp3"
                candidates.append(os.path.join(payload_root, "audio", f"{value}{ext}"))
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

    for current_payload in _iter_draft_payloads(payload):
        if not isinstance(current_payload, dict):
            continue
        payload_root = str(current_payload.get("path") or "").strip()
        if not (payload_root and os.path.isabs(payload_root) and os.path.isdir(payload_root)):
            continue

        static_cover = str(current_payload.get("static_cover_image_path") or "").strip()
        if static_cover and not os.path.isabs(static_cover):
            try_copy_from_payload_root(payload_root, static_cover)

        retouch_cover = current_payload.get("retouch_cover")
        if isinstance(retouch_cover, dict):
            for key in ("retouch_path", "image_path"):
                value = str(retouch_cover.get(key) or "").strip()
                if value and not os.path.isabs(value):
                    try_copy_from_payload_root(payload_root, value)

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
                        try_copy_from_payload_root(payload_root, value, item=item, media_type=media_type)
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
        # gg-jy-assistant only targets normal text tracks (attribute == 0)
        try:
            if int(track.get("attribute") or 0) != 0:
                continue
        except Exception:
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


def _candidate_gg_roots() -> list[str]:
    candidates = []
    env_root = str(os.environ.get("GG_JY_ASSISTANT_ROOT") or "").strip()
    if env_root:
        candidates.append(env_root)

    for raw in (
        r"D:\gg-jy-assistant",
        r"E:\gg-jy-assistant",
    ):
        candidates.append(raw)

    bundled_root = app_resource_path("runtime_tools", _OFFICIAL_READER_RUNTIME_DIRNAME)
    if bundled_root.exists():
        candidates.append(str(bundled_root))

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
    if os.path.exists(os.path.join(root, "resources", "app.asar.unpacked")):
        return unpacked_semantic

    source_utils = os.path.join(root, "resources", "app_source", "build", "electron", "utils")
    if os.path.isdir(source_utils):
        return source_utils

    return packaged_semantic


def _candidate_reader_config_paths(root: str) -> list[Path]:
    home = Path.home()
    roaming_config = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / _GG_ASSISTANT_SOFTWARE_KEY / "config.json"
    candidates = [
        roaming_config,
        Path(root) / "userdata" / _GG_ASSISTANT_SOFTWARE_KEY / "config.json",
        Path(root) / "user_data" / "config.json",
        Path(root) / "config.json",
    ]
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


def _resolve_gg_like_timeline_root(primary_path: str) -> str:
    project_root = os.path.dirname(str(primary_path or ""))
    if not project_root:
        return ""

    try:
        runtime = _resolve_private_reader_runtime()
        root_name = _compute_gg_timeline_root_dirname(runtime.get("k6"))
    except Exception:
        root_name = "Timelines"
    return os.path.join(project_root, root_name)


def _resolve_private_reader_runtime() -> dict:
    for root in _candidate_gg_roots():
        cppreader_path = os.path.join(root, "resources", "enhance", "win32", "x64", "cppreader.exe")
        utils_path = _resolve_reader_utils_path(root)
        has_reader_context = (
            os.path.exists(os.path.join(root, "resources", "app.asar"))
            or os.path.exists(os.path.join(root, "resources", "app.asar.unpacked"))
            or os.path.isdir(utils_path)
        )
        if not (os.path.exists(cppreader_path) and has_reader_context):
            continue

        for config_path in _candidate_reader_config_paths(root):
            if not config_path.exists():
                continue
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(config, dict):
                continue

            g6 = str(config.get("g6") or "").strip()
            k6 = str(config.get("k6") or "").strip()
            k6p_raw = str(config.get("k6p") or "").strip()
            if len(g6) < 11 or not k6 or not k6p_raw:
                continue
            try:
                api_param = json.loads(json.dumps(k6p_raw))
                api_param = __import__("base64").b64decode(api_param).decode("utf-8")
            except Exception:
                continue
            if len(api_param) < 20:
                continue

            user_data_path = str(config_path.parent).replace("\\", "/")
            if os.path.basename(user_data_path).lower() == "user_data":
                bundled_userdata = Path(root) / "userdata" / _GG_ASSISTANT_SOFTWARE_KEY
                if bundled_userdata.is_dir():
                    user_data_path = str(bundled_userdata).replace("\\", "/")
            return {
                "root": root,
                "cppreader_path": cppreader_path,
                "utils_path": utils_path,
                "g6_token": g6[10:],
                "k6": k6,
                "api_param": api_param,
                "user_data_path": user_data_path,
                "config_path": str(config_path),
            }

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
    runtime = _resolve_private_reader_runtime()
    try:
        return _run_private_reader_to_payload(draft_content_path, runtime)
    except Exception as primary_exc:
        source_root = os.path.dirname(str(draft_content_path or "").strip())
        if not source_root or not os.path.isdir(source_root) or not _path_has_non_ascii(source_root):
            raise
        shadow_root = ""
        try:
            shadow_root = _build_ascii_reader_shadow_root(source_root)
            shadow_path = os.path.join(shadow_root, os.path.basename(draft_content_path))
            data, diagnostics = _run_private_reader_to_payload(shadow_path, runtime)
            diagnostics["matched_candidate"] = draft_content_path
            diagnostics["shadow_read_path"] = shadow_path
            diagnostics["shadow_read_mode"] = "ascii_shadow_copy"
            diagnostics["primary_error"] = str(primary_exc)
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
        if not isinstance(text_items, list):
            continue
        text_by_id = {}
        for item in text_items:
            if not isinstance(item, dict):
                continue
            material_id = str(item.get("id") or "").strip()
            if material_id:
                text_by_id[material_id] = item
        ordered_material_ids = _collect_text_material_ids_in_track_order(current_payload)
        if not ordered_material_ids:
            continue
        for idx, material_id in enumerate(ordered_material_ids):
            if idx not in replacements:
                continue
            item = text_by_id.get(material_id)
            if not isinstance(item, dict):
                continue
            old_text = _extract_text_content(item)
            if old_text == "":
                continue
            new_text = replacements[idx]
            _write_text_content(item, new_text)
            replaced += 1
    return replaced


def _replace_materials(payload: dict, material_replacements) -> int:
    if not isinstance(material_replacements, dict) or not material_replacements:
        return 0

    replaced = 0
    for current_payload in _iter_draft_payloads(payload):
        materials = current_payload.get("materials", {})
        if not isinstance(materials, dict):
            continue
        referenced_video_ids = _collect_referenced_material_ids(current_payload, "video")
        referenced_audio_ids = _collect_referenced_material_ids(current_payload, "audio")
        for media_type in ("videos", "images", "audios"):
            items = materials.get(media_type) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                material_id = str(item.get("id") or "").strip()
                if media_type in ("videos", "images"):
                    if material_id and material_id not in referenced_video_ids:
                        continue
                    if _material_name_is_excluded(item):
                        continue
                elif media_type == "audios":
                    if material_id and material_id not in referenced_audio_ids:
                        continue
                current_path = item.get("path") or item.get("file_path") or ""
                override_path = _lookup_material_override(
                    material_replacements,
                    material_name=item.get("material_name") or item.get("name"),
                    material_path=current_path,
                    material_id=material_id,
                )
                if not override_path:
                    continue
                override_kind = _detect_media_kind(override_path)
                material_kind = str(item.get("type") or "").strip().lower()
                if material_kind in ("video",):
                    current_kind = "videos"
                elif material_kind in ("photo", "gif", "image"):
                    current_kind = "images"
                elif material_kind in ("audio",):
                    current_kind = "audios"
                else:
                    current_kind = _detect_media_kind(current_path) or media_type
                if override_kind and current_kind and override_kind != current_kind:
                    continue
                item["path"] = override_path
                if "file_path" in item:
                    item["file_path"] = override_path
                base_name = os.path.basename(override_path)
                if base_name:
                    if "material_name" in item:
                        item["material_name"] = base_name
                    if "name" in item:
                        item["name"] = base_name
                media_info = parse_media_info(override_path) or {}
                width = media_info.get("width")
                height = media_info.get("height")
                duration = media_info.get("duration")
                if isinstance(width, int) and width > 0:
                    item["width"] = width
                if isinstance(height, int) and height > 0:
                    item["height"] = height
                if isinstance(duration, (int, float)) and duration > 0:
                    item["duration"] = int(round(float(duration) * 1000000))
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
    os.makedirs(os.path.dirname(target), exist_ok=True)

    ext = os.path.splitext(source)[1].lower()
    target_ext = os.path.splitext(target)[1].lower()
    if ext in _IMAGE_EXTS:
        try:
            from PIL import Image

            with Image.open(source) as img:
                if target_ext in {".jpg", ".jpeg"}:
                    img.convert("RGB").save(target, format="JPEG", quality=90)
                else:
                    img.save(target)
            return True
        except Exception:
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
    cmd = [ffmpeg, "-y"]
    if timestamp_us > 0:
        cmd.extend(["-ss", f"{timestamp_us / 1000000.0:.6f}"])
    cmd.extend(
        [
            "-i",
            source,
            "-frames:v",
            "1",
            target,
        ]
    )
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        **_quiet_subprocess_kwargs(),
    )
    return result.returncode == 0 and os.path.isfile(target) and os.path.getsize(target) > 0


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
    cover_path_by_nested_payload: dict[int, str] = {}
    clone_root = str(cloned_draft_path).replace("\\", "/")

    for current_payload in _iter_draft_payloads(payload):
        if current_payload is payload:
            continue
        source_path, timestamp_us = _select_nested_visual_cover_source(current_payload, cloned_draft_path)
        if not source_path:
            continue
        relative_cover_path = _build_nested_cover_relative_path(current_payload)
        target_abs = os.path.join(cloned_draft_path, relative_cover_path.replace("/", os.sep))
        if not _write_visual_cover_image(source_path, target_abs, timestamp_us=timestamp_us):
            continue

        current_payload["path"] = clone_root
        current_payload["static_cover_image_path"] = relative_cover_path
        retouch_cover = current_payload.get("retouch_cover")
        if isinstance(retouch_cover, dict):
            retouch_cover["retouch_path"] = ""
            retouch_cover["image_path"] = relative_cover_path
            retouch_cover["base_type"] = "image"
            if "frame_segment_id" in retouch_cover:
                retouch_cover["frame_segment_id"] = ""
            if "frame_timestamp" in retouch_cover:
                retouch_cover["frame_timestamp"] = 0
        cover_path_by_nested_payload[id(current_payload)] = relative_cover_path
        refreshed += 1

    if not cover_path_by_nested_payload:
        return refreshed

    for owner_payload in _iter_draft_payloads(payload):
        materials = owner_payload.get("materials") or {}
        if not isinstance(materials, dict):
            continue
        for draft_item in materials.get("drafts") or []:
            if not isinstance(draft_item, dict):
                continue
            nested_payload = draft_item.get("draft")
            if not isinstance(nested_payload, dict):
                continue
            relative_cover_path = cover_path_by_nested_payload.get(id(nested_payload))
            if not relative_cover_path:
                continue
            draft_item["draft_cover_path"] = relative_cover_path

    return refreshed


def _refresh_draft_cover_from_visuals(payload: dict, cloned_draft_path: str) -> bool:
    if not isinstance(payload, dict):
        return False
    image_candidates: list[str] = []
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
            if os.path.isabs(path_value):
                video_candidates.append(path_value)
            else:
                video_candidates.append(os.path.join(cloned_draft_path, path_value.replace("/", os.sep)))
    target_path = os.path.join(cloned_draft_path, "draft_cover.jpg")
    for src in image_candidates:
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
    return False


def replace_official_draft(
    template_path: str,
    draft_name: str,
    texts_input=None,
    material_replacements=None,
    output_root: Optional[str] = None,
):
    material_replacements = _normalize_material_replacement_map(material_replacements)
    source_info_path, source_info_diag = _resolve_source_info_path_from_root_meta(template_path)
    normalized_template_path = normalize_draft_project_path(template_path) or template_path
    source_primary_path = source_info_path or _resolve_primary_draft_content_path(normalized_template_path)
    source_draft_root = os.path.dirname(source_primary_path) or normalized_template_path
    source_payload, diagnostics = _load_active_payload_with_fallback(source_primary_path, source_draft_root)

    cloned_draft_path = _clone_draft_tree(template_path, output_root, draft_name)
    _update_draft_meta_info(cloned_draft_path, draft_name)
    source_read_path = str((diagnostics or {}).get("read_path") or "").strip() or source_primary_path
    working_path = _resolve_cloned_info_path(
        cloned_draft_path,
        source_read_path,
        source_draft_root=source_draft_root,
    )
    working_payload = source_payload

    _update_draft_meta_info_with_info_path(cloned_draft_path, draft_name, working_path)
    localized_material_replacements = _localize_material_replacements_for_draft(material_replacements, cloned_draft_path)

    summary = {
        "draft_path": cloned_draft_path,
        "draft_content_path": working_path,
        "text_replaced": 0,
        "material_replaced": 0,
        "warnings": [],
        "diagnostics": diagnostics or {},
    }
    summary["diagnostics"]["source_info_path"] = source_info_path
    summary["diagnostics"]["source_primary_path"] = source_primary_path
    summary["diagnostics"]["source_read_path"] = source_read_path
    summary["diagnostics"]["source_info_resolution"] = source_info_diag
    summary["diagnostics"]["write_info_path"] = working_path
    summary["diagnostics"]["source_draft_root"] = source_draft_root
    shell_payload, shell_payload_path = _select_best_plain_shell_payload(cloned_draft_path)
    summary["diagnostics"]["shell_payload_path"] = shell_payload_path

    summary["text_replaced"] = _replace_texts(working_payload, texts_input)
    summary["material_replaced"] = _replace_materials(working_payload, localized_material_replacements)
    summary["diagnostics"]["localized_material_replacements"] = len(localized_material_replacements or {})
    summary["diagnostics"]["rebased_internal_paths"] = _rebase_source_internal_paths(
        working_payload,
        source_draft_root,
        cloned_draft_path,
    )
    summary["diagnostics"]["hydrated_payload_materials"] = _hydrate_missing_materials_from_payload_roots(
        working_payload,
        cloned_draft_path,
    )
    summary["diagnostics"]["sanitized_missing_cover_paths"] = _sanitize_missing_cover_paths(
        working_payload,
        cloned_draft_path,
    )
    summary["diagnostics"]["nested_visual_covers_refreshed"] = _refresh_nested_combination_visual_covers(
        working_payload,
        cloned_draft_path,
    )
    summary["diagnostics"]["cover_refreshed"] = _refresh_draft_cover_from_visuals(working_payload, cloned_draft_path)

    if not summary["text_replaced"] and texts_input:
        summary["warnings"].append("no text material matched")
    if not summary["material_replaced"] and localized_material_replacements:
        summary["warnings"].append("no media material matched")

    read_mode = str((diagnostics or {}).get("read_mode") or "").strip()
    info_written_paths = _write_by_info_path_with_main_timeline_mirror(working_path, working_payload, cloned_draft_path)
    draft_content_written_paths = _write_draft_content_targets(working_payload, cloned_draft_path)
    plain_written_paths = _write_plain_payload_targets(working_payload, shell_payload, cloned_draft_path)
    written_paths = _merge_unique_paths(info_written_paths, draft_content_written_paths, plain_written_paths)
    if read_mode.startswith("encrypted"):
        summary["diagnostics"]["write_mode"] = "encrypted_source_rewritten_to_info_path_with_main_timeline_mirror_plus_draft_content_plus_plain_targets"
    else:
        summary["diagnostics"]["write_mode"] = "info_path_with_main_timeline_mirror_plus_draft_content_plus_plain_targets"
    summary["written_paths"] = list(written_paths)
    summary["diagnostics"]["frame_thumbnail_cache_cleared"] = _clear_jianying_frame_thumbnail_cache()

    return summary
