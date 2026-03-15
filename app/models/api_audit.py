from datetime import datetime
from app.extensions import db


class ApiAuditLog(db.Model):
    __tablename__ = "api_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(128), index=True)
    action = db.Column(db.String(128))
    status = db.Column(db.String(32))
    code = db.Column(db.String(64))
    message = db.Column(db.Text)
    request_payload = db.Column(db.Text)
    response_payload = db.Column(db.Text)
    key_role = db.Column(db.String(32))
    key_allow = db.Column(db.Text)
    key_deny = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ApiAuditLog {self.id} {self.action}>"
