from datetime import datetime, date
from app.extensions import db


class ApiUsage(db.Model):
    __tablename__ = "api_usage"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(128), nullable=False, index=True)
    usage_date = db.Column(db.Date, nullable=False, index=True)
    count = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("client_id", "usage_date", name="uq_api_usage_client_date"),
    )

    @staticmethod
    def today() -> date:
        return date.today()
