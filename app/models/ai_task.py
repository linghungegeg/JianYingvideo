from datetime import datetime
from app.extensions import db


class AITask(db.Model):
    __tablename__ = "ai_tasks"

    id = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    key_id = db.Column(db.Integer, db.ForeignKey("user_api_keys.id"))
    provider_code = db.Column(db.String(50), nullable=False)
    task_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default="pending")
    prompt = db.Column(db.Text)
    result_path = db.Column(db.String(500))
    result_text = db.Column(db.Text)
    error_msg = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<AITask {self.id} {self.provider_code} {self.task_type}>"
