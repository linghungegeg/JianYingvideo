from datetime import datetime
from app.extensions import db


class UserQuotaLog(db.Model):
    __tablename__ = 'user_quota_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    change = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(100), nullable=False)
    project_id = db.Column(db.String(64), nullable=True)
    remaining_after = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<UserQuotaLog {self.id} {self.reason} {self.change}>"
