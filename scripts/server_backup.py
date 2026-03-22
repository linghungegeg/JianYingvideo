import argparse
import os
import tarfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "backups" / "server"
DEFAULT_ITEMS = [
    "app",
    "migrations",
    "docs",
    "requirements.server.txt",
    "requirements.txt",
    "config.py",
    "run.py",
    "wsgi.py",
    "env.presets",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a timestamped server backup archive")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--include-env", action="store_true", help="include local .env if present")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = output_dir / f"videofactory_server_backup_{stamp}.tar.gz"

    items = list(DEFAULT_ITEMS)
    if args.include_env and (ROOT / ".env").exists():
        items.append(".env")

    with tarfile.open(archive_path, "w:gz") as tar:
        for relative in items:
            source = ROOT / relative
            if not source.exists():
                continue
            tar.add(source, arcname=relative)

    print(archive_path)


if __name__ == "__main__":
    main()

