from app.extensions import db
from datetime import datetime

class Template(db.Model):
    __tablename__ = 'templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100))
    tags = db.Column(db.String(200))
    json_path = db.Column(db.String(500), nullable=False)
    preview_image = db.Column(db.String(500))
    duration = db.Column(db.Integer, default=0)
    music_suggestions = db.Column(db.Text)
    default_text = db.Column(db.Text)
    generate_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = db.Column(db.Integer, default=1)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    def __repr__(self):
        return f'<Template {self.name}>'