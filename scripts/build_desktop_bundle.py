import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from shutil import which
from urllib.parse import urlparse

from PIL import Image


ROOT_DIR = Path(__file__).resolve().parents[1]
PACKAGING_DIR = ROOT_DIR / "packaging"
DEFAULT_PRESET = ROOT_DIR / "env.presets" / "desktop_full.env.example"
DEFAULT_SPEC = PACKAGING_DIR / "video_factory_desktop.spec"
DEFAULT_INSTALLER_TEMPLATE = PACKAGING_DIR / "video_factory_installer.iss"
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
]

RUNTIME_DIR_NAMES = [
    "logs",
    "user_data",
    "runtime_tools",
    "duo_cache",
    "mcp_cache",
]


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
    app_name: str,
    exe_name: str,
) -> None:
    content = template_path.read_text(encoding="utf-8")
    content = content.replace("__APP_NAME__", app_name)
    content = content.replace("__APP_EXE_NAME__", f"{exe_name}.exe")
    content = content.replace("__DIST_ROOT__", str(dist_root).replace("/", "\\"))
    output_path.write_text(content, encoding="utf-8")


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
    run_command([str(item) for item in command], env=env, cwd=source_root)

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


def run_command(command: list[str], env: dict, cwd: Path) -> None:
    print("[RUN]", " ".join(command))
    subprocess.run(command, cwd=str(cwd), env=env, check=True)


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
    installer_script: Path,
    exe_name: str,
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
            shutil.copy2(source, branding_dir / source.name)

    manifest = {
        "app_name": dist_root.name,
        "exe_name": f"{exe_name}.exe",
        "official_site_url": env_values.get("VF_OFFICIAL_SITE_URL", "https://www.zysj.site"),
        "start_path": env_values.get("VF_START_PATH", "/user"),
        "preset": str(preset_path),
        "runtime_dirs": RUNTIME_DIR_NAMES,
        "installer_script": str(installer_script),
    }
    (dist_root / "installer_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def resolve_icon_path(icon_path: str, logo_path: str, output_root: Path) -> str:
    candidate = (icon_path or "").strip()
    fallback_logo = (logo_path or "").strip()
    source = candidate or fallback_logo
    if not source:
        return ""

    source_path = Path(source)
    if not source_path.exists():
        return ""

    if source_path.suffix.lower() == ".ico":
        return str(source_path)

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
    return str(target_path)


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
    parser.add_argument("--icon", default="", help="optional .ico path for Windows exe")
    parser.add_argument("--logo", default="", help="optional logo asset path to copy into branding/")
    parser.add_argument("--console", action="store_true", help="show console window when launching the desktop app")
    parser.add_argument("--obfuscate", action="store_true", help="build from a PyArmor-obfuscated workspace")
    parser.add_argument("--skip-precheck", action="store_true", help="skip scripts/prepackage_check.py")
    parser.add_argument("--skip-build", action="store_true", help="skip PyInstaller build and only stage installer assets")
    parser.add_argument("--dry-run", action="store_true", help="print resolved config and exit")
    args = parser.parse_args()

    preset_path = Path(args.preset).resolve()
    if not preset_path.exists():
        raise FileNotFoundError(f"preset not found: {preset_path}")
    if not DEFAULT_SPEC.exists():
        raise FileNotFoundError(f"spec not found: {DEFAULT_SPEC}")

    env_values = read_env_file(preset_path)
    dist_parent = ROOT_DIR / "build" / "release"
    dist_root = dist_parent / args.name
    work_root = ROOT_DIR / "build" / "pyinstaller"
    obf_root = ROOT_DIR / "build" / "obfuscated"
    installer_script = ROOT_DIR / "build" / "installer" / f"{args.name}_setup.iss"
    resolved_icon = resolve_icon_path(args.icon, args.logo, ROOT_DIR / "build")

    if args.dry_run:
        payload = {
            "preset": str(preset_path),
            "name": args.name,
            "dist_root": str(dist_root),
            "exe_name": args.exe_name,
            "work_root": str(work_root),
            "obf_root": str(obf_root),
            "icon": args.icon,
            "resolved_icon": resolved_icon,
            "logo": args.logo,
            "console": args.console,
            "obfuscate": args.obfuscate,
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
        run_command([sys.executable, str(ROOT_DIR / "scripts" / "prepackage_check.py")], env=env, cwd=ROOT_DIR)

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
        app_name=args.name,
        exe_name=args.exe_name,
    )
    stage_runtime_files(
        dist_root=dist_root,
        preset_path=preset_path,
        env_values=env_values,
        logo_path=args.logo,
        installer_script=installer_script,
        exe_name=args.exe_name,
    )

    print("")
    print("Desktop bundle prep completed")
    print(f"Bundle root: {dist_root}")
    print(f"Installer script: {installer_script}")
    if resolved_icon:
        print(f"Exe icon: {resolved_icon}")


if __name__ == "__main__":
    main()
