import argparse
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from app.services.jianying.official_draft_replace_service import replace_official_draft


JSON_TARGETS = {"draft_content.json", "template.json", "template.tmp"}
PREFIXES = ("materials/", "video/cover/")


def collect_refs(payload):
    refs = []

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for value in node:
                walk(value)
            return
        if isinstance(node, str):
            normalized = node.replace("\\", "/")
            if normalized.startswith(PREFIXES):
                refs.append(normalized)

    walk(payload)
    return sorted(set(refs))


def classify_ref(ref):
    normalized = ref.lower()
    if normalized.startswith("video/cover/") or "_water_mark" in normalized or "cover_" in normalized:
        return "cover"
    if normalized.startswith("materials/audio/"):
        return "audio"
    if normalized.startswith("materials/video/"):
        return "video"
    if normalized.startswith("materials/beat/"):
        return "beat"
    return "other"


def scan_generated_files(draft_root):
    per_file = {}
    category_counter = Counter()
    total_missing = 0
    unreadable = []

    for root, _, files in os.walk(draft_root):
        for filename in files:
            if filename.lower() not in JSON_TARGETS:
                continue
            path = Path(root) / filename
            rel_path = str(path.relative_to(draft_root))
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                unreadable.append({"path": rel_path, "error": str(exc)})
                continue

            refs = collect_refs(payload)
            missing = []
            for ref in refs:
                ref_path = draft_root / Path(ref.replace("/", os.sep))
                if not ref_path.exists():
                    missing.append(ref)
                    category_counter[classify_ref(ref)] += 1
            total_missing += len(missing)
            per_file[rel_path] = {
                "ref_count": len(refs),
                "missing_count": len(missing),
                "missing_refs": missing,
            }

    return {
        "files": per_file,
        "unreadable_files": unreadable,
        "total_missing_refs": total_missing,
        "missing_by_category": dict(sorted(category_counter.items())),
    }


def build_output_dir(output_root, template_path):
    safe_name = template_path.name.replace(" ", "_")
    return output_root / f"probe_{safe_name}"


def run_probe(template_path, output_root, keep_output):
    draft_output = build_output_dir(output_root, template_path)
    if draft_output.exists():
        shutil.rmtree(draft_output)

    result = replace_official_draft(str(template_path), str(draft_output))
    scan = scan_generated_files(draft_output)
    probe = {
        "template_path": str(template_path),
        "output_path": str(draft_output),
        "service_result": result,
        "scan": scan,
        "ok": scan["total_missing_refs"] == 0 and not scan["unreadable_files"],
    }

    if not keep_output:
        shutil.rmtree(draft_output, ignore_errors=True)
    return probe


def main():
    parser = argparse.ArgumentParser(description="Run official draft regression probes against known templates")
    parser.add_argument(
        "--template",
        action="append",
        dest="templates",
        default=[],
        help="absolute path to a source draft template; may be repeated",
    )
    parser.add_argument(
        "--output-root",
        default=str(ROOT_DIR / "build" / "official_draft_regression"),
        help="directory for temporary generated drafts and reports",
    )
    parser.add_argument("--keep-output", action="store_true", help="keep generated probe drafts on disk")
    parser.add_argument("--report-json", default="", help="optional path to write the combined JSON report")
    args = parser.parse_args()

    template_paths = [Path(item).resolve() for item in args.templates]
    if not template_paths:
        raise SystemExit("No templates provided. Use --template at least once.")

    missing_inputs = [str(path) for path in template_paths if not path.exists()]
    if missing_inputs:
        raise SystemExit(f"Template paths not found: {', '.join(missing_inputs)}")

    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    app = create_app()
    with app.app_context():
        probes = [run_probe(path, output_root, args.keep_output) for path in template_paths]

    report = {
        "probe_count": len(probes),
        "failed_count": sum(0 if item["ok"] else 1 for item in probes),
        "probes": probes,
    }

    if args.report_json:
        report_path = Path(args.report_json).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["failed_count"] else 0)


if __name__ == "__main__":
    main()
