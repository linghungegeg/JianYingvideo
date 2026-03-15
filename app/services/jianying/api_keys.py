import hashlib
import os
import secrets
from datetime import datetime
from typing import Optional

from app.extensions import db
from app.models.api_key import ApiKey


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key() -> str:
    return secrets.token_urlsafe(32)


def create_key(name: str, user_id: int = None, group: str = "default", role: str = "write") -> str:
    raw = generate_key()
    key_hash = _hash_key(raw)
    item = ApiKey(name=name, key_hash=key_hash, active=True, user_id=user_id, group=group, role=role)
    db.session.add(item)
    db.session.commit()
    return raw


def verify_key(raw: str) -> Optional[ApiKey]:
    if not raw:
        return None
    key_hash = _hash_key(raw)
    key = ApiKey.query.filter_by(key_hash=key_hash, active=True).first()
    if key:
        key.last_used_at = datetime.utcnow()
        db.session.commit()
    return key


def get_key_by_raw(raw: str) -> Optional[ApiKey]:
    if not raw:
        return None
    key_hash = _hash_key(raw)
    return ApiKey.query.filter_by(key_hash=key_hash, active=True).first()


def revoke_key(key_id: int) -> bool:
    key = ApiKey.query.get(key_id)
    if not key:
        return False
    key.active = False
    key.revoked_at = datetime.utcnow()
    db.session.commit()
    return True


def delete_key(key_id: int) -> bool:
    key = ApiKey.query.get(key_id)
    if not key:
        return False
    db.session.delete(key)
    db.session.commit()
    return True
