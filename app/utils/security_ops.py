import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from flask import Request, current_app
from app.utils.runtime_paths import runtime_path

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None


_SECURITY_FILE_CACHE: dict[str, Path] = {}


def _security_root() -> Path:
    configured = ""
    try:
        configured = str(current_app.config.get("SECURITY_RUNTIME_FOLDER") or "").strip()
    except Exception:
        configured = ""
    root = Path(configured) if configured else runtime_path("logs", "security")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _fallback_security_root() -> Path:
    candidates = [
        Path(tempfile.gettempdir()).resolve() / "VideoFactoryDesktop" / "security_runtime",
        Path.home().resolve() / ".videofactory-security",
        Path.cwd().resolve() / ".videofactory-security",
    ]
    last_error = None
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            return root
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"no writable fallback security root: {last_error}")


def _candidate_security_roots() -> list[Path]:
    roots = [_security_root(), _fallback_security_root()]
    deduped = []
    seen = set()
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def _resolve_writable_security_file(filename: str) -> Path:
    cached = _SECURITY_FILE_CACHE.get(filename)
    if cached:
        return cached

    last_error = None
    for root in _candidate_security_roots():
        try:
            root.mkdir(parents=True, exist_ok=True)
            candidate = root / filename
            with open(candidate, "a+", encoding="utf-8"):
                pass
            _SECURITY_FILE_CACHE[filename] = candidate
            return candidate
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"no writable security runtime path for {filename}: {last_error}")


def _rate_limit_path() -> Path:
    return _resolve_writable_security_file("rate_limits.json")


def _audit_log_path() -> Path:
    return _resolve_writable_security_file("audit.log")


@contextmanager
def _locked_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                pass
        try:
            handle.seek(0)
            yield handle
        finally:
            handle.flush()
            os.fsync(handle.fileno())
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass


def get_request_ip(req: Request) -> str:
    forwarded = (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    real_ip = (req.headers.get("X-Real-IP") or "").strip()
    remote_addr = (req.remote_addr or "").strip()
    return forwarded or real_ip or remote_addr or "unknown"


def build_identity(*parts) -> str:
    raw = "|".join([str(item or "").strip().lower() for item in parts if str(item or "").strip()])
    if not raw:
        raw = "anonymous"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def audit_security_event(event: str, *, level: str = "info", request_obj: Request = None, user_id=None, details: dict = None) -> None:
    payload = {
        "ts": datetime.utcnow().isoformat(),
        "level": str(level or "info").lower(),
        "event": str(event or "").strip() or "unknown",
        "user_id": user_id,
        "details": details or {},
    }
    if request_obj is not None:
        payload["ip"] = get_request_ip(request_obj)
        payload["path"] = request_obj.path
        payload["method"] = request_obj.method
        payload["ua"] = (request_obj.headers.get("User-Agent") or "")[:240]
    with _locked_file(_audit_log_path()) as handle:
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def consume_rate_limit(action: str, identity: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
    limit_value = max(int(limit or 0), 1)
    window_value = max(int(window_seconds or 0), 1)
    now_ts = int(time.time())
    storage_key = f"{action}:{identity}"
    with _locked_file(_rate_limit_path()) as handle:
        try:
            raw = handle.read().strip()
            payload = json.loads(raw) if raw else {}
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        timestamps = payload.get(storage_key) or []
        valid = [
            int(item) for item in timestamps
            if str(item).isdigit() and (now_ts - int(item)) < window_value
        ]
        allowed = len(valid) < limit_value
        retry_after = 0
        if allowed:
            valid.append(now_ts)
            remaining = max(limit_value - len(valid), 0)
        else:
            earliest = min(valid) if valid else now_ts
            retry_after = max(window_value - (now_ts - earliest), 1)
            remaining = 0
        payload[storage_key] = valid
        # Drop expired buckets to keep the file bounded.
        fresh_payload = {}
        for key, items in payload.items():
            keep = [
                int(item) for item in items
                if str(item).isdigit() and (now_ts - int(item)) < window_value * 4
            ]
            if keep:
                fresh_payload[key] = keep
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(fresh_payload, ensure_ascii=False))
        return allowed, remaining, retry_after
