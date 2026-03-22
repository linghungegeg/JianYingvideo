import os
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.extensions import db
from app.models.config import Config
from app.models.template_model import TemplateModel
from app.models.user import User
from app.services.user_quota_service import adjust_quota, get_or_create_quota
from app.views.api import _ensure_user_ref_code

ADMIN_USER = os.getenv("VF_FULL_REG_ADMIN_USER", "codex_full_admin")
ADMIN_PASS = os.getenv("VF_FULL_REG_ADMIN_PASS", "Codex123!")
NORMAL_USER = os.getenv("VF_FULL_REG_USER", "codex_full_user")
NORMAL_PASS = os.getenv("VF_FULL_REG_PASS", "Codex123!")


def ensure_user(username: str, password: str, role: str) -> User:
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(username=username, role=role)
    else:
        user.role = role
    user.password_hash = generate_password_hash(password)
    db.session.add(user)
    db.session.commit()
    _ensure_user_ref_code(user, commit=True)
    return user


def pick_template():
    for template in TemplateModel.query.order_by(TemplateModel.id.asc()).all():
        if template.template_path and os.path.exists(template.template_path):
            return template
    draft_root = PROJECT_ROOT / "user_data" / "dev_drafts"
    for marker in draft_root.rglob("draft_content.json"):
        if marker.is_file():
            class LocalTemplate:
                id = "local-dev-draft"
                template_path = str(marker.parent)
            return LocalTemplate()
    return None


def expect(condition: bool, message: str):
    if not condition:
        raise SystemExit(message)


def auth_headers(client, username: str, password: str):
    resp = client.post(
        "/api/auth/login",
        json={
            "account": username,
            "password": password,
            "accepted_agreements": True,
        },
    )
    expect(resp.status_code == 200, f"login failed for {username}: {resp.status_code} {resp.get_data(as_text=True)}")
    data = resp.get_json() or {}
    expect(data.get("ok") and data.get("token"), f"invalid login payload for {username}: {data}")
    return {"Authorization": f"Bearer {data['token']}"}


def open_checked(client, method, url, *, headers=None, json=None, data=None, expected_statuses=(200, 400, 401, 403, 404)):
    resp = client.open(url, method=method, headers=headers, json=json, data=data)
    expect(
        resp.status_code in expected_statuses,
        f"{method} {url} unexpected status={resp.status_code} body={resp.get_data(as_text=True)}",
    )
    if resp.status_code >= 500:
        raise SystemExit(f"{method} {url} returned 5xx: {resp.status_code} {resp.get_data(as_text=True)}")
    print(f"[OK] {method} {url} -> {resp.status_code}")
    return resp


