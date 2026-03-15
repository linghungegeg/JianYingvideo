import uuid
from datetime import datetime, timedelta
from app.extensions import db
from app.models.user import User
from app.models.user_token import UserToken


def extract_bearer_token(req):
    auth = (req.headers.get('Authorization') or '').strip()
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return None


def issue_token(user_id, hours=24):
    token = uuid.uuid4().hex
    expires_at = datetime.utcnow() + timedelta(hours=hours) if hours else None
    token_obj = UserToken(user_id=user_id, token=token, expires_at=expires_at)
    db.session.add(token_obj)
    db.session.commit()
    return token_obj


def validate_token(token):
    if not token:
        return None, None, 'missing'
    token_obj = UserToken.query.filter_by(token=token).first()
    if not token_obj:
        return None, None, 'invalid'
    if token_obj.expires_at and token_obj.expires_at < datetime.utcnow():
        return None, token_obj, 'expired'
    user = User.query.get(token_obj.user_id)
    if not user:
        return None, token_obj, 'user_missing'
    return user, token_obj, None
