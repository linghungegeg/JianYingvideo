from datetime import datetime
from app.extensions import db


class ApiKey(db.Model):
    __tablename__ = "api_keys"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    group = db.Column(db.String(64), default="default")
    role = db.Column(db.String(32), default="write")
    allow_actions = db.Column(db.Text)
    deny_actions = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    key_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    revoked_at = db.Column(db.DateTime)
    last_used_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<ApiKey {self.id} {self.name}>"
