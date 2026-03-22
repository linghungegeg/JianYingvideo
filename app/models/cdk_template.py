from datetime import datetime

from app.extensions import db


class CdkTemplate(db.Model):
    __tablename__ = 'cdk_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    duration_days = db.Column(db.Integer, nullable=False, default=30)
    bonus_points = db.Column(db.Integer, nullable=False, default=0)
    device_limit = db.Column(db.Integer, nullable=False, default=1)
    transfer_times = db.Column(db.Integer, nullable=False, default=0)
    redeem_days = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
