from app.extensions import db
from datetime import datetime


class MangaGenerationLog(db.Model):
    __tablename__ = 'manga_generation_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    project_id = db.Column(db.String(64), nullable=False)
    project_name = db.Column(db.String(200), nullable=True)
    params_json = db.Column(db.Text, nullable=False)
    first_material_id = db.Column(db.Integer, db.ForeignKey('user_materials.id'), nullable=True)
    status = db.Column(db.String(32), default='success')
    error_msg = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<MangaGenerationLog {self.id} {self.project_id}>"
