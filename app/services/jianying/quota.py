from datetime import date
from typing import Optional

from app.extensions import db
from app.models.api_quota import ApiQuota
from app.models.api_quota_usage import ApiQuotaUsage


def _get_quota(key_id: int, action: str) -> Optional[ApiQuota]:
    item = ApiQuota.query.filter_by(key_id=key_id, action=action).first()
    if item:
        return item
    return ApiQuota.query.filter_by(key_id=key_id, action="*").first()


def check_and_increment_quota(key_id: int, action: str) -> bool:
    quota = _get_quota(key_id, action)
    if not quota:
        return True
    today = date.today()
    usage = ApiQuotaUsage.query.filter_by(
        key_id=key_id, action=action, usage_date=today
    ).first()
    if not usage:
        usage = ApiQuotaUsage(key_id=key_id, action=action, usage_date=today, count=0)
        db.session.add(usage)
        db.session.commit()

    if usage.count >= quota.daily_limit:
        return False

    usage.count += 1
    db.session.commit()
    return True
