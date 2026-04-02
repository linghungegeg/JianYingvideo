import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent

for candidate in (ROOT_DIR, SCRIPTS_DIR):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from app import create_app
from app.utils.desktop_runtime import ensure_runtime_dirs, validate_installer_config
from app.utils.ffmpeg_utils import find_ffprobe
from app.utils.helpers import get_site_settings
import runtime_selfcheck


TARGET_OFFICIAL_SITE_URL = "https://www.zysj.site"
PACKAGING_FILES = [
    ROOT_DIR / "packaging" / "video_factory_desktop.spec",
    ROOT_DIR / "packaging" / "video_factory_installer.iss",
    ROOT_DIR / "scripts" / "build_desktop_bundle.py",
]


def record(name, ok, detail=""):
    status = "OK" if ok else "FAIL"
    suffix = f" {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    return ok


def warn(name, detail=""):
    suffix = f" {detail}" if detail else ""
    print(f"[WARN] {name}{suffix}")


def check_installer_gate(app):
    try:
        validate_installer_config(app)
        return record("installer/gate", True, "passed")
    except Exception as exc:
        return record("installer/gate", False, f"error={exc}")


def check_ffprobe():
    ffprobe = find_ffprobe()
    if ffprobe:
        return record("ffprobe", True, ffprobe)
    return record("ffprobe", False, "not found")


def check_http_entrypoints(app):
    client = app.test_client()

    root_resp = client.get("/", follow_redirects=False)
    root_location = root_resp.headers.get("Location", "")
    root_ok = root_resp.status_code in (301, 302, 307, 308) and root_location.endswith("/user")
    ok = record("route/root", root_ok, f"status={root_resp.status_code} location={root_location}") and True

    user_resp = client.get("/user")
    user_ok = user_resp.status_code == 200
    ok = record("route/user", user_ok, f"status={user_resp.status_code}") and ok
    return ok


def check_site_links(app):
    with app.app_context():
        settings = get_site_settings()

    remote_auth_mode = str(os.getenv("VF_REMOTE_AUTH_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}
    env_official_site_url = str(os.getenv("VF_OFFICIAL_SITE_URL") or "").strip()
    official_site_url = str(settings.get("official_site_url") or env_official_site_url).strip()
    enforce_official_site = remote_auth_mode or bool(env_official_site_url)
    if enforce_official_site:
        official_ok = official_site_url == TARGET_OFFICIAL_SITE_URL
        ok = record("site/official_url", official_ok, official_site_url or "<empty>") and True
    else:
        ok = True
        if official_site_url:
            record("site/official_url", True, official_site_url)
        else:
            warn("site/official_url", "empty in local dev env; release build will use preset/env value")

    download_url = str(settings.get("download_url") or "").strip()
    if download_url:
        record("site/download_url", True, download_url)
    else:
        warn("site/download_url", "empty, set it in admin before releasing the installer")

    logo_url = str(settings.get("official_logo_url") or "").strip()
    if logo_url:
        record("site/logo_url", True, logo_url)
    else:
        warn("site/logo_url", "empty, optional for packaging")

    return ok


def check_packaging_files():
    ok = True
    for path in PACKAGING_FILES:
        exists = path.exists() and path.is_file()
        ok = record(f"packaging/{path.name}", exists, str(path)) and ok
    return ok


def run_python_script(script_name, extra_args=None):
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        return record(f"script/{script_name}", False, "missing")

    print(f"[RUN] {script_name}")
    command = [sys.executable, str(script_path)]
    if extra_args:
        command.extend(extra_args)
    result = subprocess.run(command, cwd=ROOT_DIR)
    return record(f"script/{script_name}", result.returncode == 0, f"exit={result.returncode}")


def main():
    parser = argparse.ArgumentParser(description="VideoFactory installer prepackage check")
    parser.add_argument("--skip-final-regression", action="store_true", help="skip scripts/final_regression.py")
    parser.add_argument(
        "--with-admin-browser-regression",
        action="store_true",
        help="also run scripts/admin_user_browser_regression.py",
    )
    parser.add_argument(
        "--official-draft-template",
        action="append",
        default=[],
        help="absolute path to an official draft template for release regression; may be repeated",
    )
    args = parser.parse_args()

    print("VideoFactory prepackage check")
    app = create_app()
    ensure_runtime_dirs(app)

    checks = [
        check_installer_gate(app),
        runtime_selfcheck.check_database(app),
        runtime_selfcheck.check_directories(app),
        runtime_selfcheck.check_ffmpeg(),
        check_ffprobe(),
        runtime_selfcheck.check_secret_settings(app),
        check_http_entrypoints(app),
        check_site_links(app),
        check_packaging_files(),
    ]
    runtime_selfcheck.check_feature_switches(app)

    remote_auth_mode = str(os.getenv("VF_REMOTE_AUTH_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not args.skip_final_regression:
        checks.append(run_python_script("remote_auth_mode_check.py" if remote_auth_mode else "final_regression.py"))

    if args.official_draft_template:
        extra_args = []
        for template_path in args.official_draft_template:
            extra_args.extend(["--template", template_path])
        checks.append(run_python_script("official_draft_regression.py", extra_args=extra_args))

    if args.with_admin_browser_regression:
        checks.append(run_python_script("admin_user_browser_regression.py"))

    failed = [item for item in checks if not item]
    print("")
    print(f"Summary: total={len(checks)} failed={len(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
