from datetime import datetime
from app.extensions import db


class AIProvider(db.Model):
    __tablename__ = "ai_providers"

    id = db.Column(db.Integer, primary_key=True)
    provider_code = db.Column(db.String(50), unique=True, nullable=False)
    provider_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    logo_url = db.Column(db.String(500))
    docs_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AIProvider {self.provider_code}>"
