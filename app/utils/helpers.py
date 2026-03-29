import random
import os
import json
import uuid
import logging
import tempfile
import time
from pathlib import Path
from datetime import datetime
from flask import current_app
import sqlalchemy as sa
from app.extensions import db
from app.models.config import Config
from app.models.user_material import UserMaterial
from app.utils.crypto import encrypt_text, decrypt_text
from app.utils.runtime_paths import runtime_file_path, runtime_path


_SECURE_VALUE_PREFIX = "enc::"
_JSON_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "gbk")
_SENSITIVE_CONFIG_KEYS = {
    "token",
    "api_key",
    "api_secret",
    "secret",
    "access_token",
}
_RUNTIME_LOCAL_STATE_KEYS = {
    "user_session_token",
    "user_session_persist",
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
    "user_agreement_title": "VF_USER_AGREEMENT_TITLE",
    "user_agreement_content": "VF_USER_AGREEMENT_CONTENT",
    "privacy_agreement_title": "VF_PRIVACY_AGREEMENT_TITLE",
    "privacy_agreement_content": "VF_PRIVACY_AGREEMENT_CONTENT",
    "contact_entries": "VF_CONTACT_ENTRIES",
}
_DRAFT_ROOT_CACHE_TTL_SECONDS = 15.0
_DRAFT_LIST_CACHE_TTL_SECONDS = 15.0
_draft_root_cache = {
    "expires_at": 0.0,
    "configured_root": "",
    "value": [],
}
_draft_list_cache = {
    "expires_at": 0.0,
    "configured_root": "",
    "scan_limit": 0,
    "value": [],
}


def _ensure_config_table() -> bool:
    try:
        inspector = sa.inspect(db.engine)
        if "config" in inspector.get_table_names():
            return True
        Config.__table__.create(bind=db.engine, checkfirst=True)
        return True
    except Exception as exc:
        logging.warning("ensure config table failed: %s", exc)
        return False


def _runtime_config_fallback_file() -> Path:
    return runtime_file_path("data", "runtime-config-fallback.json")


def _read_runtime_config_fallback() -> dict:
    path = _runtime_config_fallback_file()
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logging.warning("read runtime config fallback failed: %s", exc)
        return {}


def _write_runtime_config_fallback(payload: dict) -> None:
    path = _runtime_config_fallback_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or {}, ensure_ascii=False, indent=2), encoding="utf-8")


def get_config(key, default=''):
    env_key = _SITE_SETTING_ENV_KEYS.get(str(key or "").strip())
    if env_key:
        env_value = (os.getenv(env_key) or "").strip()
        if env_value:
            return env_value
    fallback_payload = _read_runtime_config_fallback()
    try:
        _ensure_config_table()
        config = Config.query.filter_by(key=key).first()
        if config and config.value is not None:
            return config.value
    except Exception as exc:
        logging.warning("get_config fallback for %s: %s", key, exc)
    if key in fallback_payload:
        return fallback_payload.get(key) or default
    return default


def set_config(key, value):
    normalized = '' if value is None else str(value)
    try:
        _ensure_config_table()
        config = Config.query.filter_by(key=key).first()
        if config:
            config.value = normalized
        else:
            config = Config(key=key, value=normalized)
            db.session.add(config)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logging.warning("set_config fallback for %s: %s", key, exc)
    payload = _read_runtime_config_fallback()
    payload[key] = normalized
    _write_runtime_config_fallback(payload)


def set_configs(values: dict):
    items = values if isinstance(values, dict) else {}
    if not items:
        return
    normalized_items = {
        key: '' if value is None else str(value)
        for key, value in items.items()
    }
    try:
        _ensure_config_table()
        existing = {
            config.key: config
            for config in Config.query.filter(Config.key.in_(list(normalized_items.keys()))).all()
        }
        for key, value in normalized_items.items():
            config = existing.get(key)
            if config:
                config.value = value
                continue
            db.session.add(Config(key=key, value=value))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logging.warning("set_configs fallback: %s", exc)
    payload = _read_runtime_config_fallback()
    payload.update(normalized_items)
    _write_runtime_config_fallback(payload)


def get_material_folder():
    return get_config('material_folder')


def get_drafts_folder():
    return get_config('drafts_folder')


def set_drafts_folder(path):
    set_config('drafts_folder', path)


