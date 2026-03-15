from app.extensions import db
from datetime import datetime

class TemplateModel(db.Model):
    __tablename__ = 'template_models'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100))
    preview_image = db.Column(db.String(500))
    template_path = db.Column(db.String(500), nullable=False)
    placeholder_info = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = db.Column(db.Integer, default=1)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # 模板素材/文本配置改为运行时解析，不再存库

    def __repr__(self):
        return f'<TemplateModel {self.name}>'
