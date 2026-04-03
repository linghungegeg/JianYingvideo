import argparse
import json
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path


def quiet_subprocess_kwargs() -> dict:
    kwargs = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    use_show_window = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    show_window_hidden = getattr(subprocess, "SW_HIDE", 0)
    if startupinfo_cls and use_show_window:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= use_show_window
        startupinfo.wShowWindow = show_window_hidden
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _cdp_http_json(cdp_url: str, path: str):
    endpoint = urllib.parse.urljoin(cdp_url.rstrip("/") + "/", path.lstrip("/"))
    with urllib.request.urlopen(endpoint, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def wait_for_cdp_page(cdp_url: str, timeout_s: float) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            targets = _cdp_http_json(cdp_url, "/json/list")
        except Exception:
            time.sleep(0.25)
            continue
        for target in targets:
            if not isinstance(target, dict):
                continue
            ws_url = str(target.get("webSocketDebuggerUrl") or "").strip()
            if target.get("type") == "page" and ws_url:
                return target
        time.sleep(0.25)
    raise TimeoutError("timed out waiting for GG CDP page target")


def invoke_pre_replace_via_cdp(cdp_url: str, info_path: str, replace_types: list[str], timeout_s: float = 20.0):
    target = wait_for_cdp_page(cdp_url, timeout_s=timeout_s)
    ws_url = str(target.get("webSocketDebuggerUrl") or "").strip()
    payload = {
        "infoPath": str(info_path),
        "replaceTypes": list(replace_types),
    }
    expression = f"(async()=>await window.electronAPI.preReplaceMaterial({json.dumps(payload, ensure_ascii=False)}))()"
    node_script = r"""
const wsUrl = process.argv[1];
const expression = process.argv[2];
const timeoutMs = Number(process.argv[3] || "20000");
const ws = new WebSocket(wsUrl);
let done = false;
const timer = setTimeout(() => {
  if (done) return;
  done = true;
  try { ws.close(); } catch {}
  console.error("cdp Runtime.evaluate timeout");
  process.exit(3);
}, timeoutMs);
ws.addEventListener("open", () => {
  ws.send(JSON.stringify({
    id: 1,
    method: "Runtime.evaluate",
    params: { expression, awaitPromise: true, returnByValue: true }
  }));
});
ws.addEventListener("message", (event) => {
  let msg;
  try { msg = JSON.parse(event.data); } catch { return; }
  if (msg.id !== 1 || done) return;
  done = true;
  clearTimeout(timer);
  if (msg.error) {
    console.error(JSON.stringify(msg.error));
    process.exit(4);
  }
  const result = msg.result || {};
  if (result.exceptionDetails) {
    console.error(JSON.stringify(result.exceptionDetails));
    process.exit(5);
  }
  process.stdout.write(JSON.stringify((result.result || {}).value ?? null));
  try { ws.close(); } catch {}
});
ws.addEventListener("error", (event) => {
  if (done) return;
  done = true;
  clearTimeout(timer);
  console.error(event && event.message ? event.message : "websocket error");
  process.exit(6);
});
"""
    result = subprocess.run(
        ["node", "-e", node_script, ws_url, expression, str(int(timeout_s * 1000))],
        capture_output=True,
        check=False,
        **quiet_subprocess_kwargs(),
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or b"").decode("utf-8", errors="ignore").strip() or "CDP Runtime.evaluate failed")
    return json.loads((result.stdout or b"").decode("utf-8", errors="ignore") or "null")


def capture_cppreader_process(timeout_s: float = 8.0) -> dict:
    script = r"""
$rows = Get-CimInstance Win32_Process | Where-Object { $_.Name -ieq 'cppreader.exe' } |
  Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine
$rows | ConvertTo-Json -Compress
"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            check=False,
            **quiet_subprocess_kwargs(),
        )
        text = (result.stdout or b"").decode("utf-8", errors="ignore").strip()
        if text and text not in {"null", "[]"}:
            try:
                payload = json.loads(text)
                if isinstance(payload, dict):
                    return {"matches": [payload]}
                if isinstance(payload, list):
                    return {"matches": payload}
            except Exception:
                pass
        time.sleep(0.01)
    return {"matches": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture real cppreader.exe process metadata during GG preReplaceMaterial")
    parser.add_argument("source_info_path")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument("--report-json", default="")
    parser.add_argument("--replace-types", nargs="+", default=["video", "photo", "gif"])
    args = parser.parse_args()

    report = {
        "source_info_path": str(Path(args.source_info_path).resolve()),
        "cdp_url": args.cdp_url,
        "replace_types": list(args.replace_types),
        "pre_replace_result": None,
        "cppreader_process": {"matches": []},
    }

    holder = {}

    def watcher():
        holder["cppreader_process"] = capture_cppreader_process(timeout_s=8.0)

    thread = threading.Thread(target=watcher, daemon=True)
    thread.start()
    report["pre_replace_result"] = invoke_pre_replace_via_cdp(args.cdp_url, report["source_info_path"], list(args.replace_types))
    thread.join(timeout=9.0)
    report["cppreader_process"] = holder.get("cppreader_process") or {"matches": []}

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report_json:
        path = Path(args.report_json).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
