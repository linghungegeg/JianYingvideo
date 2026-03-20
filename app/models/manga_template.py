from app.extensions import db
from datetime import datetime


class MangaTemplate(db.Model):
    __tablename__ = 'manga_templates'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    params_json = db.Column(db.Text, nullable=False)
    preview_material_id = db.Column(db.Integer, db.ForeignKey('user_materials.id'), nullable=True)
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<MangaTemplate {self.id} {self.name}>"
