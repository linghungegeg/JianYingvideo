from datetime import datetime
from app.extensions import db


class UserQuota(db.Model):
    __tablename__ = 'user_quota'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    total_generated = db.Column(db.Integer, default=0, nullable=False)
    remaining = db.Column(db.Integer, default=0, nullable=False)
    vip_expire_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('quota', uselist=False))
