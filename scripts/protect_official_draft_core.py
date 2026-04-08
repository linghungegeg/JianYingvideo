import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT_DIR / "build" / "protected_official_draft_core"
CORE_TARGETS = [
    "app/services/jianying/official_draft_codec.py",
    "app/services/jianying/draft_replacement_strategy.py",
]
PYARMOR_CANDIDATES = [
    Path(sys.executable).resolve().parent / "pyarmor.exe",
    ROOT_DIR / "venv312" / "Scripts" / "pyarmor.exe",
    ROOT_DIR / "venv" / "Scripts" / "pyarmor.exe",
]


def find_pyarmor() -> Path:
    for candidate in PYARMOR_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("pyarmor.exe not found in venv or venv312")


def run_command(command: list[str], cwd: Path, env: dict | None = None) -> None:
    print("[RUN]", " ".join(str(item) for item in command))
    subprocess.run(command, cwd=str(cwd), env=env, check=True)


def materialize_relative_targets(output_root: Path) -> list[str]:
    generated_targets: list[str] = []
    for relative_path in CORE_TARGETS:
        flat_file = output_root / Path(relative_path).name
        if not flat_file.exists():
            continue
        target_path = output_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            target_path.unlink()
        shutil.move(str(flat_file), str(target_path))
        generated_targets.append(str(target_path.resolve()))
    return generated_targets


def overlay_targets_into_workspace(output_root: Path, workspace_root: Path) -> list[str]:
    copied_paths: list[str] = []
    for relative_path in CORE_TARGETS:
        source_path = output_root / relative_path
        if not source_path.exists():
            continue
        target_path = workspace_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied_paths.append(str(target_path.resolve()))

    for runtime_dir in output_root.glob("pyarmor_runtime_*"):
        if not runtime_dir.is_dir():
            continue
        target_runtime_dir = workspace_root / runtime_dir.name
        shutil.copytree(runtime_dir, target_runtime_dir, dirs_exist_ok=True)
        copied_paths.append(str(target_runtime_dir.resolve()))
    return copied_paths


def build_command(pyarmor_exe: Path, output_root: Path, mode: str) -> list[str]:
    command = [str(pyarmor_exe), "gen", "-O", str(output_root)]
    if mode == "full":
        command.extend(["--mix-str", "--assert-call", "--assert-import"])
    command.extend(str(ROOT_DIR / item) for item in CORE_TARGETS)
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description="Protect official draft core modules with local PyArmor.")
    parser.add_argument("-O", "--output", default=str(DEFAULT_OUTPUT), help="output directory")
    parser.add_argument("--clean", action="store_true", help="remove output directory before generation")
    parser.add_argument("--no-mix-str", action="store_true", help="disable --mix-str")
    parser.add_argument("--no-assert-call", action="store_true", help="disable --assert-call")
    parser.add_argument("--no-assert-import", action="store_true", help="disable --assert-import")
    parser.add_argument("--overlay-into", default="", help="copy protected targets into an existing workspace")
    args = parser.parse_args()

    output_root = Path(args.output).resolve()
    if args.clean and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    pyarmor_exe = find_pyarmor()
    env = os.environ.copy()
    env["PYARMOR_HOME"] = str(output_root / ".pyarmor")
    requested_mode = "minimal" if (args.no_mix_str and args.no_assert_call and args.no_assert_import) else "full"
    effective_mode = requested_mode
    try:
        run_command(build_command(pyarmor_exe, output_root, requested_mode), cwd=ROOT_DIR, env=env)
    except subprocess.CalledProcessError:
        if requested_mode != "full":
            raise
        print("[WARN] full PyArmor mode failed, retrying with minimal flags")
        effective_mode = "minimal"
        if output_root.exists():
            shutil.rmtree(output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        env["PYARMOR_HOME"] = str(output_root / ".pyarmor")
        run_command(build_command(pyarmor_exe, output_root, effective_mode), cwd=ROOT_DIR, env=env)

    runtime_dirs = sorted(path.name for path in output_root.glob("pyarmor_runtime_*") if path.is_dir())
    generated_targets = materialize_relative_targets(output_root)
    print(f"Protection mode: {effective_mode}")
    print("Protected targets:")
    for item in generated_targets:
        print(f"  - {item}")
    print("Runtime dirs:")
    for item in runtime_dirs:
        print(f"  - {item}")

    overlay_root_text = str(args.overlay_into or "").strip()
    if overlay_root_text:
        overlay_root = Path(overlay_root_text).resolve()
        overlay_root.mkdir(parents=True, exist_ok=True)
        copied_paths = overlay_targets_into_workspace(output_root, overlay_root)
        print("Overlay copied into workspace:")
        for item in copied_paths:
            print(f"  - {item}")


if __name__ == "__main__":
    sys.exit(main())
