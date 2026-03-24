import base64
import fnmatch
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from app.utils.helpers import extract_root_meta_draft_projects
from app.utils.runtime_paths import runtime_file_path, runtime_path


_DRAFT_CONTENT_ENCODINGS = (
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "gb18030",
    "gbk",
)
_SKIP_DIR_PREFIXES = (".cloud_cache", ".recycle_bin", ".trashed", "$recycle.bin")
_DRAFT_CANDIDATE_NAMES = (
    "draft_content.json",
    "draft_content.json.bak",
    "template.json",
    "template.json.bak",
    "template.tmp",
    "template-2.tmp",
)


def _dedupe_keep_order(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        normalized = os.path.normpath(str(item or "").strip())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _path_contains_skipped_dir(path: str) -> bool:
    normalized = os.path.normpath(str(path or "").strip())
    if not normalized:
        return False
    for part in normalized.replace("/", os.sep).split(os.sep):
        lowered = str(part or "").strip().lower()
        if lowered.startswith(_SKIP_DIR_PREFIXES):
            return True
    return False


def _filter_supported_candidates(paths: list[str]) -> list[str]:
    return [path for path in _dedupe_keep_order(paths) if not _path_contains_skipped_dir(path)]


def _resolve_lossy_windows_path(path: str) -> str:
    normalized = os.path.normpath(str(path or "").strip())
    if not normalized or os.path.exists(normalized):
        return normalized
    if "?" not in normalized:
        return normalized

    drive, tail = os.path.splitdrive(normalized)
    if not drive or not tail:
        return normalized

    current = drive + os.sep
    parts = [part for part in tail.split(os.sep) if part]
    for part in parts:
        candidate = os.path.join(current, part)
        if os.path.exists(candidate):
            current = candidate
            continue
        if "?" not in part or not os.path.isdir(current):
            return normalized
        try:
            names = os.listdir(current)
        except Exception:
            return normalized
        matches = [name for name in names if fnmatch.fnmatchcase(name, part)]
        if len(matches) != 1:
            return normalized
        current = os.path.join(current, matches[0])
    return current


def _load_json_quietly(path: str) -> Optional[Any]:
    if not path or not os.path.exists(path):
        return None
    data, err = load_json_file_with_encodings(path)
    if err is None:
        return data
    return None


def _coerce_nested_draft_payload(item: Any) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    draft = item.get("draft")
    if isinstance(draft, dict):
        return draft
    if not isinstance(draft, str):
        return None
    raw = draft.lstrip("\ufeff\x00\r\n\t ")
    if not raw or raw[:1] not in "{[":
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if isinstance(parsed, dict):
        item["draft"] = parsed
        return parsed
    return None


def _draft_payload_score(data: Any) -> tuple[int, int, int, int, int, int]:
    if not isinstance(data, dict):
        return (-1, -1, -1, -1, -1, -1)

    tracks = data.get("tracks")
    track_count = len(tracks) if isinstance(tracks, list) else 0
    segment_count = 0
    if isinstance(tracks, list):
        for track in tracks:
            if isinstance(track, dict):
                segment_count += len(track.get("segments") or [])

    materials = data.get("materials")
    if not isinstance(materials, dict):
        materials = {}

    video_count = len(materials.get("videos") or [])
    image_count = len(materials.get("images") or [])
    audio_count = len(materials.get("audios") or [])
    text_count = len(materials.get("texts") or [])
    draft_count = len(materials.get("drafts") or [])

    named_count = 0
    for key in ("videos", "images", "audios", "texts"):
        for item in materials.get(key) or []:
            if not isinstance(item, dict):
                continue
            value = (
                item.get("path")
                or item.get("file_path")
                or item.get("file_Path")
                or item.get("material_name")
                or item.get("name")
                or item.get("file_name")
                or item.get("recognize_text")
                or ""
            )
            if str(value).strip():
                named_count += 1

    replaceable_count = video_count + image_count + audio_count + text_count
    return (
        replaceable_count,
        segment_count,
        text_count,
        video_count + image_count + audio_count,
        track_count,
        named_count + draft_count,
    )


def resolve_active_draft_payload(data: Any) -> Any:
    if not isinstance(data, dict):
        return data

    best = data
    best_score = _draft_payload_score(data)
    visited: set[int] = set()

    def _walk(payload: Any) -> None:
        nonlocal best, best_score
        if not isinstance(payload, dict):
            return
        ident = id(payload)
        if ident in visited:
            return
        visited.add(ident)

        score = _draft_payload_score(payload)
        if score > best_score:
            best = payload
            best_score = score

        materials = payload.get("materials")
        if not isinstance(materials, dict):
            return
        for item in materials.get("drafts") or []:
            child = _coerce_nested_draft_payload(item)
            if isinstance(child, dict):
                _walk(child)

    _walk(data)
    return best


def _has_meaningful_draft_payload(data: Any) -> bool:
    data = resolve_active_draft_payload(data)
    if not isinstance(data, dict):
        return False
    tracks = data.get("tracks")
    if isinstance(tracks, list) and tracks:
        return True

    materials = data.get("materials")
    if not isinstance(materials, dict):
        return False
    for key in ("videos", "images", "audios", "texts"):
        items = materials.get(key)
        if isinstance(items, list) and items:
            return True
    return False


def _safe_read_head(path: str, size: int = 96) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(size)
    except Exception:
        return b""


def _detect_candidate_signature(path: str) -> dict:
    exists = os.path.exists(path)
    head = _safe_read_head(path)
    ascii_preview = "".join(chr(b) if 32 <= b <= 126 else "." for b in head[:48])
    looks_json = False
    looks_base64 = False
    try:
        text = head.decode("utf-8", errors="ignore").lstrip("\ufeff\x00\r\n\t ")
        looks_json = bool(text[:1] in "{[")
        compact = text.strip()
        if compact:
            try:
                base64.b64decode(compact, validate=True)
                looks_base64 = True
            except Exception:
                looks_base64 = False
    except Exception:
        pass
    return {
        "path": path,
        "exists": exists,
        "size": os.path.getsize(path) if exists else 0,
        "ascii_preview": ascii_preview,
        "head_hex": head.hex(),
        "looks_json": looks_json,
        "looks_base64": looks_base64,
        "is_skipped_dir": _path_contains_skipped_dir(path),
    }


def _collect_root_meta_hits(path: str) -> list[dict]:
    hits: list[dict] = []
    visited: set[str] = set()
    current = os.path.normpath(str(path or "").strip())
    for _ in range(6):
        if not current or current in visited:
            break
        visited.add(current)
        items = extract_root_meta_draft_projects(current, limit=5)
        if items:
            hits.append(
                {
                    "query_path": current,
                    "matches": [
                        {
                            "name": item.get("name") or "",
                            "path": item.get("path") or "",
                            "draft_id": item.get("draft_id") or "",
                        }
                        for item in items
                    ],
                }
            )
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    return hits


def _persist_diagnostics(diagnostics: dict) -> list[str]:
    payload = dict(diagnostics or {})
    payload["written_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    payload["cwd"] = os.getcwd()
    payload["runtime_base"] = str(runtime_path())
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    targets = [
        runtime_file_path("logs", "draft-diagnose.json"),
        runtime_file_path("logs", f"draft-diagnose-{int(time.time())}.json"),
    ]
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        targets.append(desktop / "draft-diagnose.json")

    written: list[str] = []
    seen: set[str] = set()
    for target in targets:
        norm = os.path.normpath(str(target))
        if norm in seen:
            continue
        seen.add(norm)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            written.append(str(target))
        except Exception:
            continue
    return written


def _collect_timeline_json_candidates(normalized_path: str) -> list[str]:
    candidates: list[str] = []
    timelines_root = os.path.join(normalized_path, "Timelines")
    if not os.path.isdir(timelines_root):
        return candidates

    project_path = os.path.join(timelines_root, "project.json")
    project_data = _load_json_quietly(project_path)
    if not isinstance(project_data, dict):
        project_data = _load_json_quietly(os.path.join(timelines_root, "project.json.bak"))
    timeline_ids: list[str] = []
    if isinstance(project_data, dict):
        main_timeline_id = str(project_data.get("main_timeline_id") or "").strip()
        if main_timeline_id:
            timeline_ids.append(main_timeline_id)
        for item in project_data.get("timelines", []) or []:
            if not isinstance(item, dict):
                continue
            timeline_id = str(item.get("id") or "").strip()
            if timeline_id:
                timeline_ids.append(timeline_id)

    ordered_timeline_ids = _dedupe_keep_order(timeline_ids)
    for timeline_id in ordered_timeline_ids:
        base = os.path.join(timelines_root, timeline_id)
        for name in _DRAFT_CANDIDATE_NAMES:
            candidates.append(os.path.join(base, name))

    backup_root = os.path.join(normalized_path, ".backup")
    backup_timeline_ids = ordered_timeline_ids[:]
    if os.path.isdir(backup_root) and not backup_timeline_ids:
        for name in os.listdir(backup_root):
            candidate_dir = os.path.join(backup_root, name)
            if name == "projectBackUp" or not os.path.isdir(candidate_dir):
                continue
            backup_timeline_ids.append(name)
    for timeline_id in _dedupe_keep_order(backup_timeline_ids):
        backup_dir = os.path.join(backup_root, timeline_id)
        if not os.path.isdir(backup_dir):
            continue
        for pattern in ("*.load.bak", "*.save.bak", "*.close.bak", "*.bak"):
            for path in sorted(Path(backup_dir).glob(pattern), reverse=True):
                candidates.append(str(path))

    for root, dirs, files in os.walk(timelines_root):
        dirs[:] = [name for name in dirs if not _path_contains_skipped_dir(os.path.join(root, name))]
        for name in _DRAFT_CANDIDATE_NAMES:
            if name in files:
                candidates.append(os.path.join(root, name))
    return candidates


def find_draft_content_files(template_path: str) -> list[str]:
    if not template_path:
        return []
    normalized_path = normalize_draft_project_path(template_path)
    if not normalized_path:
        return []
    if os.path.isfile(normalized_path):
        if os.path.basename(normalized_path).lower() in set(_DRAFT_CANDIDATE_NAMES):
            return _filter_supported_candidates([normalized_path]) or [normalized_path]
        normalized_path = os.path.dirname(normalized_path)

    candidates = [os.path.join(normalized_path, name) for name in _DRAFT_CANDIDATE_NAMES]
    candidates.extend(_collect_timeline_json_candidates(normalized_path))

    filtered = _filter_supported_candidates(candidates)
    return filtered or _dedupe_keep_order(candidates)


def normalize_draft_project_path(template_path: str) -> str:
    normalized_path = _resolve_lossy_windows_path(os.path.normpath(str(template_path or "").strip()))
    if not normalized_path:
        return ""

    if os.path.isfile(normalized_path):
        return os.path.dirname(normalized_path)

    direct_candidate = os.path.join(normalized_path, "draft_content.json")
    if os.path.exists(direct_candidate) and not _path_contains_skipped_dir(direct_candidate):
        return normalized_path
    if os.path.isdir(os.path.join(normalized_path, "Timelines")) and not _path_contains_skipped_dir(normalized_path):
        return normalized_path

    current = normalized_path
    for _ in range(4):
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
        candidate = os.path.join(current, "draft_content.json")
        if os.path.exists(candidate):
            return current
        if os.path.isdir(os.path.join(current, "Timelines")):
            return current

    return normalized_path


def load_json_file_with_encodings(path: str) -> tuple[Optional[Any], Optional[Exception]]:
    last_err: Optional[Exception] = None
    raw_bytes = None
    for attempt in range(8):
        try:
            with open(path, "rb") as handle:
                raw_bytes = handle.read()
            break
        except Exception as exc:
            last_err = exc
            if attempt >= 7:
                return None, exc
            time.sleep(min(0.2 * (attempt + 1), 1.0))
    if raw_bytes is None:
        return None, last_err or ValueError("empty file")
    if not raw_bytes:
        return None, ValueError("empty file")

    normalized_candidates = [raw_bytes]
    stripped_null_prefix = raw_bytes.lstrip(b"\x00")
    if stripped_null_prefix != raw_bytes:
        normalized_candidates.append(stripped_null_prefix)
    compacted_null_bytes = raw_bytes.replace(b"\x00", b"")
    if compacted_null_bytes and compacted_null_bytes != raw_bytes:
        normalized_candidates.append(compacted_null_bytes)

    for candidate_bytes in normalized_candidates:
        for encoding in _DRAFT_CONTENT_ENCODINGS:
            try:
                raw = candidate_bytes.decode(encoding).lstrip("\ufeff\x00\r\n\t ")
                if not raw or raw[0] not in "{[":
                    continue
                decoder = json.JSONDecoder()
                data, _ = decoder.raw_decode(raw)
                return data, None
            except Exception as exc:
                last_err = exc

    try:
        for candidate_bytes in normalized_candidates:
            b64_text = candidate_bytes.decode("ascii", errors="ignore").strip()
            if not b64_text:
                continue
            decoded = base64.b64decode(b64_text, validate=True)
            for encoding in _DRAFT_CONTENT_ENCODINGS:
                try:
                    text = decoded.decode(encoding).lstrip("\ufeff\x00\r\n\t ")
                    if not text or text[0] not in "{[":
                        continue
                    decoder = json.JSONDecoder()
                    data, _ = decoder.raw_decode(text)
                    return data, None
                except Exception as exc:
                    last_err = exc
    except Exception as exc:
        last_err = exc

    return None, last_err or ValueError("non-json or encrypted content")


def load_draft_content(template_path: str, logger: Optional[logging.Logger] = None) -> tuple[Optional[dict], Optional[str], dict]:
    diagnostics = {
        "raw_path": str(template_path or "").strip(),
        "normalized_path": "",
        "candidates": [],
        "candidate_details": [],
        "matched_candidate": "",
        "failures": [],
        "root_meta_hits": _collect_root_meta_hits(template_path),
    }
    if not template_path:
        diagnostics["error"] = "缺少草稿路径"
        diagnostics["diagnostic_paths"] = _persist_diagnostics(diagnostics)
        return None, "缺少草稿路径", diagnostics

    normalized_path = normalize_draft_project_path(template_path)
    diagnostics["normalized_path"] = normalized_path
    candidates = find_draft_content_files(normalized_path)
    diagnostics["candidates"] = candidates

    if logger:
        logger.info("draft_loader: raw=%s normalized=%s candidates=%s", diagnostics["raw_path"], normalized_path, candidates)

    for draft_content in candidates:
        diagnostics["candidate_details"].append(_detect_candidate_signature(draft_content))
        if not os.path.exists(draft_content):
            continue
        data, load_err = load_json_file_with_encodings(draft_content)
        if load_err is None and isinstance(data, dict):
            if not _has_meaningful_draft_payload(data):
                diagnostics["failures"].append(
                    {
                        "path": draft_content,
                        "error": "parsed empty shell payload",
                    }
                )
                if logger:
                    logger.warning("draft_loader: skip_empty_shell path=%s", draft_content)
                continue
            diagnostics["matched_candidate"] = draft_content
            diagnostics["format"] = "json"
            if logger:
                logger.info("draft_loader: loaded=%s", draft_content)
            return data, None, diagnostics
        diagnostics["failures"].append(
            {
                "path": draft_content,
                "error": str(load_err or "unknown"),
            }
        )
        if logger:
            logger.warning("draft_loader: load_failed path=%s err=%s", draft_content, load_err)

    if candidates and all(_path_contains_skipped_dir(path) for path in candidates):
        diagnostics["error"] = "当前路径命中了回收站或缓存草稿，请改选活动草稿目录"
    elif candidates and any(os.path.exists(path) for path in candidates):
        diagnostics["error"] = "解析失败: draft_content.json 读取失败"
    else:
        diagnostics["error"] = "未找到 draft_content.json"

    diagnostics["diagnostic_paths"] = _persist_diagnostics(diagnostics)
    message = diagnostics["error"]
    if diagnostics["diagnostic_paths"]:
        message = f"{message}。诊断文件: {diagnostics['diagnostic_paths'][0]}"
    return None, message, diagnostics