def pick_preferred_draft_root(fallback_path: str = "", *, prefer_configured: bool = True) -> str:
    configured = str(get_drafts_folder() or "").strip()
    configured_norm = os.path.normpath(configured) if configured else ""
    if prefer_configured and configured_norm and os.path.isdir(configured_norm):
        return configured_norm

    recent_drafts = list_local_drafts(limit=60, force_refresh=True)
    for item in recent_drafts:
        candidate = os.path.normpath(str((item or {}).get("root") or "").strip())
        if not candidate or candidate == configured_norm:
            continue
        if os.path.isdir(candidate):
            return candidate

    for item in discover_draft_roots(force_refresh=True):
        candidate = os.path.normpath(str((item or {}).get("path") or "").strip())
        if not candidate or candidate == configured_norm:
            continue
        if os.path.isdir(candidate):
            return candidate

    if configured_norm:
        return configured_norm

    fallback = str(fallback_path or "").strip()
    return os.path.normpath(fallback) if fallback else ""


def _existing_drive_roots() -> list[Path]:
    roots = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:/")
        try:
            if drive.exists():
                roots.append(drive)
        except Exception:
            continue
    return roots


def _discover_nested_draft_roots(max_depth: int = 3) -> list[str]:
    roots: list[str] = []
    seen: set[str] = set()
    target_names = {
        "com.lveditor.draft",
        "jianyingpro drafts",
        "capcut drafts",
        "剪映草稿",
        "草稿",
    }
    skip_names = {
        "$recycle.bin",
        "system volume information",
        ".git",
        "node_modules",
        "__pycache__",
    }

    def _remember(path: Path) -> None:
        norm = os.path.normpath(str(path))
        if norm and norm not in seen:
            seen.add(norm)
            roots.append(norm)

    for drive in _existing_drive_roots():
        queue: list[tuple[Path, int]] = [(drive, 0)]
        visited: set[str] = set()
        while queue:
            current, depth = queue.pop(0)
            norm = os.path.normpath(str(current))
            if norm in visited:
                continue
            visited.add(norm)

            name = current.name.strip().lower()
            if name in skip_names:
                continue
            if name in target_names:
                _remember(current)
                continue
            if depth >= max_depth:
                continue
            try:
                children = [child for child in current.iterdir() if child.is_dir()]
            except Exception:
                continue
            for child in children:
                child_name = child.name.strip().lower()
                if child_name in skip_names:
                    continue
                if depth >= 2 and child_name not in target_names:
                    looks_related = (
                        "jianying" in child_name
                        or "capcut" in child_name
                        or "draft" in child_name
                        or "剪映" in child.name
                        or "草稿" in child.name
                    )
                    if not looks_related:
                        continue
                queue.append((child, depth + 1))
    return roots


def _scan_drive_for_draft_projects(max_depth: int = 6, max_hits: int = 200) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    skip_names = {
        "$recycle.bin",
        "system volume information",
        ".git",
        "node_modules",
        "__pycache__",
    }
    skip_prefixes = (".cloud_cache", ".recycle_bin", ".trashed", "$recycle.bin")

    def _contains_skipped_part(path: Path) -> bool:
        for part in path.parts:
            lowered = str(part or "").strip().lower()
            if lowered.startswith(skip_prefixes):
                return True
        return False

    def _should_descend(path: Path, depth: int) -> bool:
        if _contains_skipped_part(path):
            return False
        if depth <= 1:
            return True
        name = path.name.strip().lower()
        return (
            "jianying" in name
            or "capcut" in name
            or "draft" in name
            or "剪映" in path.name
            or "草稿" in path.name
        )

    for drive in _existing_drive_roots():
        queue: list[tuple[Path, int]] = [(drive, 0)]
        visited: set[str] = set()
        while queue and len(results) < max_hits:
            current, depth = queue.pop(0)
            norm = os.path.normpath(str(current))
            if norm in visited:
                continue
            visited.add(norm)

            lowered = current.name.strip().lower()
            if lowered in skip_names or _contains_skipped_part(current):
                continue
            try:
                draft_file = current / "draft_content.json"
                if draft_file.exists():
                    project_path = norm
                    if project_path not in seen:
                        seen.add(project_path)
                        results.append(
                            {
                                "name": os.path.basename(project_path.rstrip("\\/")),
                                "path": project_path,
                                "root": os.path.normpath(str(current.parent)),
                                "source": "全盘扫描",
                                "updated_at": datetime.fromtimestamp(draft_file.stat().st_mtime).isoformat(),
                            }
                        )
                    continue
            except Exception:
                continue
            if depth >= max_depth:
                continue
            try:
                children = [child for child in current.iterdir() if child.is_dir()]
            except Exception:
                continue
            for child in children:
                child_name = child.name.strip().lower()
                if child_name in skip_names:
                    continue
                if not _should_descend(child, depth):
                    continue
                queue.append((child, depth + 1))
    return results


