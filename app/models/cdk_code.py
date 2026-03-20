from datetime import datetime
from app.extensions import db


class CdkCode(db.Model):
    __tablename__ = 'cdk_codes'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    card_type = db.Column(db.String(20), nullable=False)
    duration_days = db.Column(db.Integer, nullable=False)
    bonus_points = db.Column(db.Integer, default=0)
    device_limit = db.Column(db.Integer, default=1)
    transfer_times = db.Column(db.Integer, default=0)
    transfer_times_left = db.Column(db.Integer, default=0)
    status = db.Column(db.Integer, default=0)  # 0-未激活 1-已激活 2-已过期 3-已禁用
    activated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    activated_at = db.Column(db.DateTime, nullable=True)
    expire_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    batch_id = db.Column(db.String(32), nullable=True)
    redeem_deadline = db.Column(db.DateTime, nullable=True)
    last_transfer_at = db.Column(db.DateTime, nullable=True)
