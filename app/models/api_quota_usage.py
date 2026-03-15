from datetime import datetime, date
from app.extensions import db


class ApiQuotaUsage(db.Model):
    __tablename__ = "api_quota_usage"

    id = db.Column(db.Integer, primary_key=True)
    key_id = db.Column(db.Integer, db.ForeignKey("api_keys.id"), nullable=False)
    action = db.Column(db.String(128), nullable=False)
    usage_date = db.Column(db.Date, nullable=False, index=True)
    count = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("key_id", "action", "usage_date", name="uq_api_quota_usage"),
    )

    @staticmethod
    def today() -> date:
        return date.today()
