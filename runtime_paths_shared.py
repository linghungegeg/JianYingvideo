import os
import sys
import tempfile
from pathlib import Path


DEFAULT_RUNTIME_APP_NAME = "VideoFactoryDesktop"
_RUNTIME_BASE_DIR_CACHE = None


def runtime_app_name() -> str:
    for key in ("VF_RUNTIME_DIR_NAME", "VF_BUILD_APP_NAME"):
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return DEFAULT_RUNTIME_APP_NAME


def app_install_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", "")
        if bundle_root:
            return Path(bundle_root).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def app_resource_path(*parts: str) -> Path:
    return app_install_root().joinpath(*parts)


def is_writable_runtime_dir(path: Path) -> bool:
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


def runtime_base_dir() -> Path:
    global _RUNTIME_BASE_DIR_CACHE
    if isinstance(_RUNTIME_BASE_DIR_CACHE, Path) and is_writable_runtime_dir(_RUNTIME_BASE_DIR_CACHE):
        return _RUNTIME_BASE_DIR_CACHE

    explicit_base = str(os.getenv("VF_RUNTIME_BASE_DIR") or "").strip()
    if explicit_base:
        try:
            base = Path(explicit_base).expanduser().resolve()
            if is_writable_runtime_dir(base):
                _RUNTIME_BASE_DIR_CACHE = base
                return base
        except Exception:
            pass

    candidates = [
        os.getenv("LOCALAPPDATA"),
        os.getenv("APPDATA"),
        tempfile.gettempdir(),
    ]
    for raw in candidates:
        value = str(raw or "").strip()
        if value:
            try:
                base = Path(value).expanduser().resolve() / runtime_app_name()
                if is_writable_runtime_dir(base):
                    _RUNTIME_BASE_DIR_CACHE = base
                    return base
            except Exception:
                continue
    fallback = Path.home().resolve() / ".videofactory"
    try:
        if is_writable_runtime_dir(fallback):
            _RUNTIME_BASE_DIR_CACHE = fallback
            return fallback
    except Exception:
        local_fallback = Path.cwd().resolve() / ".videofactory-runtime"
        if is_writable_runtime_dir(local_fallback):
            _RUNTIME_BASE_DIR_CACHE = local_fallback
            return local_fallback
    local_fallback = Path.cwd().resolve() / ".videofactory-runtime"
    local_fallback.mkdir(parents=True, exist_ok=True)
    _RUNTIME_BASE_DIR_CACHE = local_fallback
    return local_fallback


def runtime_path(*parts: str, ensure: bool = False) -> Path:
    path = runtime_base_dir().joinpath(*parts)
    if ensure:
        path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_file_path(*parts: str) -> Path:
    path = runtime_path(*parts[:-1], ensure=True) if len(parts) > 1 else runtime_base_dir()
    return path / parts[-1]
