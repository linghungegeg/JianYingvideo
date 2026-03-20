from datetime import datetime
from app.extensions import db
from app.utils.crypto import encrypt_text, decrypt_text


class UserApiKey(db.Model):
    __tablename__ = "user_api_keys"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey("ai_providers.id"), nullable=False)
    key_name = db.Column(db.String(100), nullable=False)
    api_key = db.Column(db.Text, nullable=False)
    api_secret = db.Column(db.Text)
    endpoint = db.Column(db.String(500))
    base_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    last_used_at = db.Column(db.DateTime)
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    provider = db.relationship("AIProvider")

    def set_api_key(self, raw_key: str):
        self.api_key = encrypt_text(raw_key or "")

    def get_api_key(self) -> str:
        return decrypt_text(self.api_key or "")

    def set_api_secret(self, raw_secret: str):
        if raw_secret is None:
            self.api_secret = None
        else:
            self.api_secret = encrypt_text(raw_secret)

    def get_api_secret(self) -> str:
        return decrypt_text(self.api_secret or "")

    def masked_key(self) -> str:
        raw = self.get_api_key()
        if not raw:
            return ""
        if len(raw) <= 8:
            return "*" * len(raw)
        return f"{raw[:4]}****{raw[-4:]}"

    def __repr__(self):
        return f"<UserApiKey {self.id} user={self.user_id} provider={self.provider_id}>"
