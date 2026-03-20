import os
import re
import shutil
import sys
from pathlib import Path
from cryptography.fernet import Fernet

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.utils.ffmpeg_utils import find_ffmpeg_with_source


REQUIRED_DIR_KEYS = [
    "UPLOAD_FOLDER",
    "LOG_FOLDER",
]


def record(name, ok, detail=""):
    status = "OK" if ok else "FAIL"
    suffix = f" {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    return ok


def warn(name, detail=""):
    suffix = f" {detail}" if detail else ""
    print(f"[WARN] {name}{suffix}")


def sanitize_url(value):
    if not value or "://" not in value:
        return value
    return re.sub(r"^(.*://[^:/@]+:)([^@]+)(@.*)$", r"\1***\3", value)


def check_database(app):
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    is_mysql = uri.startswith("mysql+")
    ok = record("database/backend", is_mysql, sanitize_url(uri))
    if not ok:
        warn("database/backend", "commercial packaging should use MySQL")

    try:
        with app.app_context():
            db.session.execute(text("SELECT 1"))
        record("database/connect", True)
        return ok
    except Exception as exc:
        record("database/connect", False, f"error={exc}")
        return False


def check_directories(app):
    ok = True
    seen = set()
    for key in REQUIRED_DIR_KEYS:
        raw = app.config.get(key)
        if not raw:
            ok = record(f"dir/{key}", False, "missing config") and ok
            continue
        path = Path(raw)
        seen.add(path)
        exists = path.exists() and path.is_dir()
        ok = record(f"dir/{key}", exists, str(path)) and ok

    base_dir = Path(app.root_path).parent
    extra_dirs = [
        base_dir / "user_data",
        base_dir / "app" / "uploads",
        base_dir / "logs",
    ]
    for path in extra_dirs:
        if path in seen:
            continue
        exists = path.exists() and path.is_dir()
        ok = record(f"dir/{path.name}", exists, str(path)) and ok
    return ok


def check_ffmpeg():
    ffmpeg, source = find_ffmpeg_with_source()
    if ffmpeg:
        record("ffmpeg", True, f"{source}={ffmpeg}")
        return True

    record("ffmpeg", False, "not found")
    return False


def check_secret_settings(app):
    secret = app.config.get("SECRET_KEY") or ""
    key = app.config.get("BYOK_ENCRYPTION_KEY") or ""

    secret_ok = secret != "hard-to-guess-string-change-in-production"
    record("secret_key", secret_ok, "custom" if secret_ok else "using default")

    byok_ok = bool(key)
    key_detail = "missing"
    if key:
        try:
            Fernet(key.encode("utf-8"))
            key_detail = "configured (fernet)"
        except Exception:
            key_detail = "configured (derived)"
    record("byok_key", byok_ok, key_detail)
    return secret_ok and byok_ok


def check_feature_switches(app):
    print("Feature switches:")
    print(f"  LEGACY_TEMPLATE_ENDPOINTS_ENABLED={int(bool(app.config.get('LEGACY_TEMPLATE_ENDPOINTS_ENABLED')))}")
    print(f"  DUO_FEATURES_ENABLED={int(bool(app.config.get('DUO_FEATURES_ENABLED')))}")
    print(f"  OPENCLAW_FEATURES_ENABLED={int(bool(app.config.get('OPENCLAW_FEATURES_ENABLED')))}")
    print(f"  MANGA_FEATURES_ENABLED={int(bool(app.config.get('MANGA_FEATURES_ENABLED')))}")


def check_http_mode(app):
    base_url = os.getenv("VF_BASE_URL")
    if not base_url:
        warn("http/check", "skip, set VF_BASE_URL to enable endpoint probing")
        return True

    import json
    from urllib.error import HTTPError, URLError
    from urllib.parse import urljoin
    from urllib.request import Request, urlopen

    def request(path):
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        req = Request(url, method="GET")
        try:
            with urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except HTTPError as exc:
            return exc.code, exc.read()
        except URLError as exc:
            raise exc

    checks = [
        "/api/effects/types",
    ]
    if app.config.get("DUO_FEATURES_ENABLED"):
        checks.append("/api/duo/ffmpeg/status")
    all_ok = True
    for path in checks:
        try:
            status, body = request(path)
            detail = f"status={status}"
            if body:
                try:
                    payload = json.loads(body.decode("utf-8"))
                    if isinstance(payload, dict) and "ok" in payload:
                        detail += f" ok={payload.get('ok')}"
                except Exception:
                    pass
            all_ok = record(f"http{path}", status in (200, 400, 401, 403), detail) and all_ok
        except Exception as exc:
            all_ok = record(f"http{path}", False, f"error={exc}") and all_ok
    return all_ok


def main():
    print("VideoFactory runtime self-check")
    app = create_app()

    checks = [
        check_database(app),
        check_directories(app),
        check_ffmpeg(),
        check_secret_settings(app),
    ]
    check_feature_switches(app)
    checks.append(check_http_mode(app))

    failed = [item for item in checks if not item]
    print("")
    print(f"Summary: total={len(checks)} failed={len(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
