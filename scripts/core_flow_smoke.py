import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models.config import Config
from app.models.task import Task
from app.models.template_model import TemplateModel
from app.models.user import User
from app.services.user_quota_service import adjust_quota, get_or_create_quota
from app.views.api import _ensure_user_ref_code
USERNAME = os.getenv("VF_SMOKE_USER", "codex_smoke")
PASSWORD = os.getenv("VF_SMOKE_PASS", "Codex123!")
LOCAL_DRAFTS_DIR = os.getenv(
    "VF_SMOKE_DRAFTS_DIR",
    str(Path.cwd() / "user_data" / "dev_drafts"),
)


def ensure_user():
    user = User.query.filter_by(username=USERNAME).first()
    if not user:
        user = User(username=USERNAME, role="admin")
    user.password_hash = generate_password_hash(PASSWORD)
    db.session.add(user)
    db.session.commit()
    _ensure_user_ref_code(user, commit=True)
    return user


def ensure_drafts_folder():
    os.makedirs(LOCAL_DRAFTS_DIR, exist_ok=True)
    item = Config.query.filter_by(key="drafts_folder").first()
    if not item:
        item = Config(key="drafts_folder", value=LOCAL_DRAFTS_DIR)
    else:
        item.value = LOCAL_DRAFTS_DIR
    db.session.add(item)
    db.session.commit()


def pick_template():
    for template in TemplateModel.query.order_by(TemplateModel.id).all():
        if template.template_path and os.path.exists(template.template_path):
            return template
    return None


def main():
    app = create_app()
    with app.app_context():
        user = ensure_user()
        user_id = user.id
        ensure_drafts_folder()
        template = pick_template()
        if not template:
            raise SystemExit("No valid template_path found in template_models")
        template_id = template.id
        template_path = template.template_path

        quota_before = get_or_create_quota(user_id)
        if quota_before.remaining < 1:
            quota_before = adjust_quota(user_id, remaining=1)
        before_remaining = quota_before.remaining
        before_total = quota_before.total_generated

        client = app.test_client()
        login_resp = client.post("/api/auth/login", json={"account": USERNAME, "password": PASSWORD})
        if login_resp.status_code != 200:
            raise SystemExit(f"Login failed: {login_resp.status_code} {login_resp.get_data(as_text=True)}")

        token = login_resp.get_json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "draft_path": template_path,
            "materials_root": None,
            "texts_input": [],
            "batch_count": 1,
            "replace_materials": False,
            "replace_texts": False,
            "export_enabled": False,
        }
        enqueue_resp = client.post("/api/generate-batch", json=payload, headers=headers)
        if enqueue_resp.status_code != 200:
            raise SystemExit(f"Enqueue failed: {enqueue_resp.status_code} {enqueue_resp.get_data(as_text=True)}")
        job_id = enqueue_resp.get_json()["job_id"]

    import time
    final_payload = None
    for _ in range(120):
        with app.app_context():
            task = db.session.get(Task, job_id)
            if task and task.status in ("finished", "failed"):
                final_payload = {
                    "status": task.status,
                    "error_msg": task.error_msg,
                }
                break
        time.sleep(1)

    with app.app_context():
        task = db.session.get(Task, job_id)
        quota_after = get_or_create_quota(user_id)
        print("template_id", template_id)
        print("job_id", job_id)
        print("task_status", task.status if task else None)
        print("task_error", task.error_msg if task else None)
        print("quota_before", before_remaining, before_total)
        print("quota_after", quota_after.remaining, quota_after.total_generated)
        if not task or task.status != "finished":
            raise SystemExit("Smoke check failed: task did not finish successfully")
        if quota_after.remaining != before_remaining - 1:
            raise SystemExit("Smoke check failed: quota remaining did not decrement by 1")
        if quota_after.total_generated != before_total + 1:
            raise SystemExit("Smoke check failed: total_generated did not increment by 1")
        print("OK core flow smoke passed")


if __name__ == "__main__":
    main()
