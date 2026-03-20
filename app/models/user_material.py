from datetime import datetime
from app.extensions import db


class UserMaterial(db.Model):
    __tablename__ = "user_materials"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)
    source = db.Column(db.String(50), default="ai")
    tags = db.Column(db.Text, nullable=True)
    metadata_json = db.Column("metadata", db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<UserMaterial {self.id} {self.file_type}>"
