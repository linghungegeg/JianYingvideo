from app.extensions import db
from datetime import datetime


class TaskEffectLog(db.Model):
    __tablename__ = 'task_effect_logs'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(64), db.ForeignKey('tasks.id'), nullable=False, index=True)
    summary = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<TaskEffectLog {self.id} task={self.task_id}>'
