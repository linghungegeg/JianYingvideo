import base64
import hashlib
from flask import current_app
from cryptography.fernet import Fernet, InvalidToken


def _derive_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _normalize_fernet_key(raw_value: str) -> bytes:
    value = (raw_value or "").strip()
    if not value:
        raise ValueError("missing encryption key")
    try:
        Fernet(value.encode("utf-8"))
        return value.encode("utf-8")
    except Exception:
        return _derive_key(value)


def _get_fernet() -> Fernet:
    custom_key = None
    try:
        custom_key = current_app.config.get("BYOK_ENCRYPTION_KEY") or current_app.config.get("VIDEOFACTORY_KEY_ENCRYPTION_KEY")
    except Exception:
        custom_key = None
    if custom_key:
        return Fernet(_normalize_fernet_key(custom_key))
    secret = "video_factory_default_key"
    try:
        secret = current_app.config.get("SECRET_KEY", secret)
    except Exception:
        pass
    return Fernet(_derive_key(secret))


def encrypt_text(raw: str) -> str:
    if raw is None:
        return ""
    f = _get_fernet()
    token = f.encrypt(raw.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_text(token: str) -> str:
    if not token:
        return ""
    try:
        f = _get_fernet()
        raw = f.decrypt(token.encode("utf-8"))
        return raw.decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
