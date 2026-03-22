import json
import os
import sys
import uuid
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from app.extensions import db
import app.views.api as api_mod


class DummyResponse:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = json.dumps(payload, ensure_ascii=False)
        self.content = self.text.encode("utf-8")

    def json(self):
        return self._payload


def expect(condition, message):
    if not condition:
        raise SystemExit(message)


def fake_remote(path, method="GET", headers=None, json_data=None, data=None, timeout=15):
    if path == "/api/user/info":
        return DummyResponse({
            "ok": True,
            "user": {
                "id": 7,
                "username": "remote_user",
                "email": "remote@test.local",
                "role": "user",
            },
        })
    if path == "/api/site-settings":
        return DummyResponse({
            "ok": True,
            "settings": {"official_site_url": "https://www.zysj.site"},
        })
    if path == "/api/desktop/task-claim":
        return DummyResponse({
            "ok": True,
            "task_id": (json_data or {}).get("task_id"),
            "quota_reserved": True,
        })
    if path == "/api/desktop/task-complete":
        return DummyResponse({
            "ok": True,
            "task_id": (json_data or {}).get("task_id"),
            "success": bool((json_data or {}).get("success")),
        })
    raise AssertionError(f"unexpected remote path: {path}")


def main():
    expect(str(os.getenv("VF_REMOTE_AUTH_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}, "VF_REMOTE_AUTH_MODE is not enabled")
    expect(bool(str(os.getenv("VF_OFFICIAL_SITE_URL") or "").strip()), "VF_OFFICIAL_SITE_URL is missing")

    with patch.object(api_mod, "call_remote_api", side_effect=fake_remote):
        app = create_app()
        with app.app_context():
            db.create_all()
        client = app.test_client()
        auth = {"Authorization": "Bearer remote-token"}
        task_id = f"remote_auth_check_{uuid.uuid4().hex}"

        resp = client.get("/user")
        expect(resp.status_code == 200, f"/user returned {resp.status_code}")

        resp = client.get("/api/site-settings")
        expect(resp.status_code == 200, f"/api/site-settings returned {resp.status_code}")

        resp = client.get("/api/user/config", headers=auth)
        expect(resp.status_code == 200, f"/api/user/config returned {resp.status_code}")

        resp = client.post(
            "/api/desktop/task-claim",
            headers=auth,
            json={"task_id": task_id, "action_key": "generate_batch", "quota_amount": 1},
        )
        expect(resp.status_code == 200, f"/api/desktop/task-claim returned {resp.status_code}")

        resp = client.post(
            "/api/desktop/task-complete",
            headers=auth,
            json={"task_id": task_id, "success": True},
        )
        expect(resp.status_code == 200, f"/api/desktop/task-complete returned {resp.status_code}")

    print("remote-auth-mode simulated checks passed")


if __name__ == "__main__":
    main()
