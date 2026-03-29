import os
import re
import sys
import uuid
from pathlib import Path

from werkzeug.security import generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.extensions import db
from app.models.resource_exchange_post import ResourceExchangePost
from app.models.user import User
from app.models.user_quota import UserQuota
from app.models.user_token import UserToken
from app.views.api import _ensure_user_ref_code

_RUN_SUFFIX = uuid.uuid4().hex[:8]
ADMIN_USER = os.getenv("VF_REG_ADMIN_USER", f"codex_reg_admin_{_RUN_SUFFIX}")
ADMIN_PASS = os.getenv("VF_REG_ADMIN_PASS", "Codex123!")
NORMAL_USER = os.getenv("VF_REG_USER", f"codex_reg_user_{_RUN_SUFFIX}")
NORMAL_PASS = os.getenv("VF_REG_PASS", "Codex123!")
_CLEANUP_USERS = not os.getenv("VF_REG_ADMIN_USER") and not os.getenv("VF_REG_USER")


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


def cleanup_users(usernames):
    users = User.query.filter(User.username.in_(list(usernames))).all()
    if not users:
        return
    user_ids = [user.id for user in users]
    UserToken.query.filter(UserToken.user_id.in_(user_ids)).delete(synchronize_session=False)
    UserQuota.query.filter(UserQuota.user_id.in_(user_ids)).delete(synchronize_session=False)
    ResourceExchangePost.query.filter(ResourceExchangePost.user_id.in_(user_ids)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    db.session.commit()


def expect(condition: bool, message: str):
    if not condition:
        raise SystemExit(message)


def ensure_contains(text: str, needles, label: str):
    missing = [item for item in needles if item not in text]
    expect(not missing, f"{label} missing markers: {missing}")


def ensure_groups(text: str, pattern: str, expected, label: str):
    found = set(re.findall(pattern, text))
    expect(found == set(expected), f"{label} groups mismatch: expected={sorted(expected)} found={sorted(found)}")


def auth_headers(client, username: str, password: str):
    resp = client.post(
        "/api/auth/login",
        json={"account": username, "password": password, "accepted_agreements": True},
    )
    expect(resp.status_code == 200, f"login failed for {username}: {resp.status_code} {resp.get_data(as_text=True)}")
    data = resp.get_json() or {}
    expect(data.get("ok") and data.get("token"), f"login payload invalid for {username}: {data}")
    return {"Authorization": f"Bearer {data['token']}"}, data


def main():
    app = create_app()
    try:
        with app.app_context():
            ensure_user(ADMIN_USER, ADMIN_PASS, "admin")
            ensure_user(NORMAL_USER, NORMAL_PASS, "user")

        client = app.test_client()

        user_page = client.get("/user")
        expect(user_page.status_code == 200, f"/user returned {user_page.status_code}")
        user_html = user_page.get_data(as_text=True)
        ensure_contains(
            user_html,
            [
                'id="authModal"',
                'class="auth-modal open"',
                'id="workbenchApp"',
                'id="panel-assistant"',
                'id="panel-materials"',
                'id="panel-ai-make"',
                'id="panel-ai-manga"',
                'id="panel-effects"',
                'id="panel-split"',
                'id="panel-clip"',
                'id="panel-export"',
                'id="panel-resource-exchange"',
                'id="panel-settings"',
                'id="panel-account"',
                'id="account-tutorial-section"',
                'data-group="assistant"',
                'data-group="resource"',
                '鎸夌粍绮惧噯鏇挎崲',
                '娣峰壀瑁傚彉鏇挎崲',
                '鍒嗗尯娣峰壀瑁傚彉',
                'data-subtab-container="panel-export"',
                'data-subtab-container="panel-split"',
                'data-subtab-container="clipToolsGrid"',
                'data-hard-section="settings-ai-section"',
                'AI璐﹀彿绠＄悊',
            ],
            "/user",
        )
        expect("椤堕儴鍝佺墝鏉?" not in user_html, "/user still contains old top brand copy")
        expect('id="panel-material-capture"' not in user_html, "/user still contains removed material capture panel")
        expect('id="partition_text_mode"' in user_html, "/user missing partition text mode select")
        expect('id="sequence_clip_count"' in user_html, "/user missing sequence clip count input")
        expect('data-mix-target="sequence"' in user_html, "/user missing sequence mix mode entry")
        expect("绱犳潗鑾峰緱" not in user_html, "/user still contains removed capture navigation copy")
        expect('data-hard-section="settings-service-section"' not in user_html, "/user sidebar still exposes AI manga service entry")
        expect(user_html.find('data-group="assistant"') < user_html.find('data-group="mix"'), "/user assistant group is not before mix")
        expect(user_html.find('data-group="resource"') < user_html.find('data-group="settings"'), "/user resource group is not before settings")
        ensure_groups(
            user_html,
            r'data-subtab-group="(export-[^"]+)"',
            ["export-settings", "export-batch", "export-segments"],
            "/user export subtabs",
        )
        ensure_groups(
            user_html,
            r'data-subtab-group="(split-[^"]+)"',
            ["split-file", "split-draft", "split-batch"],
            "/user split subtabs",
        )
        ensure_groups(
            user_html,
            r'data-subtab-group="(clip-[^"]+)"',
            ["clip-ai", "clip-rhythm", "clip-transform", "clip-shake"],
            "/user clip subtabs",
        )

        admin_page = client.get("/admin")
        expect(admin_page.status_code == 200, f"/admin returned {admin_page.status_code}")
        admin_html = admin_page.get_data(as_text=True)
        ensure_contains(
            admin_html,
            [
                'id="adminWorkbench"',
                'class="workspace-shell admin-shell is-locked"',
                'id="adminAuthModal"',
                'id="adminNav"',
                'class="admin-layout"',
                'class="admin-sidebar"',
                'class="admin-main"',
                'data-section="overview"',
                'data-section="site"',
                'data-section="license"',
                'data-section="cdk"',
                'data-section="bindings"',
                'data-section="users"',
                'data-section="resource-review"',
                'data-section="logs"',
                'id="section-overview"',
                'id="section-site"',
                'id="section-license"',
                'id="section-resource-review"',
                'id="clearAdminAuthBtn"',
            ],
            "/admin",
        )
        expect("杩斿洖鐢ㄦ埛宸ヤ綔鍙?" not in admin_html, "/admin still contains removed back-to-workspace action")

        admin_headers, admin_login = auth_headers(client, ADMIN_USER, ADMIN_PASS)
        expect((admin_login.get("user") or {}).get("role") == "admin", "admin login did not return admin role")

        normal_headers, normal_login = auth_headers(client, NORMAL_USER, NORMAL_PASS)
        expect((normal_login.get("user") or {}).get("role") == "user", "normal login did not return user role")

        authed_checks = [
            ("GET", "/api/user/info", admin_headers, 200, lambda d: d.get("ok") and d.get("user", {}).get("role") == "admin"),
            (
                "GET",
                "/api/runtime-features",
                None,
                200,
                lambda d: d.get("ok")
                and all(d.get("features", {}).get(k) for k in ("duo", "openclaw", "manga"))
                and d.get("requirements", {}).get("manga") == ["MANGA_FEATURES_ENABLED"],
            ),
            ("GET", "/api/site-settings", None, 200, lambda d: isinstance(d, dict)),
            (
                "GET",
                "/api/workspace/settings",
                admin_headers,
                200,
                lambda d: d.get("ok")
                and isinstance(d.get("settings"), dict)
                and "capture_save_folder" not in (d.get("settings", {}).get("paths") or {})
                and "net" not in (d.get("settings", {}).get("services") or {})
                and "openclaw" in (d.get("settings", {}).get("services") or {}),
            ),
            ("GET", "/api/effects/types", None, 200, lambda d: isinstance(d.get("types"), list)),
            ("GET", "/api/duo/resources/categories", None, 200, lambda d: isinstance(d, dict)),
            ("GET", "/api/duo/cache/status", None, 200, lambda d: isinstance(d, dict)),
            ("GET", "/api/duo/ffmpeg/status", None, 200, lambda d: isinstance(d, dict)),
            ("GET", "/api/admin/license-settings", admin_headers, 200, lambda d: d.get("ok") and isinstance(d.get("settings"), dict)),
            ("GET", "/api/admin/quota-summary", admin_headers, 200, lambda d: d.get("ok") and all(k in d for k in ("total_remaining", "total_generated", "active_trial_users", "quota_users"))),
            ("GET", "/api/admin/cdk/list", admin_headers, 200, lambda d: d.get("ok") and isinstance(d.get("items"), list)),
            ("GET", "/api/admin/license/bindings", admin_headers, 200, lambda d: d.get("ok") and isinstance(d.get("items"), list)),
            ("GET", "/api/admin/users/search", admin_headers, 200, lambda d: d.get("ok") and isinstance(d.get("items"), list) and isinstance(d.get("pagination"), dict)),
            ("GET", f"/api/admin/users/search?kw={ADMIN_USER}", admin_headers, 200, lambda d: d.get("ok") and isinstance(d.get("items"), list) and isinstance(d.get("pagination"), dict)),
            ("GET", "/api/admin/logs", admin_headers, 200, lambda d: d.get("ok") and isinstance(d.get("items"), list)),
            ("GET", "/api/openclaw/logs", admin_headers, 200, lambda d: d.get("ok") is True),
            ("GET", "/api/ai/providers", admin_headers, 200, lambda d: d.get("ok") and isinstance(d.get("items"), list)),
            ("GET", "/api/ai/keys", admin_headers, 200, lambda d: d.get("ok") and isinstance(d.get("items"), list)),
            ("GET", "/api/user/points/overview", admin_headers, 200, lambda d: d.get("ok") is True),
            ("GET", "/api/license/status", admin_headers, 200, lambda d: isinstance(d, dict)),
            ("GET", "/api/resource-exchange/list", None, 200, lambda d: d.get("ok") and isinstance(d.get("items"), list) and isinstance(d.get("pagination"), dict)),
            ("GET", "/api/resource-exchange/my-posts", normal_headers, 200, lambda d: d.get("ok") and isinstance(d.get("items"), list)),
            ("GET", "/api/admin/resource-exchange/posts", admin_headers, 200, lambda d: d.get("ok") and isinstance(d.get("items"), list) and isinstance(d.get("pagination"), dict)),
        ]

        for method, url, headers, expected_status, validator in authed_checks:
            resp = client.open(url, method=method, headers=headers)
            expect(resp.status_code == expected_status, f"{url} returned {resp.status_code}: {resp.get_data(as_text=True)}")
            data = resp.get_json() or {}
            expect(validator(data), f"{url} payload check failed: {data}")
            print(f"[OK] {url}")

        denied = client.get("/api/admin/license-settings", headers=normal_headers)
        expect(denied.status_code == 403, f"normal user should not access admin settings: {denied.status_code}")
        denied_data = denied.get_json() or {}
        expect(denied_data.get("ok") is False, f"admin denial payload invalid: {denied_data}")
        print("[OK] normal user blocked from admin settings")

        quota_denied = client.get("/api/admin/quota-summary", headers=normal_headers)
        expect(quota_denied.status_code == 403, f"normal user should not access quota summary: {quota_denied.status_code}")
        quota_denied_data = quota_denied.get_json() or {}
        expect(quota_denied_data.get("ok") is False, f"quota summary denial payload invalid: {quota_denied_data}")
        print("[OK] normal user blocked from admin quota summary")

        print("OK final regression passed")
    finally:
        if _CLEANUP_USERS:
            with app.app_context():
                cleanup_users({ADMIN_USER, NORMAL_USER})


if __name__ == "__main__":
    main()
