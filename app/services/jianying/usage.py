import os
from datetime import date

from app.extensions import db
from app.models.api_usage import ApiUsage


def get_daily_limit() -> int:
    raw = os.getenv("MCP_DAILY_LIMIT", "").strip()
    if raw.isdigit():
        return int(raw)
    return 1000


def check_and_increment(client_id: str) -> bool:
    """
    返回 True 表示允许调用；False 表示超限。
    """
    if not client_id:
        return False
    today = date.today()
    usage = ApiUsage.query.filter_by(client_id=client_id, usage_date=today).first()
    if not usage:
        usage = ApiUsage(client_id=client_id, usage_date=today, count=0)
        db.session.add(usage)
        db.session.commit()

    limit = get_daily_limit()
    if usage.count >= limit:
        return False

    usage.count += 1
    db.session.commit()
    return True
