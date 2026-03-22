import os
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from flask import current_app


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def get_official_site_origin() -> str:
    raw = (
        os.getenv("VF_OFFICIAL_SITE_URL")
        or os.getenv("OFFICIAL_SITE_URL")
        or ""
    ).strip()
    if not raw:
        try:
            raw = str(current_app.config.get("OFFICIAL_SITE_URL") or "").strip()
        except Exception:
            raw = ""
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def remote_auth_mode_enabled() -> bool:
    if _env_flag("VF_REMOTE_AUTH_MODE", False):
        return bool(get_official_site_origin())
    return False


def is_local_runtime_host(hostname: str) -> bool:
    host = str(hostname or "").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def build_remote_url(path: str) -> str:
    origin = get_official_site_origin().rstrip("/")
    if not origin:
        return ""
    return urljoin(origin + "/", path.lstrip("/"))


def call_remote_api(
    path: str,
    *,
    method: str = "GET",
    headers: Optional[dict] = None,
    json_data=None,
    data=None,
    timeout: int = 15,
):
    url = build_remote_url(path)
    if not url:
        raise RuntimeError("official site origin is not configured")
    filtered_headers = {}
    for key, value in (headers or {}).items():
        if value is None:
            continue
        lower_key = str(key).lower()
        if lower_key in {"host", "content-length", "connection"}:
            continue
        filtered_headers[key] = value
    return requests.request(
        method=method.upper(),
        url=url,
        headers=filtered_headers,
        json=json_data,
        data=data,
        timeout=timeout,
        allow_redirects=False,
    )
