import os
import shutil
from typing import Callable, Optional


def copy_into_cache_target(source_path: str, target_path: str, image_exts: set[str]) -> str:
    source = str(source_path or "").strip()
    target = str(target_path or "").strip()
    if not source or not target or not os.path.isfile(source):
        return ""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    source_ext = os.path.splitext(source)[1].lower()
    target_ext = os.path.splitext(target)[1].lower()
    if source_ext != target_ext and source_ext in image_exts and target_ext in image_exts:
        try:
            from PIL import Image

            with Image.open(source) as image:
                image.save(target)
            shutil.copystat(source, target)
            return target
        except Exception:
            return ""
    shutil.copy2(source, target)
    return target


def path_requires_preserved_image_target_name(path_value: str, image_exts: set[str]) -> bool:
    raw = str(path_value or "").strip()
    if not raw:
        return False
    base_name = os.path.basename(raw)
    ext = os.path.splitext(base_name)[1].lower()
    if ext not in image_exts:
        return False
    return "##_material_placeholder_" in base_name


def path_is_selfbuilt_draft_placeholder(path_value: str) -> bool:
    raw = str(path_value or "").strip()
    return raw.startswith("##_draftpath_placeholder_")


def collect_ordered_replacement_paths(
    material_replacements,
    expected_kind: str,
    detect_media_kind: Callable[[str], str],
    normalize_abs_path: Callable[[str], str],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    if not isinstance(material_replacements, dict):
        return ordered
    for _key, value in material_replacements.items():
        path_text = str(value or "").strip()
        if not path_text:
            continue
        media_kind = detect_media_kind(path_text)
        if expected_kind and media_kind != expected_kind:
            continue
        norm = normalize_abs_path(path_text) if os.path.isabs(path_text) else path_text.replace("\\", "/")
        if norm in seen:
            continue
        seen.add(norm)
        ordered.append(path_text)
    return ordered


def build_selfbuilt_visual_override_map(
    current_payload: dict,
    material_replacements,
    collect_referenced_material_ids: Callable[[dict, str], set[str]],
    detect_media_kind: Callable[[str], str],
    normalize_abs_path: Callable[[str], str],
) -> dict[str, str]:
    if not isinstance(current_payload, dict):
        return {}
    materials = current_payload.get("materials") or {}
    if not isinstance(materials, dict):
        return {}

    ordered_image_overrides = collect_ordered_replacement_paths(
        material_replacements,
        "images",
        detect_media_kind,
        normalize_abs_path,
    )
    if not ordered_image_overrides:
        return {}

    referenced_video_ids = collect_referenced_material_ids(current_payload, "video")
    if not referenced_video_ids:
        return {}

    candidates: list[dict] = []
    for media_type in ("videos", "images"):
        for item in materials.get(media_type) or []:
            if not isinstance(item, dict):
                continue
            material_id = str(item.get("id") or "").strip()
            if material_id and material_id not in referenced_video_ids:
                continue
            current_path = str(item.get("path") or item.get("file_path") or "").strip()
            if not path_is_selfbuilt_draft_placeholder(current_path):
                continue
            material_kind = str(item.get("type") or "").strip().lower()
            if media_type == "images" or material_kind in {"photo", "image", "gif"}:
                candidates.append(item)

    if not candidates or len(ordered_image_overrides) < len(candidates):
        return {}

    override_map: dict[str, str] = {}
    for item, override_path in zip(candidates, ordered_image_overrides):
        material_id = str(item.get("id") or "").strip()
        if material_id:
            override_map[material_id] = override_path
    return override_map


def collect_selfbuilt_visual_material_ids(
    current_payload: dict,
    collect_referenced_material_ids: Callable[[dict, str], set[str]],
) -> set[str]:
    result: set[str] = set()
    if not isinstance(current_payload, dict):
        return result
    materials = current_payload.get("materials") or {}
    if not isinstance(materials, dict):
        return result
    referenced_video_ids = collect_referenced_material_ids(current_payload, "video")
    if not referenced_video_ids:
        return result
    for media_type in ("videos", "images"):
        for item in materials.get(media_type) or []:
            if not isinstance(item, dict):
                continue
            material_id = str(item.get("id") or "").strip()
            if material_id and material_id not in referenced_video_ids:
                continue
            current_path = str(item.get("path") or item.get("file_path") or "").strip()
            if not path_is_selfbuilt_draft_placeholder(current_path):
                continue
            material_kind = str(item.get("type") or "").strip().lower()
            if media_type == "images" or material_kind in {"photo", "image", "gif"}:
                if material_id:
                    result.add(material_id)
    return result


def collect_official_placeholder_visual_material_ids(
    current_payload: dict,
    collect_referenced_material_ids: Callable[[dict, str], set[str]],
    image_exts: set[str],
) -> set[str]:
    result: set[str] = set()
    if not isinstance(current_payload, dict):
        return result
    materials = current_payload.get("materials") or {}
    if not isinstance(materials, dict):
        return result
    referenced_video_ids = collect_referenced_material_ids(current_payload, "video")
    if not referenced_video_ids:
        return result
    for media_type in ("videos", "images"):
        for item in materials.get(media_type) or []:
            if not isinstance(item, dict):
                continue
            material_id = str(item.get("id") or "").strip()
            if not material_id or material_id not in referenced_video_ids:
                continue
            current_path = str(item.get("path") or item.get("file_path") or "").strip()
            if not path_requires_preserved_image_target_name(current_path, image_exts):
                continue
            material_kind = str(item.get("type") or "").strip().lower()
            if media_type == "images" or material_kind in {"photo", "image", "gif"}:
                result.add(material_id)
    return result


def payload_has_selfbuilt_draftpath_semantics(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    materials = payload.get("materials") or {}
    if not isinstance(materials, dict):
        return False
    for media_type in ("videos", "images"):
        for item in materials.get(media_type) or []:
            if not isinstance(item, dict):
                continue
            for key in ("path", "file_path"):
                value = str(item.get(key) or "").strip()
                if path_is_selfbuilt_draft_placeholder(value):
                    return True
    return False


def classify_draft_strategy(
    payload: dict,
    payload_has_official_nested_cache_semantics: Callable[[dict], bool],
) -> dict:
    if payload_has_official_nested_cache_semantics(payload):
        return {
            "draft_kind": "official_nested_template_draft",
            "replacement_strategy": "official_minimal_rewrite",
        }
    if payload_has_selfbuilt_draftpath_semantics(payload):
        return {
            "draft_kind": "selfbuilt_placeholder_draft",
            "replacement_strategy": "selfbuilt_grouped_placeholder_rewrite",
        }
    return {
        "draft_kind": "plain_or_unknown_draft",
        "replacement_strategy": "generic_minimal_rewrite",
    }


def sync_selfbuilt_plain_visual_materials_from_active(target_payload: dict, active_payload: dict) -> int:
    if not isinstance(target_payload, dict) or not isinstance(active_payload, dict):
        return 0
    if not payload_has_selfbuilt_draftpath_semantics(active_payload):
        return 0

    active_materials = active_payload.get("materials") or {}
    target_materials = target_payload.get("materials") or {}
    if not isinstance(active_materials, dict) or not isinstance(target_materials, dict):
        return 0

    active_map: dict[str, dict] = {}
    for media_type in ("videos", "images"):
        for item in active_materials.get(media_type) or []:
            if not isinstance(item, dict):
                continue
            material_id = str(item.get("id") or "").strip()
            path_value = str(item.get("path") or item.get("file_path") or "").strip()
            if not material_id or not path_is_selfbuilt_draft_placeholder(path_value):
                continue
            marker_end = path_value.find("##/")
            rel_path = path_value[marker_end + 3 :] if marker_end >= 0 else path_value
            active_map[material_id] = {
                "path": rel_path.replace("\\", "/"),
                "width": item.get("width"),
                "height": item.get("height"),
                "duration": item.get("duration"),
                "material_name": item.get("material_name"),
                "name": item.get("name"),
            }

    if not active_map:
        return 0

    changed = 0
    for media_type in ("videos", "images"):
        for item in target_materials.get(media_type) or []:
            if not isinstance(item, dict):
                continue
            material_id = str(item.get("id") or "").strip()
            active_item = active_map.get(material_id)
            if not active_item:
                continue
            if item.get("path") != active_item["path"]:
                item["path"] = active_item["path"]
                changed += 1
            if "file_path" in item and item.get("file_path") != active_item["path"]:
                item["file_path"] = active_item["path"]
                changed += 1
            width = active_item.get("width")
            height = active_item.get("height")
            duration = active_item.get("duration")
            if isinstance(width, int) and width > 0 and item.get("width") != width:
                item["width"] = width
                changed += 1
            if isinstance(height, int) and height > 0 and item.get("height") != height:
                item["height"] = height
                changed += 1
            if isinstance(duration, int) and duration > 0 and item.get("duration") != duration:
                item["duration"] = duration
                changed += 1
            if "material_name" in item and item.get("material_name") != (active_item.get("material_name") or ""):
                item["material_name"] = active_item.get("material_name") or ""
                changed += 1
            if "name" in item and item.get("name") != (active_item.get("name") or ""):
                item["name"] = active_item.get("name") or ""
                changed += 1
    return changed


def apply_draft_placeholder_material_override(
    current_path: str,
    override_path: str,
    cloned_draft_path: str,
    image_exts: set[str],
) -> str:
    raw_current = str(current_path or "").strip()
    raw_override = str(override_path or "").strip()
    if not raw_current or os.path.isabs(raw_current) or not os.path.isfile(raw_override):
        return raw_override
    prefix = ""
    tail = raw_current.replace("\\", "/")
    if raw_current.startswith("##_draftpath_placeholder_"):
        marker_end = raw_current.find("##/")
        if marker_end < 0:
            return raw_override
        prefix = raw_current[: marker_end + 3]
        tail = raw_current[marker_end + 3 :].replace("\\", "/")
    rel_dir = os.path.dirname(tail).replace("\\", "/")
    preserve_target_name = path_requires_preserved_image_target_name(raw_current, image_exts)
    base_name = os.path.basename(tail) if preserve_target_name else (os.path.basename(raw_override) or os.path.basename(tail))
    if not rel_dir or not base_name:
        return raw_override
    target_abs = os.path.join(cloned_draft_path, rel_dir.replace("/", os.sep), base_name)
    try:
        written = copy_into_cache_target(raw_override, target_abs, image_exts)
        if not written:
            return raw_override
    except Exception:
        return raw_override
    rel_path = f"{rel_dir}/{base_name}"
    return f"{prefix}{rel_path}" if prefix else rel_path


def clamp_replaced_segment_source_timeranges(
    payload: dict,
    material_durations: dict[str, int],
    safe_int: Callable[[object, int], int],
) -> int:
    if not isinstance(payload, dict) or not isinstance(material_durations, dict) or not material_durations:
        return 0
    tracks = payload.get("tracks") or []
    if not isinstance(tracks, list):
        return 0

    adjusted = 0
    for track in tracks:
        if not isinstance(track, dict):
            continue
        track_type = str(track.get("type") or "").strip().lower()
        if track_type not in ("audio", "video"):
            continue
        segments = track.get("segments") or []
        if not isinstance(segments, list):
            continue
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            material_id = str(seg.get("material_id") or "").strip()
            material_duration = material_durations.get(material_id)
            if not isinstance(material_duration, int) or material_duration <= 0:
                continue
            sr = seg.get("source_timerange")
            if not isinstance(sr, dict):
                continue
            start_us = max(0, safe_int(sr.get("start"), 0))
            duration_us = max(0, safe_int(sr.get("duration"), 0))
            if start_us < material_duration and start_us + duration_us <= material_duration:
                continue

            if start_us >= material_duration:
                start_us = max(0, material_duration - 1)
                new_duration_us = 1
            else:
                new_duration_us = max(1, material_duration - start_us)

            sr["start"] = start_us
            sr["duration"] = new_duration_us

            tr = seg.get("target_timerange")
            if isinstance(tr, dict):
                current_target_duration = max(0, safe_int(tr.get("duration"), 0))
                if current_target_duration <= 0 or new_duration_us < current_target_duration:
                    tr["duration"] = new_duration_us
            adjusted += 1
    return adjusted


def replace_materials(
    payload: dict,
    material_replacements,
    *,
    cloned_draft_path: str = "",
    image_exts: set[str],
    detect_media_kind: Callable[[str], str],
    normalize_abs_path: Callable[[str], str],
    collect_referenced_material_ids: Callable[[dict, str], set[str]],
    material_name_is_excluded: Callable[[dict], bool],
    lookup_material_override: Callable[[dict, Optional[str], Optional[str], Optional[str]], Optional[str]],
    parse_replacement_media_info: Callable[[str], dict],
    safe_int: Callable[[object, int], int],
) -> int:
    if not isinstance(material_replacements, dict) or not material_replacements:
        return 0

    replaced = 0
    iter_payloads = [payload]
    if isinstance(payload, dict):
        stack = [payload]
        seen_ids: set[int] = set()
        iter_payloads = []
        while stack:
            current = stack.pop()
            if not isinstance(current, dict):
                continue
            marker = id(current)
            if marker in seen_ids:
                continue
            seen_ids.add(marker)
            iter_payloads.append(current)
            materials = current.get("materials")
            if not isinstance(materials, dict):
                continue
            for item in materials.get("drafts") or []:
                if not isinstance(item, dict):
                    continue
                nested = item.get("draft")
                if isinstance(nested, dict):
                    stack.append(nested)

    for current_payload in iter_payloads:
        materials = current_payload.get("materials", {})
        if not isinstance(materials, dict):
            continue
        referenced_video_ids = collect_referenced_material_ids(current_payload, "video")
        referenced_audio_ids = collect_referenced_material_ids(current_payload, "audio")
        selfbuilt_visual_material_ids = collect_selfbuilt_visual_material_ids(
            current_payload,
            collect_referenced_material_ids,
        )
        official_placeholder_visual_ids = collect_official_placeholder_visual_material_ids(
            current_payload,
            collect_referenced_material_ids,
            image_exts,
        )
        selfbuilt_visual_override_map = build_selfbuilt_visual_override_map(
            current_payload,
            material_replacements,
            collect_referenced_material_ids,
            detect_media_kind,
            normalize_abs_path,
        )
        replaced_durations: dict[str, int] = {}
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
                    if material_name_is_excluded(item):
                        continue
                    current_path = item.get("path") or item.get("file_path") or ""
                    material_kind = str(item.get("type") or "").strip().lower()
                    if (
                        official_placeholder_visual_ids
                        and material_id
                        and material_id not in official_placeholder_visual_ids
                        and (
                            media_type == "images"
                            or material_kind in {"photo", "image", "gif"}
                        )
                    ):
                        continue
                elif media_type == "audios":
                    if material_id and material_id not in referenced_audio_ids:
                        continue
                    current_path = item.get("path") or item.get("file_path") or ""
                    material_kind = str(item.get("type") or "").strip().lower()
                else:
                    current_path = item.get("path") or item.get("file_path") or ""
                    material_kind = str(item.get("type") or "").strip().lower()
                override_path = ""
                if material_id and material_id in selfbuilt_visual_override_map:
                    override_path = selfbuilt_visual_override_map.get(material_id) or ""
                elif material_id and material_id in selfbuilt_visual_material_ids:
                    continue
                if not override_path:
                    override_path = lookup_material_override(
                        material_replacements,
                        material_name=item.get("material_name") or item.get("name"),
                        material_path=current_path,
                        material_id=material_id,
                    )
                if not override_path:
                    continue
                override_kind = detect_media_kind(override_path)
                if material_kind in ("video",):
                    current_kind = "videos"
                elif material_kind in ("photo", "gif", "image"):
                    current_kind = "images"
                elif material_kind in ("audio",):
                    current_kind = "audios"
                else:
                    current_kind = detect_media_kind(current_path) or media_type
                if override_kind and current_kind and override_kind != current_kind:
                    continue
                metadata_source_path = override_path
                override_path = apply_draft_placeholder_material_override(
                    current_path,
                    override_path,
                    cloned_draft_path,
                    image_exts,
                )
                item["path"] = override_path
                if "file_path" in item:
                    item["file_path"] = override_path
                base_name = os.path.basename(override_path)
                preserve_blank_names = path_is_selfbuilt_draft_placeholder(current_path)
                if base_name and not preserve_blank_names:
                    if "material_name" in item:
                        item["material_name"] = base_name
                    if "name" in item:
                        item["name"] = base_name
                media_info = parse_replacement_media_info(metadata_source_path)
                width = media_info.get("width")
                height = media_info.get("height")
                duration = media_info.get("duration")
                if isinstance(width, int) and width > 0:
                    item["width"] = width
                if isinstance(height, int) and height > 0:
                    item["height"] = height
                if isinstance(duration, (int, float)) and duration > 0:
                    duration_us = int(round(float(duration) * 1000000))
                    item["duration"] = duration_us
                    if material_id and media_type in ("videos", "audios"):
                        replaced_durations[material_id] = duration_us
                replaced += 1
        if replaced_durations:
            clamp_replaced_segment_source_timeranges(
                current_payload,
                replaced_durations,
                safe_int,
            )
    return replaced
