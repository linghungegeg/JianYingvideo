import os
import threading
import time
import webbrowser
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from app.utils.runtime_paths import app_install_root, runtime_path


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def ensure_runtime_dirs(app) -> None:
    targets = {
        Path(app.config.get("UPLOAD_FOLDER") or runtime_path("uploads")),
        Path(app.config.get("LOG_FOLDER") or runtime_path("logs")),
        runtime_path("user_data"),
        runtime_path("runtime_tools"),
        runtime_path("duo_cache"),
        runtime_path("mcp_cache"),
    }
    for path in targets:
        path.mkdir(parents=True, exist_ok=True)


def validate_installer_config(app) -> None:
    if not _env_flag("VF_REQUIRE_PRODUCTION_CONFIG", False):
        return

    errors = []
    db_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    remote_auth_mode = _env_flag("VF_REMOTE_AUTH_MODE", False)
    official_site_url = str(os.getenv("VF_OFFICIAL_SITE_URL") or app.config.get("OFFICIAL_SITE_URL") or "").strip()

    if not remote_auth_mode and not db_uri.startswith("mysql+"):
        errors.append("SQLALCHEMY_DATABASE_URI must point to MySQL")
    if remote_auth_mode and not official_site_url:
        errors.append("VF_OFFICIAL_SITE_URL is required when VF_REMOTE_AUTH_MODE=1")

    secret = str(app.config.get("SECRET_KEY") or "")
    if secret == "hard-to-guess-string-change-in-production":
        errors.append("SECRET_KEY is still using the default placeholder")

    byok_key = str(app.config.get("BYOK_ENCRYPTION_KEY") or "")
    if not byok_key:
        errors.append("VIDEOFACTORY_KEY_ENCRYPTION_KEY / BYOK_ENCRYPTION_KEY is missing")

    if errors:
        joined = "; ".join(errors)
        raise RuntimeError(f"installer startup blocked: {joined}")


def run_startup_migrations(app) -> None:
    if not _env_flag("VF_AUTO_MIGRATE", True):
        return

    base_dir = app_install_root()
    alembic_ini = base_dir / "migrations" / "alembic.ini"
    script_location = base_dir / "migrations"

    cfg = AlembicConfig(str(alembic_ini))
    cfg.set_main_option("script_location", str(script_location))

    with app.app_context():
        command.upgrade(cfg, "head")


def desktop_server_options() -> dict:
    return {
        "host": os.getenv("VF_HOST", "127.0.0.1"),
        "port": _env_int("VF_PORT", 5000),
        "debug": _env_flag("VF_DEBUG", False),
        "threaded": True,
        "use_reloader": False,
    }


def desktop_target_url(server_options: dict) -> str:
    host = server_options.get("host", "127.0.0.1")
    port = server_options.get("port", 5000)
    start_path = os.getenv("VF_START_PATH", "/user").strip() or "/user"
    if not start_path.startswith("/"):
        start_path = "/" + start_path
    return f"http://{host}:{port}{start_path}"


def open_browser_later(url: str) -> None:
    if not _env_flag("VF_OPEN_BROWSER", True):
        return

    delay = max(float(os.getenv("VF_OPEN_BROWSER_DELAY", "1.2")), 0.0)

    def _open() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"open browser skipped: {exc}")

    threading.Thread(target=_open, daemon=True).start()
