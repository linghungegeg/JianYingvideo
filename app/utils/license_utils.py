import base64
import json
import math
import os
import secrets
import string
import hmac
import hashlib
from typing import Dict, Any

from app.utils.helpers import get_config, set_config


_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_cdk_code(length: int = 20) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _get_signing_key() -> str:
    key = os.getenv("LICENSE_SIGNING_KEY")
    if key:
        return key
    saved = get_config("license_signing_key")
    if saved:
        return saved
    generated = secrets.token_hex(32)
    set_config("license_signing_key", generated)
    return generated


def sign_payload(payload: Dict[str, Any]) -> str:
    secret = _get_signing_key().encode("utf-8")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(body).decode("utf-8").rstrip("=")
    sig = hmac.new(secret, b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")
    return f"{b64}.{sig_b64}"


def get_license_settings() -> Dict[str, int]:
    offline_hours = int(get_config("license_offline_hours", "24") or 24)
    transfer_cooldown_minutes = get_config("license_transfer_cooldown_minutes", "")
    if str(transfer_cooldown_minutes or "").strip():
        transfer_cooldown = int(transfer_cooldown_minutes or 0)
    else:
        legacy_hours = int(get_config("license_transfer_cooldown_hours", "24") or 24)
        transfer_cooldown = max(0, legacy_hours * 60)
    code_length = int(get_config("license_code_length", "20") or 20)
    points_ratio = int(get_config("license_points_ratio", "100") or 100)
    daily_checkin_reward = int(get_config("daily_checkin_reward", "1") or 1)
    return {
        "offline_hours": offline_hours,
        "transfer_cooldown_minutes": transfer_cooldown,
        "transfer_cooldown_hours": int(math.ceil(transfer_cooldown / 60.0)) if transfer_cooldown > 0 else 0,
        "code_length": code_length,
        "points_ratio": points_ratio,
        "daily_checkin_reward": daily_checkin_reward,
    }
