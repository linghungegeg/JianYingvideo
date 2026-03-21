from datetime import datetime

from app.extensions import db


class ResourceExchangePost(db.Model):
    __tablename__ = "resource_exchange_posts"

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    username = db.Column(db.String(80), nullable=False)
    membership_label = db.Column(db.String(32), nullable=False, default="试用用户")
    membership_value = db.Column(db.Integer, nullable=False, default=0)
    project_name = db.Column(db.String(64), nullable=False)
    project_intro = db.Column(db.String(255), nullable=False)
    contact = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    review_reason = db.Column(db.String(255), nullable=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewer_name = db.Column(db.String(80), nullable=True)

    def __repr__(self):
        return f"<ResourceExchangePost {self.id} {self.project_name}>"
