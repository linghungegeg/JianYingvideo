from datetime import datetime, date
from app.extensions import db


class ApiQuota(db.Model):
    __tablename__ = "api_quotas"

    id = db.Column(db.Integer, primary_key=True)
    key_id = db.Column(db.Integer, db.ForeignKey("api_keys.id"), nullable=False)
    action = db.Column(db.String(128), nullable=False, default="*")
    daily_limit = db.Column(db.Integer, default=1000)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("key_id", "action", name="uq_api_quota_key_action"),
    )

    @staticmethod
    def today() -> date:
        return date.today()