def main():
    app = create_app()
    with app.app_context():
        ensure_user(ADMIN_USER, ADMIN_PASS, "admin")
        normal_user = ensure_user(NORMAL_USER, NORMAL_PASS, "user")
        quota = get_or_create_quota(normal_user.id)
        if (quota.remaining or 0) < 3:
            adjust_quota(normal_user.id, remaining=3)
        template = pick_template()
        item = Config.query.filter_by(key="drafts_folder").first()
        drafts_folder = item.value if item and item.value else ""

    client = app.test_client()
    admin_headers = auth_headers(client, ADMIN_USER, ADMIN_PASS)
    user_headers = auth_headers(client, NORMAL_USER, NORMAL_PASS)

    # user page routes
    for url in ("/", "/user", "/user/home", "/user/logs", "/user/settings", "/user/generate", "/admin", "/admin/"):
        open_checked(client, "GET", url, expected_statuses=(200, 302))

    # general user APIs
    open_checked(client, "GET", "/api/runtime-features")
    open_checked(client, "GET", "/api/site-settings")
    open_checked(client, "GET", "/api/user/info", headers=user_headers)
    open_checked(client, "GET", "/api/user/points/overview", headers=user_headers)
    open_checked(client, "GET", "/api/license/status", headers=user_headers)
    open_checked(client, "GET", "/api/effects/types")
    open_checked(client, "GET", "/api/materials/list", headers=user_headers)
    open_checked(client, "GET", "/api/user/materials", headers=user_headers)
    open_checked(client, "GET", "/api/ai/providers", headers=user_headers)
    open_checked(client, "GET", "/api/ai/keys", headers=user_headers)
    open_checked(client, "GET", "/api/user/keys", headers=user_headers)
    open_checked(client, "GET", "/api/openclaw/logs", headers=user_headers)
    open_checked(client, "GET", "/api/manga/history", headers=user_headers)
    open_checked(client, "GET", "/api/manga/templates", headers=user_headers)
    open_checked(client, "GET", "/api/duo/resources/categories")
    open_checked(client, "GET", "/api/duo/cache/status")
    open_checked(client, "GET", "/api/duo/ffmpeg/status")
    open_checked(client, "GET", "/api/drafts/discover?limit=10", headers=user_headers)

    # user config/settings writes
    open_checked(client, "GET", "/api/user/config", headers=user_headers)
    open_checked(
        client,
        "POST",
        "/api/user/config",
        headers=user_headers,
        json={"openclaw_base_url": "http://127.0.0.1:8000", "openclaw_token": "demo"},
        expected_statuses=(200,),
    )
    open_checked(
        client,
        "POST",
        "/api/settings",
        headers=user_headers,
        json={"draft_root": drafts_folder, "export_dir": "", "cache_dir": "", "strategy": "balanced", "auto_discover": True},
        expected_statuses=(200,),
    )

    # draft-related endpoints
    if template:
        payload = {"draft_path": template.template_path}
        open_checked(client, "POST", "/api/draft/inspect", headers=user_headers, json=payload)
        open_checked(client, "POST", "/api/draft/timeline-summary", headers=user_headers, json=payload)
        open_checked(
            client,
            "POST",
            "/api/drafts/timeline-summary",
            headers=user_headers,
            json={"draft_paths": [template.template_path]},
        )
        open_checked(
            client,
            "POST",
            "/api/export/main-track",
            headers=user_headers,
            json={"draft_path": template.template_path, "output_dir": "", "only_main_video": True},
        )
    else:
        print("[WARN] no template found, skipped draft-specific checks")

    # validation-path checks: should fail gracefully, not 500
    open_checked(client, "POST", "/api/openclaw/test", headers=user_headers, json={}, expected_statuses=(400,))
    open_checked(client, "POST", "/api/split", headers=user_headers, json={}, expected_statuses=(400,))
    open_checked(client, "POST", "/api/export/drafts", headers=user_headers, json={}, expected_statuses=(400,))
    open_checked(client, "POST", "/api/micro-adjust", headers=user_headers, json={}, expected_statuses=(400,))
    open_checked(client, "POST", "/api/duo/resources/search", headers=user_headers, json={}, expected_statuses=(200, 400))
    open_checked(client, "POST", "/api/effects/list", headers=user_headers, json={}, expected_statuses=(200, 400))
    open_checked(client, "POST", "/api/apply-effect", headers=user_headers, json={}, expected_statuses=(400,))
    open_checked(client, "POST", "/api/ai/generate/video", headers=user_headers, json={}, expected_statuses=(400,))
    open_checked(client, "POST", "/api/ai/generate/audio", headers=user_headers, json={}, expected_statuses=(400,))
    open_checked(client, "POST", "/api/ai/generate/text", headers=user_headers, json={}, expected_statuses=(400,))
    open_checked(client, "POST", "/api/ai/manga/generate", headers=user_headers, json={}, expected_statuses=(400, 404))
    open_checked(client, "POST", "/api/manga/batch/set-duration", headers=user_headers, json={}, expected_statuses=(400,))
    open_checked(client, "POST", "/api/manga/batch/apply-effects", headers=user_headers, json={}, expected_statuses=(400,))
    open_checked(client, "POST", "/api/manga/batch/export", headers=user_headers, json={}, expected_statuses=(400,))

    # admin APIs
    open_checked(client, "GET", "/api/admin/manga/stats", headers=admin_headers)
    open_checked(client, "GET", "/api/admin/license-settings", headers=admin_headers)
    open_checked(client, "GET", "/api/admin/cdk/list", headers=admin_headers)
    open_checked(client, "GET", "/api/admin/license/bindings", headers=admin_headers)
    open_checked(client, "GET", f"/api/admin/users/search?kw={NORMAL_USER}", headers=admin_headers)
    open_checked(client, "GET", "/api/admin/logs", headers=admin_headers)

    # admin write paths
    open_checked(
        client,
        "POST",
        "/api/admin/license-settings",
        headers=admin_headers,
        json={
            "license_offline_hours": 72,
            "license_transfer_cooldown_hours": 24,
            "license_code_length": 16,
            "license_points_ratio": 1,
            "manga_generate_cost": 1,
            "daily_checkin_reward": 1,
        },
        expected_statuses=(200,),
    )
    open_checked(
        client,
        "POST",
        "/api/admin/cdk/batch",
        headers=admin_headers,
        json={"card_type": "回归测试卡", "duration_days": 1, "quantity": 1},
        expected_statuses=(200,),
    )

    # privilege checks
    open_checked(client, "GET", "/api/admin/license-settings", headers=user_headers, expected_statuses=(403,))
    open_checked(client, "GET", "/api/admin/logs", headers=user_headers, expected_statuses=(403,))

    print("OK full feature regression passed")


if __name__ == "__main__":
    main()
