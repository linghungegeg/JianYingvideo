import argparse
import hashlib
import importlib.util
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from shutil import which
from urllib.parse import urlparse

from PIL import Image


ROOT_DIR = Path(__file__).resolve().parents[1]
PACKAGING_DIR = ROOT_DIR / "packaging"
DEFAULT_BRANDING_DIR = PACKAGING_DIR / "branding"
DEFAULT_BRANDING_LOGO = DEFAULT_BRANDING_DIR / "logo.png"
DEFAULT_BRANDING_ICON = DEFAULT_BRANDING_DIR / "app_icon.ico"
DEFAULT_OFFICIAL_DRAFT_TEMPLATE_FILE = PACKAGING_DIR / "official_draft_release_templates.json"
DEFAULT_PRESET = ROOT_DIR / "env.presets" / "desktop_full.env.example"
DEFAULT_SPEC = PACKAGING_DIR / "video_factory_desktop.spec"
DEFAULT_INSTALLER_TEMPLATE = PACKAGING_DIR / "video_factory_installer.iss"
DEFAULT_APP_VERSION = "1.0.1"
DEFAULT_WINGET_UPX = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "upx.exe"
OBFUSCATE_COPY_TARGETS = [
    "app",
    "migrations",
    "env.presets",
    "packaging",
    "runtime_tools",
    ".env.example",
    "desktop_app.py",
    "run.py",
]
PYARMOR_TARGETS = [
    "app/views/api.py",
    "app/utils/auth_token.py",
    "app/services/jianying/official_draft_replace_service.py",
    "app/services/jianying/draft_replacement_strategy.py",
    "app/tasks.py",
]

RUNTIME_DIR_NAMES = [
    "logs",
    "user_data",
    "runtime_tools",
    "duo_cache",
    "mcp_cache",
]
RELEASE_FORBIDDEN_NAME_PARTS = (
    ".codex-tmp",
    "backups",
    "docs",
    "reverse_capture",
    "official_draft_regression",
)
RELEASE_FORBIDDEN_FILE_GLOBS = (
    "tmp_*",
    "@AutomationLog.txt",
    "pyarmor.bug.log",
)
RELEASE_MINIFY_JS_TARGETS = (
    "app/static/js/user-index.js",
)


def read_env_file(path: Path) -> dict:
    payload = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        payload[key.strip()] = value.strip()
    return payload


