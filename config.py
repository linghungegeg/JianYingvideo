import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv


def _app_install_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", "")
        if bundle_root:
            return Path(bundle_root).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _runtime_app_name() -> str:
    for key in ("VF_RUNTIME_DIR_NAME", "VF_BUILD_APP_NAME"):
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return "VideoFactoryDesktop"


def _is_writable_runtime_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_file = path / ".vf_write_probe"
        with open(probe_file, "w", encoding="utf-8") as handle:
            handle.write("ok")
        probe_file.unlink(missing_ok=True)
        probe_dir = path / ".vf_dir_probe"
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe_dir.rmdir()
        return True
    except Exception:
        return False


def _runtime_base_dir() -> Path:
    candidates = [
        os.getenv("VF_RUNTIME_BASE_DIR"),
        os.getenv("LOCALAPPDATA"),
        os.getenv("APPDATA"),
        tempfile.gettempdir(),
    ]
    for raw in candidates:
        value = str(raw or "").strip()
        if not value:
            continue
        try:
            base = Path(value).expanduser().resolve() / _runtime_app_name()
            if _is_writable_runtime_dir(base):
                return base
        except Exception:
            continue
    fallback = Path.home().resolve() / ".videofactory"
    if _is_writable_runtime_dir(fallback):
        return fallback
    local_fallback = Path.cwd().resolve() / ".videofactory-runtime"
    local_fallback.mkdir(parents=True, exist_ok=True)
    return local_fallback


def _runtime_path(*parts: str, ensure: bool = False) -> Path:
    path = _runtime_base_dir().joinpath(*parts)
    if ensure:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _runtime_file_path(*parts: str) -> Path:
    path = _runtime_path(*parts[:-1], ensure=True) if len(parts) > 1 else _runtime_base_dir()
    return path / parts[-1]


_APP_ENV_PATH = _app_install_root() / ".env"
if _APP_ENV_PATH.exists():
    load_dotenv(dotenv_path=_APP_ENV_PATH)


def _default_sqlite_uri() -> str:
    return "sqlite:///" + str(_runtime_file_path("data", "data-runtime.sqlite"))


def _normalize_sqlite_uri(value: str) -> str:
    raw = str(value or "").strip()
    if not raw.startswith("sqlite:///") or raw.startswith("sqlite:////"):
        return raw
    relative = raw[len("sqlite:///"):].strip().replace("\\", "/")
    if not relative:
        return raw
    normalized = _runtime_file_path("data", relative).resolve()
    return "sqlite:///" + str(normalized)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "hard-to-guess-string-change-in-production"
    BYOK_ENCRYPTION_KEY = os.environ.get("VIDEOFACTORY_KEY_ENCRYPTION_KEY") or os.environ.get("BYOK_ENCRYPTION_KEY")

    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("SQLALCHEMY_DATABASE_URI")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("DEV_DATABASE_URL")
        or _default_sqlite_uri()
    )
    SQLALCHEMY_DATABASE_URI = _normalize_sqlite_uri(SQLALCHEMY_DATABASE_URI)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload/log folders
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or str(_runtime_path("uploads"))
    LOG_FOLDER = os.environ.get("LOG_FOLDER") or str(_runtime_path("logs"))
    SECURITY_RUNTIME_FOLDER = os.environ.get("SECURITY_RUNTIME_FOLDER") or str(_runtime_path("logs", "security"))

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(LOG_FOLDER, exist_ok=True)
    os.makedirs(SECURITY_RUNTIME_FOLDER, exist_ok=True)

    # Redis
    REDIS_URL = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"

    # Default free quota for new users
    DEFAULT_USER_QUOTA = int(os.environ.get("DEFAULT_USER_QUOTA", "5"))

    # Legacy template-library endpoints. Keep enabled during migration, disable later.
    LEGACY_TEMPLATE_ENDPOINTS_ENABLED = os.environ.get("LEGACY_TEMPLATE_ENDPOINTS_ENABLED", "0") == "1"

    # Optional feature groups for lean desktop builds.
    DUO_FEATURES_ENABLED = os.environ.get("DUO_FEATURES_ENABLED", "1") == "1"
    OPENCLAW_FEATURES_ENABLED = os.environ.get("OPENCLAW_FEATURES_ENABLED", "1") == "1"
    MANGA_FEATURES_ENABLED = os.environ.get("MANGA_FEATURES_ENABLED", "1") == "1"
