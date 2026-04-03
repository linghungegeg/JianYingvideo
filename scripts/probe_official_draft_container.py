import argparse
import base64
import json
import sys
from pathlib import Path


def scan_offsets(raw: bytes, needle: bytes) -> list[int]:
    offsets: list[int] = []
    start = 0
    while True:
        idx = raw.find(needle, start)
        if idx < 0:
            return offsets
        offsets.append(idx)
        start = idx + 1


def printable_ratio(raw: bytes) -> float:
    if not raw:
        return 0.0
    printable = 0
    for b in raw:
        if 32 <= b < 127:
            printable += 1
    return printable / len(raw)


def build_report(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    raw = base64.b64decode(text + "===")

    interesting = {
        "json_brace_offsets": scan_offsets(raw, b"{")[:20],
        "json_bracket_offsets": scan_offsets(raw, b"[")[:20],
        "gzip_magic_offsets": scan_offsets(raw, b"\x1f\x8b")[:20],
        "zlib_789c_offsets": scan_offsets(raw, b"\x78\x9c")[:20],
        "zlib_78da_offsets": scan_offsets(raw, b"\x78\xda")[:20],
    }

    sample_offsets = sorted(
        {
            0,
            *interesting["json_brace_offsets"][:3],
            *interesting["json_bracket_offsets"][:3],
            *interesting["gzip_magic_offsets"][:3],
        }
    )

    samples = []
    for offset in sample_offsets:
        start = max(0, offset - 32)
        end = min(len(raw), offset + 96)
        chunk = raw[start:end]
        samples.append(
            {
                "offset": offset,
                "range": [start, end],
                "hex": chunk.hex(),
                "utf8": chunk.decode("utf-8", errors="ignore"),
            }
        )

    return {
        "path": str(path),
        "text_length": len(text),
        "base64_length": len(raw),
        "base64_mod_16": len(raw) % 16,
        "base64_head": text[:120],
        "base64_head_hex": raw[:64].hex(),
        "base64_tail_hex": raw[-64:].hex(),
        "base64_printable_ratio": printable_ratio(raw),
        "interesting_offsets": interesting,
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe encoded official draft container structure")
    parser.add_argument("draft_content_path", help="path to draft_content.json")
    parser.add_argument("--report-json", default="", help="optional output path for report JSON")
    args = parser.parse_args()

    path = Path(args.draft_content_path).resolve()
    report = build_report(path)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write((rendered + "\n").encode("utf-8", errors="ignore"))

    if args.report_json:
        out = Path(args.report_json).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
