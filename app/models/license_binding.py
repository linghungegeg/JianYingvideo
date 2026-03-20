from datetime import datetime
from app.extensions import db


class LicenseBinding(db.Model):
    __tablename__ = 'license_bindings'

    id = db.Column(db.Integer, primary_key=True)
    code_id = db.Column(db.Integer, db.ForeignKey('cdk_codes.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    device_fingerprint = db.Column(db.String(128), nullable=False)
    device_label = db.Column(db.String(128), nullable=True)
    device_info = db.Column(db.Text, nullable=True)
    active = db.Column(db.Boolean, default=True)
    bound_at = db.Column(db.DateTime, default=datetime.utcnow)
    unbound_at = db.Column(db.DateTime, nullable=True)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