def validate_release_env_values(env_values: dict) -> list[str]:
    issues = []
    secret = str(env_values.get("SECRET_KEY") or "")
    byok_key = str(env_values.get("VIDEOFACTORY_KEY_ENCRYPTION_KEY") or env_values.get("BYOK_ENCRYPTION_KEY") or "")
    database_url = str(env_values.get("DATABASE_URL") or env_values.get("SQLALCHEMY_DATABASE_URI") or "")
    dev_database_url = str(env_values.get("DEV_DATABASE_URL") or "")
    remote_auth_mode = str(env_values.get("VF_REMOTE_AUTH_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}
    official_site_url = str(env_values.get("VF_OFFICIAL_SITE_URL") or "").strip()

    if not secret or "your-secret-key-change-in-production" in secret:
        issues.append("SECRET_KEY 仍是占位值")
    if not byok_key or "base64-32-byte-urlsafe-key" in byok_key:
        issues.append("VIDEOFACTORY_KEY_ENCRYPTION_KEY 仍是占位值")
    if remote_auth_mode:
        if not official_site_url:
            issues.append("VF_OFFICIAL_SITE_URL 不能为空")
        if not dev_database_url.startswith("sqlite:///"):
            issues.append("VF_REMOTE_AUTH_MODE=1 时，DEV_DATABASE_URL 应指向本地 sqlite")
        if database_url:
            issues.append("VF_REMOTE_AUTH_MODE=1 时，不应继续下发 DATABASE_URL")
        return issues

    if not database_url or "USER:PASSWORD@" in database_url:
        issues.append("DATABASE_URL 仍是示例占位值")
        return issues

    try:
        parsed = urlparse(database_url)
        host = str(parsed.hostname or "").strip().lower()
        username = str(parsed.username or "").strip().lower()
        if host in {"localhost", "127.0.0.1", "::1"}:
            issues.append("DATABASE_URL 仍指向 localhost，本地安装包会要求终端用户自带 MySQL，不能直接发布")
        if username == "root":
            issues.append("DATABASE_URL 使用 root 账号，不能随安装包下发")
    except Exception:
        issues.append("DATABASE_URL 解析失败")
    return issues


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree_or_file(source_root: Path, target_root: Path, relative_path: str) -> None:
    source = source_root / relative_path
    target = target_root / relative_path
    if not source.exists():
        return
    if source.is_dir():
        shutil.copytree(
            source,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def render_installer_script(
    template_path: Path,
    output_path: Path,
    dist_root: Path,
    app_display_name: str,
    app_publisher: str,
    exe_name: str,
    app_version: str,
    install_subdir: str,
    output_base_filename: str,
    setup_icon_path: str,
) -> None:
    content = template_path.read_text(encoding="utf-8")
    content = content.replace("__APP_DISPLAY_NAME__", app_display_name)
    content = content.replace("__APP_PUBLISHER__", app_publisher)
    content = content.replace("__APP_VERSION__", app_version)
    content = content.replace("__APP_EXE_NAME__", f"{exe_name}.exe")
    content = content.replace("__INSTALL_SUBDIR__", install_subdir)
    content = content.replace("__OUTPUT_BASE_FILENAME__", output_base_filename)
    content = content.replace("__DIST_ROOT__", str(dist_root).replace("/", "\\"))
    content = content.replace("__SETUP_ICON_FILE__", str(setup_icon_path or "").replace("/", "\\"))
    output_path.write_text(content, encoding="utf-8-sig")


def sanitize_installer_basename(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "").strip()).strip("._-")
    return sanitized or "VideoFactory_Setup"


def build_obfuscated_workspace(source_root: Path, obf_root: Path) -> Path:
    pyarmor_exe = source_root / "venv" / "Scripts" / "pyarmor.exe"
    if not pyarmor_exe.exists():
        raise FileNotFoundError(f"pyarmor not found: {pyarmor_exe}")

    ensure_clean_dir(obf_root)
    for relative_path in OBFUSCATE_COPY_TARGETS:
        copy_tree_or_file(source_root, obf_root, relative_path)

    generated_root = obf_root / "_pyarmor_dist"
    command = [
        str(pyarmor_exe),
        "gen",
        "-O",
        str(generated_root),
        "--mix-str",
        "--assert-call",
        "--assert-import",
    ]
    command.extend([str(source_root / item) for item in PYARMOR_TARGETS])
    env = os.environ.copy()
    env["PYARMOR_HOME"] = str(obf_root / ".pyarmor")
    print("[RUN]", " ".join(str(item) for item in command))
    pyarmor_result = subprocess.run(
        [str(item) for item in command],
        cwd=str(source_root),
        env=env,
        text=True,
        capture_output=True,
    )
    if pyarmor_result.stdout:
        print(pyarmor_result.stdout, end="" if pyarmor_result.stdout.endswith("\n") else "\n")
    if pyarmor_result.stderr:
        print(pyarmor_result.stderr, end="" if pyarmor_result.stderr.endswith("\n") else "\n")
    if pyarmor_result.returncode != 0:
        if not _is_pyarmor_license_limit(pyarmor_result.stdout, pyarmor_result.stderr):
            raise subprocess.CalledProcessError(
                pyarmor_result.returncode,
                [str(item) for item in command],
                output=pyarmor_result.stdout,
                stderr=pyarmor_result.stderr,
            )
        print("PyArmor trial license exhausted, falling back to pyc-only protection for core modules")
        return build_pyc_only_workspace(obf_root)

    for relative_path in PYARMOR_TARGETS:
        generated = generated_root / relative_path
        if not generated.exists():
            continue
        target = obf_root / relative_path
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if generated.is_dir():
            shutil.copytree(generated, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(generated, target)

    for runtime_dir in generated_root.glob("pyarmor_runtime_*"):
        if runtime_dir.is_dir():
            shutil.copytree(runtime_dir, obf_root / runtime_dir.name, dirs_exist_ok=True)

    return obf_root


def _is_pyarmor_license_limit(stdout: str, stderr: str) -> bool:
    output_parts = []
    if stdout:
        output_parts.append(str(stdout))
    if stderr:
        output_parts.append(str(stderr))
    message = "\n".join(output_parts).lower()
    return "out of license" in message or "license" in message


def build_pyc_only_workspace(obf_root: Path) -> Path:
    for relative_path in PYARMOR_TARGETS:
        target = obf_root / relative_path
        if not target.exists() or not target.is_file():
            continue
        pyc_target = target.with_suffix(".pyc")
        py_compile.compile(str(target), cfile=str(pyc_target), doraise=True)
        target.unlink()
    return obf_root


def run_command(command: list[str], env: dict, cwd: Path) -> None:
    print("[RUN]", " ".join(command))
    subprocess.run(command, cwd=str(cwd), env=env, check=True)


def resolve_iscc_exe() -> str:
    command_hit = which("ISCC.exe")
    if command_hit:
        return str(Path(command_hit).resolve())
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 5\ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return ""


def build_inno_installer(installer_script: Path, output_dir: Path) -> Path | None:
    iscc_exe = resolve_iscc_exe()
    if not iscc_exe:
        print("Warning: ISCC.exe not found, skipped installer compilation")
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            iscc_exe,
            f"/O{output_dir}",
            str(installer_script),
        ],
        env=os.environ.copy(),
        cwd=ROOT_DIR,
    )
    installers = sorted(output_dir.glob("*.exe"), key=lambda item: item.stat().st_mtime, reverse=True)
    return installers[0] if installers else None


def ensure_build_dependencies(obfuscate: bool, source_root: Path) -> None:
    missing = []
    for module_name in ("PyInstaller", "webview", "PIL"):
        if importlib.util.find_spec(module_name) is None:
            missing.append(module_name)

    if missing:
        joined = ", ".join(missing)
        raise SystemExit(
            f"当前打包解释器缺少依赖: {joined}。"
            f"请切换到已安装这些依赖的 Python 环境后再执行构建。"
        )

    if obfuscate:
        pyarmor_exe = source_root / "venv" / "Scripts" / "pyarmor.exe"
        if not pyarmor_exe.exists():
            raise SystemExit(f"缺少 PyArmor: {pyarmor_exe}")


def stage_runtime_files(
    dist_root: Path,
    preset_path: Path,
    env_values: dict,
    logo_path: str,
    branding_icon_path: str,
    installer_script: Path,
    app_name: str,
    exe_name: str,
    build_metadata: dict,
) -> None:
    for dir_name in RUNTIME_DIR_NAMES:
        (dist_root / dir_name).mkdir(parents=True, exist_ok=True)

    shutil.copy2(preset_path, dist_root / ".env")
    internal_root = dist_root / "_internal"
    if internal_root.exists():
        shutil.copy2(preset_path, internal_root / ".env")

    branding_dir = dist_root / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)
    if logo_path:
        source = Path(logo_path)
        if source.exists():
            shutil.copy2(source, branding_dir / "logo.png")
    if branding_icon_path:
        icon_source = Path(branding_icon_path)
        if icon_source.exists():
            shutil.copy2(icon_source, branding_dir / "app_icon.ico")

    manifest = {
        "app_name": app_name,
        "exe_name": f"{exe_name}.exe",
        "official_site_url": env_values.get("VF_OFFICIAL_SITE_URL", "https://www.zysj.site"),
        "start_path": env_values.get("VF_START_PATH", "/user"),
        "preset": str(preset_path),
        "runtime_dirs": RUNTIME_DIR_NAMES,
        "installer_script": str(installer_script),
        "build": build_metadata,
    }
    (dist_root / "installer_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_forbidden_release_entries(dist_root: Path) -> list[str]:
    matches: list[str] = []
    if not dist_root.exists():
        return matches
    for path in dist_root.rglob("*"):
        rel = str(path.relative_to(dist_root)).replace("\\", "/")
        lower_rel = rel.lower()
        if any(part in lower_rel for part in RELEASE_FORBIDDEN_NAME_PARTS):
            matches.append(rel)
            continue
        if path.is_file():
            name = path.name
            for pattern in RELEASE_FORBIDDEN_FILE_GLOBS:
                if path.match(pattern) or Path(name).match(pattern):
                    matches.append(rel)
                    break
    return sorted(set(matches))


def ensure_release_output_clean(dist_root: Path) -> None:
    forbidden_entries = find_forbidden_release_entries(dist_root)
    if forbidden_entries:
        preview = "；".join(forbidden_entries[:10])
        raise SystemExit(f"构建已拦截：发布目录包含不应随商用包分发的文件。{preview}")


def minify_release_assets(dist_root: Path) -> None:
    npx_path = which("npx")
    if not npx_path:
        raise SystemExit("构建已拦截：未找到 npx，无法执行前端资源压缩。")
    for relative_path in RELEASE_MINIFY_JS_TARGETS:
        target = dist_root / relative_path
        if not target.exists() or not target.is_file():
            continue
        tmp_path = target.with_suffix(f"{target.suffix}.min")
        command = [
            npx_path,
            "terser",
            str(target),
            "--compress",
            "--mangle",
            "--output",
            str(tmp_path),
        ]
        run_command(command, env=os.environ.copy(), cwd=ROOT_DIR)
        shutil.move(str(tmp_path), str(target))


def safe_git_output(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
    except Exception:
        return ""
    return result.stdout.strip()


def compute_file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def extract_official_draft_fix_revision(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    patterns = [
        r'OFFICIAL_DRAFT_FIX_REVISION\s*=\s*"([^"]+)"',
        r"OFFICIAL_DRAFT_FIX_REVISION\s*=\s*'([^']+)'",
        r'fix_revision"\s*:\s*"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return str(match.group(1) or "").strip()
    return ""


def build_release_metadata(preset_path: Path, installer_script: Path) -> dict:
    official_service = ROOT_DIR / "app" / "services" / "jianying" / "official_draft_replace_service.py"
    git_status = safe_git_output(["status", "--short"])
    return {
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": safe_git_output(["rev-parse", "HEAD"]),
        "git_commit_short": safe_git_output(["rev-parse", "--short", "HEAD"]),
        "git_branch": safe_git_output(["rev-parse", "--abbrev-ref", "HEAD"]),
        "git_dirty": bool(git_status),
        "preset_name": preset_path.name,
        "installer_script_name": installer_script.name,
        "official_draft_service_path": str(official_service),
        "official_draft_service_sha256": compute_file_sha256(official_service),
        "official_draft_fix_revision": extract_official_draft_fix_revision(official_service),
    }


def load_official_draft_templates_from_file(path_text: str) -> list[str]:
    file_path = Path(path_text).resolve()
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    templates: list[str] = []
    for item in payload.get("templates") or []:
        if isinstance(item, dict):
            template_path = str(item.get("path") or "").strip()
        else:
            template_path = str(item or "").strip()
        if template_path:
            templates.append(template_path)
    return templates


def resolve_icon_path(icon_path: str, logo_path: str, output_root: Path) -> str:
    candidate = (icon_path or "").strip()
    fallback_logo = (logo_path or "").strip()
    source = candidate or (str(DEFAULT_BRANDING_ICON) if DEFAULT_BRANDING_ICON.exists() else fallback_logo)
    if not source:
        return ""

    source_path = Path(source)
    if not source_path.exists():
        return ""

    if source_path.suffix.lower() == ".ico":
        return str(source_path.resolve())

    if source_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
        return ""

    icon_output_dir = output_root / "installer_assets"
    icon_output_dir.mkdir(parents=True, exist_ok=True)
    target_path = icon_output_dir / "app_icon.ico"

    image = Image.open(source_path)
    if image.mode not in ("RGBA", "RGB"):
        image = image.convert("RGBA")
    else:
        image = image.copy()
    image.save(target_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return str(target_path.resolve())


def resolve_logo_path(logo_path: str) -> str:
    candidate = (logo_path or "").strip()
    if candidate:
        source_path = Path(candidate)
        if source_path.exists():
            return str(source_path.resolve())
        return ""
    if DEFAULT_BRANDING_LOGO.exists():
        return str(DEFAULT_BRANDING_LOGO.resolve())
    return ""


def build_pyinstaller(
    spec_path: Path,
    dist_parent: Path,
    work_root: Path,
    app_name: str,
    exe_name: str,
    console: bool,
    icon_path: str,
    env_values: dict,
    project_root: Path,
) -> None:
    env = os.environ.copy()
    env.update(env_values)
    env["VF_BUILD_APP_NAME"] = app_name
    env["VF_BUILD_EXE_NAME"] = exe_name
    env["VF_BUILD_CONSOLE"] = "1" if console else "0"
    env["VF_PROJECT_ROOT"] = str(project_root)
    pyinstaller_cache_root = work_root / "pyinstaller-cache"
    pyinstaller_cache_root.mkdir(parents=True, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = str(pyinstaller_cache_root)
    if icon_path:
        env["VF_EXE_ICON"] = icon_path

    upx_path = which("upx")
    if not upx_path:
        try:
            if DEFAULT_WINGET_UPX.exists():
                upx_path = str(DEFAULT_WINGET_UPX)
        except OSError:
            upx_path = ""
    resolved_upx_dir = ""
    if upx_path:
        resolved_upx_dir = str(Path(upx_path).resolve().parent)
        env["VF_ENABLE_UPX"] = "1"

    workpath = work_root / "work"
    dist_parent.mkdir(parents=True, exist_ok=True)
    workpath.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_parent),
        "--workpath",
        str(workpath),
    ]
    if resolved_upx_dir:
        command.extend(["--upx-dir", resolved_upx_dir])
    command.append(str(spec_path))
    run_command(command, env=env, cwd=ROOT_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build VideoFactory desktop onedir bundle")
    parser.add_argument("--preset", default=str(DEFAULT_PRESET), help="env preset file to stage as .env")
    parser.add_argument("--name", default="VideoFactory", help="desktop app name")
    parser.add_argument("--exe-name", default="VideoFactory", help="internal Windows exe file name")
    parser.add_argument("--display-name", default="", help="display name used in installer UI")
    parser.add_argument("--version", default=DEFAULT_APP_VERSION, help="installer version")
    parser.add_argument("--icon", default="", help="optional .ico path for Windows exe")
    parser.add_argument("--logo", default="", help="optional logo asset path to copy into branding/")
    parser.add_argument("--console", action="store_true", help="show console window when launching the desktop app")
    parser.add_argument("--obfuscate", action="store_true", help="build from a PyArmor-obfuscated workspace")
    parser.add_argument("--skip-precheck", action="store_true", help="skip scripts/prepackage_check.py")
    parser.add_argument("--skip-build", action="store_true", help="skip PyInstaller build and only stage installer assets")
    parser.add_argument(
        "--official-draft-template",
        action="append",
        default=[],
        help="absolute path to an official draft template to include in prepackage regression; may be repeated",
    )
    parser.add_argument(
        "--official-draft-template-file",
        action="append",
        default=[],
        help="JSON file containing official draft templates to include in prepackage regression; may be repeated",
    )
    parser.add_argument(
        "--use-default-official-drafts",
        action="store_true",
        help=f"load release-blocking official draft templates from {DEFAULT_OFFICIAL_DRAFT_TEMPLATE_FILE}",
    )
    parser.add_argument("--dry-run", action="store_true", help="print resolved config and exit")
    args = parser.parse_args()

    preset_path = Path(args.preset).resolve()
    if not preset_path.exists():
        raise FileNotFoundError(f"preset not found: {preset_path}")
    if not DEFAULT_SPEC.exists():
        raise FileNotFoundError(f"spec not found: {DEFAULT_SPEC}")

    env_values = read_env_file(preset_path)
    official_draft_templates = list(args.official_draft_template)
    template_files = [Path(item).resolve() for item in args.official_draft_template_file]
    if args.use_default_official_drafts:
        template_files.append(DEFAULT_OFFICIAL_DRAFT_TEMPLATE_FILE)
    for template_file in template_files:
        if not template_file.exists():
            raise FileNotFoundError(f"official draft template file not found: {template_file}")
        official_draft_templates.extend(load_official_draft_templates_from_file(str(template_file)))
    deduped_templates = []
    seen_templates = set()
    for item in official_draft_templates:
        normalized = os.path.normcase(os.path.normpath(str(item)))
        if normalized in seen_templates:
            continue
        seen_templates.add(normalized)
        deduped_templates.append(str(item))
    official_draft_templates = deduped_templates

    dist_parent = ROOT_DIR / "build" / "release"
    dist_root = dist_parent / args.name
    work_root = ROOT_DIR / "build" / "pyinstaller"
    obf_root = ROOT_DIR / "build" / "obfuscated"
    installer_script = ROOT_DIR / "build" / "installer" / f"{args.name}_setup.iss"
    installer_output_dir = ROOT_DIR / "build" / "installer" / "output"
    resolved_logo = resolve_logo_path(args.logo)
    resolved_icon = resolve_icon_path(args.icon, resolved_logo, ROOT_DIR / "build")
    display_name = str(args.display_name or "").strip() or args.name
    installer_output_base = f"{sanitize_installer_basename(args.name)}_{args.version}"

    if args.dry_run:
        payload = {
            "preset": str(preset_path),
            "name": args.name,
            "dist_root": str(dist_root),
            "exe_name": args.exe_name,
            "display_name": display_name,
            "version": args.version,
            "work_root": str(work_root),
            "obf_root": str(obf_root),
            "icon": args.icon,
            "resolved_icon": resolved_icon,
              "logo": resolved_logo,
            "console": args.console,
            "obfuscate": args.obfuscate,
            "official_draft_templates": official_draft_templates,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    env = os.environ.copy()
    env.update(env_values)
    ensure_build_dependencies(args.obfuscate, ROOT_DIR)

    issues = validate_release_env_values(env_values)
    if issues:
        joined = "；".join(issues)
        if args.skip_precheck:
            print(f"Warning: 当前 preset 仍含占位值，适合演练 staging，不适合正式打包。{joined}")
        else:
            raise SystemExit(f"构建已拦截：当前 preset 仍含占位值。{joined}")

    if not args.skip_precheck:
        precheck_command = [sys.executable, str(ROOT_DIR / "scripts" / "prepackage_check.py")]
        for template_path in official_draft_templates:
            precheck_command.extend(["--official-draft-template", template_path])
        run_command(precheck_command, env=env, cwd=ROOT_DIR)

    if not args.skip_build:
        ensure_clean_dir(dist_parent)
        ensure_clean_dir(work_root)
        if args.obfuscate:
            ensure_clean_dir(obf_root)
    else:
        dist_root.mkdir(parents=True, exist_ok=True)
        work_root.mkdir(parents=True, exist_ok=True)
    ensure_clean_dir(installer_script.parent)

    if not args.skip_build:
        build_root = ROOT_DIR
        if args.obfuscate:
            build_root = build_obfuscated_workspace(ROOT_DIR, obf_root)
        build_pyinstaller(
            spec_path=DEFAULT_SPEC,
            dist_parent=dist_parent,
            work_root=work_root,
            app_name=args.name,
            exe_name=args.exe_name,
            console=args.console,
            icon_path=resolved_icon,
            env_values=env_values,
            project_root=build_root,
        )

    render_installer_script(
        template_path=DEFAULT_INSTALLER_TEMPLATE,
        output_path=installer_script,
        dist_root=dist_root,
        app_display_name=display_name,
        app_publisher=display_name,
        exe_name=args.exe_name,
        app_version=args.version,
        install_subdir=display_name,
        output_base_filename=installer_output_base,
        setup_icon_path=resolved_icon,
    )
    build_metadata = build_release_metadata(preset_path, installer_script)
    stage_runtime_files(
        dist_root=dist_root,
        preset_path=preset_path,
        env_values=env_values,
        logo_path=resolved_logo,
        branding_icon_path=resolved_icon,
        installer_script=installer_script,
        app_name=args.name,
        exe_name=args.exe_name,
        build_metadata=build_metadata,
    )
    minify_release_assets(dist_root)
    ensure_release_output_clean(dist_root)
    installer_binary = build_inno_installer(installer_script, installer_output_dir)

    print("")
    print("Desktop bundle prep completed")
    print(f"Bundle root: {dist_root}")
    print(f"Installer script: {installer_script}")
    if installer_binary:
        print(f"Installer exe: {installer_binary}")
    if resolved_icon:
        print(f"Exe icon: {resolved_icon}")


if __name__ == "__main__":
    main()
