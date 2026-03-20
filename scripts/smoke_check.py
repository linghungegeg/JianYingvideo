import json
from pathlib import Path


def check_file(path: Path, keywords):
    text = path.read_text(encoding="utf-8", errors="ignore")
    missing = [k for k in keywords if k not in text]
    return missing


def main():
    base = Path(".")
    files = [
        ("app/templates/user/index.html", ["duo_category", "duo_results", "duo_cache_info", "duo_params"]),
        ("app/services/duo_video_service.py", ["DuoVideoService", "search", "count"]),
        ("app/tasks.py", ["_apply_mcp_effects", "duo_config"]),
    ]
    for f, keys in files:
        p = base / f
        if not p.exists():
            print(f"[FAIL] missing file: {f}")
            continue
        missing = check_file(p, keys)
        if missing:
            print(f"[FAIL] {f} missing tokens: {missing}")
        else:
            print(f"[OK] {f}")

    # validate resources.json shape if present
    res = base / "app/utils/duo_resources/resources.json"
    if res.exists():
        data = json.loads(res.read_text(encoding="utf-8", errors="ignore"))
        items = data.get("items", [])
        print(f"[OK] resources.json items={len(items)}")
    else:
        print("[WARN] resources.json not found")


if __name__ == "__main__":
    main()
