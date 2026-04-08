import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = ROOT_DIR / "build" / "stable_releases"
DEFAULT_RELEASE_ROOT = ROOT_DIR / "build" / "release"


def safe_git_output(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def copy_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)
    return True


def main():
    parser = argparse.ArgumentParser(description="Archive a stable desktop release with manifest and git metadata")
    parser.add_argument("--version", required=True, help="stable version label, for example v1.0.1")
    parser.add_argument("--release-name", required=True, help="bundle directory name under build/release")
    parser.add_argument("--portable-zip", default="", help="optional portable zip path to archive")
    parser.add_argument("--installer-exe", default="", help="optional installer exe path to archive")
    parser.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT), help="archive root directory")
    parser.add_argument("--tag", action="store_true", help="create an annotated stable/<version> tag")
    args = parser.parse_args()

    release_root = DEFAULT_RELEASE_ROOT / args.release_name
    manifest_path = release_root / "installer_manifest.json"
    if not release_root.exists():
        raise SystemExit(f"release bundle not found: {release_root}")
    if not manifest_path.exists():
        raise SystemExit(f"installer manifest not found: {manifest_path}")

    archive_root = Path(args.archive_root).resolve()
    archive_dir = archive_root / args.version
    archive_dir.mkdir(parents=True, exist_ok=True)

    copied = {
        "bundle": copy_if_exists(release_root, archive_dir / release_root.name),
        "manifest": copy_if_exists(manifest_path, archive_dir / "installer_manifest.json"),
    }

    portable_zip = Path(args.portable_zip).resolve() if args.portable_zip else None
    if portable_zip:
        copied["portable_zip"] = copy_if_exists(portable_zip, archive_dir / portable_zip.name)

    installer_exe = Path(args.installer_exe).resolve() if args.installer_exe else None
    if installer_exe:
        copied["installer_exe"] = copy_if_exists(installer_exe, archive_dir / installer_exe.name)

    tag_name = f"stable/{args.version}"
    tag_created = False
    if args.tag:
        existing_tag = safe_git_output(["tag", "--list", tag_name])
        if existing_tag != tag_name:
            subprocess.run(
                ["git", "tag", "-a", tag_name, "-m", f"stable {args.version}"],
                cwd=str(ROOT_DIR),
                check=True,
            )
            tag_created = True

    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive_report = {
        "version": args.version,
        "tag_name": tag_name,
        "tag_created": tag_created,
        "git_commit": safe_git_output(["rev-parse", "HEAD"]),
        "git_branch": safe_git_output(["rev-parse", "--abbrev-ref", "HEAD"]),
        "archived_at_local": datetime.now().isoformat(),
        "source_release_root": str(release_root),
        "archive_dir": str(archive_dir),
        "copied": copied,
        "build_manifest": manifest_payload,
    }
    (archive_dir / "archive_report.json").write_text(
        json.dumps(archive_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(archive_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