def _read_recorded_draft_roots() -> list[str]:
    roots: list[str] = []
    seen: set[str] = set()
    config_candidates = []
    home = Path.home()

    for base in (
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("APPDATA"),
        str(home / "AppData" / "Local"),
        str(home / "AppData" / "Roaming"),
    ):
        if not base:
            continue
        base_path = Path(base)
        config_candidates.extend(
            [
                base_path / "JianyingPro" / "JianyingPro Drafts.json",
                base_path / "CapCut" / "CapCut Drafts.json",
                base_path / "CapCut International" / "CapCut Drafts.json",
            ]
        )

    for path in config_candidates:
        try:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        for key in ("draft_root_path", "drafts_root_path", "root_path", "folder", "path"):
            value = str(payload.get(key) or "").strip()
            norm = os.path.normpath(value)
            if norm and norm not in seen:
                seen.add(norm)
                roots.append(norm)
    return roots


def _load_json_file(path: Path):
    for encoding in _JSON_ENCODINGS:
        try:
            return json.loads(path.read_text(encoding=encoding))
        except Exception:
            continue
    return None


def _draft_timestamp_to_epoch(value) -> float:
    try:
        number = float(value or 0)
    except Exception:
        return 0.0
    if number <= 0:
        return 0.0
    if number > 1_000_000_000_000_000:
        return number / 1_000_000.0
    if number > 1_000_000_000_000:
        return number / 1000.0
    return number


