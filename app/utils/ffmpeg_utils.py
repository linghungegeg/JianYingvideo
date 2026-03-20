import os
import shutil
from pathlib import Path
from typing import Optional, Tuple


def _runtime_tool_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime_tools" / "ffmpeg"


def _path_exists(path: str) -> bool:
    if not path:
        return False
    if os.path.exists(path) or os.path.lexists(path):
        return True
    return os.path.exists(os.path.realpath(path))


def _env_path(name: str) -> Optional[str]:
    value = (os.getenv(name) or "").strip()
    if value and _path_exists(value):
        return value
    return None


def _winget_links_dir() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Microsoft" / "WinGet" / "Links"
    return Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links"


def find_binary(name: str, env_var: Optional[str] = None) -> Optional[str]:
    if env_var:
        env_path = _env_path(env_var)
        if env_path:
            return env_path

    runtime_candidate = _runtime_tool_dir() / f"{name}.exe"
    if _path_exists(str(runtime_candidate)):
        return str(runtime_candidate)

    path_hit = shutil.which(name)
    if path_hit:
        return path_hit

    winget_candidate = _winget_links_dir() / f"{name}.exe"
    if _path_exists(str(winget_candidate)):
        return str(winget_candidate)

    return None


def find_ffmpeg() -> Optional[str]:
    return find_binary("ffmpeg", "FFMPEG_PATH")


def find_ffprobe() -> Optional[str]:
    return find_binary("ffprobe", "FFPROBE_PATH")


def find_ffmpeg_with_source() -> Tuple[Optional[str], str]:
    env_path = _env_path("FFMPEG_PATH")
    if env_path:
        return env_path, "FFMPEG_PATH"

    runtime_candidate = _runtime_tool_dir() / "ffmpeg.exe"
    if _path_exists(str(runtime_candidate)):
        return str(runtime_candidate), "runtime_tools"

    path_hit = shutil.which("ffmpeg")
    if path_hit:
        return path_hit, "PATH"

    winget_candidate = _winget_links_dir() / "ffmpeg.exe"
    if _path_exists(str(winget_candidate)):
        return str(winget_candidate), "WinGet Links"

    return None, ""
