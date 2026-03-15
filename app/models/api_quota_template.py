from datetime import datetime
from app.extensions import db


class ApiQuotaTemplate(db.Model):
    __tablename__ = "api_quota_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    rules_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<ApiQuotaTemplate {self.name}>"