def _discover_root_meta_files(path: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def _remember(candidate: Path) -> None:
        norm = os.path.normpath(str(candidate))
        if norm and norm not in seen and candidate.exists():
            seen.add(norm)
            candidates.append(candidate)

    if path.is_file() and path.name.lower() == "root_meta_info.json":
        _remember(path)
        return candidates

    direct_root_meta = path / "root_meta_info.json"
    if direct_root_meta.exists():
        _remember(direct_root_meta)

    if not path.is_dir():
        return candidates

    try:
        children = [child for child in path.iterdir() if child.is_dir()]
    except Exception:
        return candidates

    for child in children:
        lowered = child.name.strip().lower()
        if "draft" not in lowered and "lveditor" not in lowered:
            continue
        root_meta = child / "root_meta_info.json"
        if root_meta.exists():
            _remember(root_meta)
    return candidates


def extract_root_meta_draft_projects(path: str, limit: int | None = None) -> list[dict]:
    normalized = os.path.normpath(str(path or "").strip())
    if not normalized:
        return []

    root_meta_files = _discover_root_meta_files(Path(normalized))
    if not root_meta_files:
        return []

    results: list[dict] = []
    seen: set[str] = set()

    for root_meta_path in root_meta_files:
        payload = _load_json_file(root_meta_path)
        if not isinstance(payload, dict):
            continue
        entries = payload.get("all_draft_store") or []
        if not isinstance(entries, list):
            continue

        for item in entries:
            if not isinstance(item, dict):
                continue
            if bool(item.get("draft_is_invisible")):
                continue
            if str(item.get("tm_draft_removed") or "").strip() not in {"", "0", "0.0"}:
                continue

            path_candidates = []
            for raw_value in (
                item.get("draft_fold_path"),
                os.path.dirname(str(item.get("draft_json_file") or "").strip()),
            ):
                value = str(raw_value or "").strip()
                if value:
                    path_candidates.append(value)

            root_value = str(item.get("draft_root_path") or "").strip()
            name_value = str(item.get("draft_name") or "").strip()
            if root_value and name_value:
                path_candidates.append(os.path.join(root_value, name_value))

            draft_path = ""
            for raw_candidate in path_candidates:
                candidate = os.path.normpath(raw_candidate.replace("/", os.sep))
                if not candidate:
                    continue
                if os.path.isfile(candidate):
                    candidate = os.path.dirname(candidate)
                if os.path.exists(os.path.join(candidate, "draft_content.json")):
                    draft_path = candidate
                    break
            if not draft_path or draft_path in seen:
                continue

            seen.add(draft_path)
            updated_epoch = max(
                _draft_timestamp_to_epoch(item.get("tm_draft_modified")),
                _draft_timestamp_to_epoch(item.get("tm_draft_create")),
            )
            if updated_epoch <= 0:
                try:
                    updated_epoch = os.path.getmtime(os.path.join(draft_path, "draft_content.json"))
                except Exception:
                    updated_epoch = 0.0
            updated_at = datetime.fromtimestamp(updated_epoch).isoformat() if updated_epoch > 0 else ""
            results.append(
                {
                    "name": name_value or os.path.basename(draft_path.rstrip("\\/")),
                    "path": draft_path,
                    "root": os.path.normpath(root_value) if root_value else os.path.normpath(os.path.dirname(draft_path)),
                    "draft_id": str(item.get("draft_id") or "").strip(),
                    "updated_at": updated_at,
                }
            )

    results.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    if isinstance(limit, int) and limit > 0:
        return results[:limit]
    return results


def _candidate_draft_roots() -> list[str]:
    roots = []
    configured = str(get_drafts_folder() or "").strip()
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

    # common manual folders on any local drive, not just C/D/E
    drive_suffixes = [
        ("JianyingPro Drafts",),
        ("CapCut Drafts",),
        ("jycaogao", "JianyingPro Drafts"),
        ("Videos", "JianyingPro Drafts"),
        ("Videos", "CapCut Drafts"),
    ]
    for drive in _existing_drive_roots():
        for suffix in drive_suffixes:
            roots.append(str(drive.joinpath(*suffix)))

    roots.extend(
        [
            str(home / "Videos" / "JianyingPro Drafts"),
            str(home / "Videos" / "CapCut Drafts"),
        ]
    )
    roots.extend(_read_recorded_draft_roots())

    existing_known_roots = []
    seen_existing = set()
    for item in roots:
        norm = os.path.normpath(str(item).strip())
        if not norm or norm in seen_existing:
            continue
        seen_existing.add(norm)
        if os.path.isdir(norm):
            existing_known_roots.append(norm)
    if not existing_known_roots:
        roots.extend(_discover_nested_draft_roots(max_depth=4))

    deduped = []
    seen = set()
    for item in roots:
        norm = os.path.normpath(str(item).strip())
        if not norm:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(norm)
    return deduped


def _draft_cache_key() -> str:
    return os.path.normpath(str(get_drafts_folder() or "").strip())


def discover_draft_roots(force_refresh: bool = False) -> list[dict]:
    cache_key = _draft_cache_key()
    now = time.time()
    if (
        not force_refresh
        and _draft_root_cache["value"]
        and _draft_root_cache["configured_root"] == cache_key
        and float(_draft_root_cache["expires_at"] or 0.0) > now
    ):
        return [dict(item) for item in _draft_root_cache["value"]]

    items = []
    for root in _candidate_draft_roots():
        exists = os.path.isdir(root)
        label = "自定义目录" if os.path.normpath(root) == os.path.normpath(get_drafts_folder() or "") else (
            "剪映国际版" if "capcut" in root.lower() else "剪映"
        )
        items.append({"path": root, "label": label, "exists": exists})
    _draft_root_cache["configured_root"] = cache_key
    _draft_root_cache["expires_at"] = now + _DRAFT_ROOT_CACHE_TTL_SECONDS
    _draft_root_cache["value"] = [dict(item) for item in items]
    return items


def list_local_drafts(limit: int = 30, force_refresh: bool = False) -> list[dict]:
    limit = max(1, int(limit or 30))
    cache_key = _draft_cache_key()
    now = time.time()
    if (
        not force_refresh
        and _draft_list_cache["value"]
        and _draft_list_cache["configured_root"] == cache_key
        and int(_draft_list_cache["scan_limit"] or 0) >= limit
        and float(_draft_list_cache["expires_at"] or 0.0) > now
    ):
        return [dict(item) for item in _draft_list_cache["value"][:limit]]

    drafts = []
    seen = set()
    scan_limit = max(limit, 100)
    skip_prefixes = (".cloud_cache", ".recycle_bin", ".trashed", "$recycle.bin")

    def _should_skip_dir(name: str) -> bool:
        lowered = str(name or "").strip().lower()
        return not lowered or lowered.startswith(skip_prefixes)

    def _iter_draft_directories(root: str, max_depth: int = 6):
        base = Path(root)
        if not base.exists() or not base.is_dir():
            return

        walked = set()

        def _visit(path: Path, depth: int):
            if _should_skip_dir(path.name):
                return
            norm = os.path.normpath(str(path))
            if norm in walked:
                return
            walked.add(norm)
            if (path / "draft_content.json").exists():
                yield norm
                return
            if depth >= max_depth:
                return
            try:
                children = [child for child in path.iterdir() if child.is_dir()]
            except Exception:
                return
            for child in children:
                yield from _visit(child, depth + 1)

        yield from _visit(base, 0)

    for root_info in discover_draft_roots(force_refresh=force_refresh):
        root = root_info["path"]
        if not root_info["exists"]:
            continue
        try:
            metadata_drafts = extract_root_meta_draft_projects(root, limit=max(scan_limit * 3, 60))
            for item in metadata_drafts:
                norm = os.path.normpath(str(item.get("path") or "").strip())
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                drafts.append(
                    {
                        "name": item.get("name") or os.path.basename(norm.rstrip("\\/")),
                        "path": norm,
                        "root": item.get("root") or root,
                        "source": root_info["label"],
                        "updated_at": item.get("updated_at") or "",
                    }
                )
            if metadata_drafts:
                continue
            for norm in _iter_draft_directories(root, max_depth=6):
                if norm in seen:
                    continue
                seen.add(norm)
                stat = os.stat(norm)
                drafts.append(
                    {
                        "name": os.path.basename(norm.rstrip("\\/")),
                        "path": norm,
                        "root": root,
                        "source": root_info["label"],
                        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
        except Exception:
            continue
    if not drafts:
        drafts.extend(_scan_drive_for_draft_projects(max_depth=6, max_hits=max(scan_limit * 3, 60)))
    drafts.sort(key=lambda item: item["updated_at"], reverse=True)
    cached_items = drafts[:scan_limit]
    _draft_list_cache["configured_root"] = cache_key
    _draft_list_cache["scan_limit"] = scan_limit
    _draft_list_cache["expires_at"] = now + _DRAFT_LIST_CACHE_TTL_SECONDS
    _draft_list_cache["value"] = [dict(item) for item in cached_items]
    return cached_items[:limit]


def _legacy_candidate_draft_roots() -> list[str]:
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


def _legacy_discover_draft_roots() -> list[dict]:
    items = []
    for root in _candidate_draft_roots():
        exists = os.path.isdir(root)
        label = "自定义目录" if os.path.normpath(root) == os.path.normpath(get_drafts_folder() or "") else (
            "剪映国际版" if "capcut" in root.lower() else "剪映"
        )
        items.append({"path": root, "label": label, "exists": exists})
    return items


def _legacy_list_local_drafts(limit: int = 30) -> list[dict]:
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
    user_agreement_title = get_config('user_agreement_title', '用户协议') or '用户协议'
    user_agreement_content = get_config(
        'user_agreement_content',
        '欢迎使用本服务。继续登录或注册即表示你已阅读并同意平台的服务规则、会员机制、次数结算与内容规范。'
    ) or '欢迎使用本服务。继续登录或注册即表示你已阅读并同意平台的服务规则、会员机制、次数结算与内容规范。'
    privacy_agreement_title = get_config('privacy_agreement_title', '隐私协议') or '隐私协议'
    privacy_agreement_content = get_config(
        'privacy_agreement_content',
        '我们仅在提供账号登录、授权验证、次数结算、客服联系与必要安全审计时处理你的必要信息，并采取合理措施保护数据安全。'
    ) or '我们仅在提供账号登录、授权验证、次数结算、客服联系与必要安全审计时处理你的必要信息，并采取合理措施保护数据安全。'
    try:
        contact_entries = json.loads(get_config('contact_entries', '[]') or '[]')
        if not isinstance(contact_entries, list):
            contact_entries = []
    except Exception:
        contact_entries = []
    contact_entries = [str(item or '').strip() for item in contact_entries if str(item or '').strip()]
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
        'user_agreement_title': user_agreement_title,
        'user_agreement_content': user_agreement_content,
        'privacy_agreement_title': privacy_agreement_title,
        'privacy_agreement_content': privacy_agreement_content,
        'contact_entries': contact_entries,
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
        'agreements': {
            'user': {
                'title': user_agreement_title,
                'content': user_agreement_content,
            },
            'privacy': {
                'title': privacy_agreement_title,
                'content': privacy_agreement_content,
            },
        },
        'contacts': contact_entries,
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


def cleanup_legacy_runtime_session_state() -> dict:
    payload = _read_runtime_local_state_file()
    changed = False

    if payload.get("user_session_token") and not payload.get("user_session_persist"):
        payload.pop("user_session_token", None)
        changed = True

    if payload.get("admin_session_token") == "":
        payload.pop("admin_session_token", None)
        changed = True

    if changed:
        _write_runtime_local_state_file(payload)
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
