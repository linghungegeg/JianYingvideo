from datetime import datetime

from flask import current_app

from app.extensions import db
from app.models.user_quota import UserQuota
from app.utils.helpers import get_config


def get_or_create_quota(user_id, default_remaining=0, auto_commit=True):
    quota = UserQuota.query.get(user_id)
    if not quota:
        resolved_default = int(default_remaining or 0)
        if resolved_default <= 0:
            try:
                saved_default = get_config('default_user_quota', '')
                resolved_default = int(saved_default or current_app.config.get('DEFAULT_USER_QUOTA', 0) or 0)
            except Exception:
                resolved_default = 0
        quota = UserQuota(
            user_id=user_id,
            total_generated=0,
            remaining=max(0, int(resolved_default or 0)),
        )
        db.session.add(quota)
        if auto_commit:
            db.session.commit()
    return quota


def quota_to_dict(quota):
    vip_expire_at = quota.vip_expire_at.isoformat() if quota.vip_expire_at else None
    is_vip = bool(quota.vip_expire_at and quota.vip_expire_at > datetime.utcnow())
    return {
        'total_generated': quota.total_generated,
        'remaining': quota.remaining,
        'vip_expire_at': vip_expire_at,
        'is_vip': is_vip
    }


def deduct_quota(user_id, amount=1):
    quota = get_or_create_quota(user_id)
    if quota.remaining < amount:
        return False, '次数不足', quota
    quota.remaining -= amount
    quota.total_generated += amount
    db.session.commit()
    return True, 'ok', quota


def adjust_quota(user_id, remaining=None, delta=None, vip_expire_at=None):
    quota = get_or_create_quota(user_id)
    if remaining is not None:
        quota.remaining = max(0, int(remaining))
    if delta is not None:
        quota.remaining = max(0, quota.remaining + int(delta))
    if vip_expire_at is not None:
        quota.vip_expire_at = vip_expire_at
    db.session.commit()
    return quota
