import json
from typing import Dict

from app.models.api_quota_template import ApiQuotaTemplate


TEMPLATES: Dict[str, Dict[str, int]] = {
    "free": {
        "*": 200,
        "video.add_segment": 50,
        "audio.add_segment": 50,
        "text.add_segment": 50,
    },
    "basic": {
        "*": 1000,
        "video.add_segment": 300,
        "audio.add_segment": 300,
        "text.add_segment": 300,
    },
    "pro": {
        "*": 5000,
        "video.add_segment": 1500,
        "audio.add_segment": 1500,
        "text.add_segment": 1500,
    },
}


def get_template(name: str) -> Dict[str, int]:
    item = ApiQuotaTemplate.query.filter_by(name=name).first()
    if item:
        try:
            return json.loads(item.rules_json)
        except Exception:
            return {}
    return TEMPLATES.get(name, {})


def upsert_template(name: str, rules: Dict[str, int]) -> None:
    payload = json.dumps(rules, ensure_ascii=False)
    item = ApiQuotaTemplate.query.filter_by(name=name).first()
    if not item:
        item = ApiQuotaTemplate(name=name, rules_json=payload)
        from app.extensions import db
        db.session.add(item)
    else:
        item.rules_json = payload
    from app.extensions import db
    db.session.commit()
