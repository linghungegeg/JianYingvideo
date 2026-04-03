import argparse
import hashlib
import json
import shutil
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


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def patch_trial_time(config_path: Path, min_value: int = 5) -> tuple[dict, dict]:
    original = load_json(config_path)
    patched = dict(original)
    if int(patched.get("t") or 0) < min_value:
        patched["t"] = min_value
        save_json(config_path, patched)
    return original, patched


def restore_config(config_path: Path, original: dict) -> None:
    save_json(config_path, original)


def decrypt_rec(rec_path: Path, k6: str) -> str:
    rec_text = rec_path.read_text(encoding="utf-8", errors="ignore").strip()
    cipher_bytes = bytes.fromhex(rec_text)
    key = hashlib.md5(str(k6).encode("utf-8")).digest()
    try:
        from Crypto.Cipher import AES  # type: ignore

        plain = AES.new(key, AES.MODE_ECB).decrypt(cipher_bytes)
    except Exception:
        node_script = """
const crypto = require('crypto');
const payload = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const cipherHex = payload.cipherHex;
const keyHex = payload.keyHex;
const decipher = crypto.createDecipheriv('aes-128-ecb', Buffer.from(keyHex, 'hex'), null);
decipher.setAutoPadding(false);
const out = Buffer.concat([decipher.update(Buffer.from(cipherHex, 'hex')), decipher.final()]);
process.stdout.write(out.toString('utf8'));
"""
        result = subprocess.run(
            ["node", "-e", node_script],
            input=json.dumps({"cipherHex": rec_text, "keyHex": key.hex()}, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            check=False,
            **quiet_subprocess_kwargs(),
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or b"").decode("utf-8", errors="ignore").strip() or "node AES decrypt failed")
        return (result.stdout or b"").decode("utf-8", errors="ignore").rstrip("\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\r\x10")
    return plain.rstrip(b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\r\x10").decode("utf-8", errors="ignore")


def wait_for_page(browser, timeout_s: float):
    raise NotImplementedError


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
    if not ws_url:
        raise RuntimeError("CDP target missing webSocketDebuggerUrl")

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
    params: {
      expression,
      awaitPromise: true,
      returnByValue: true
    }
  }));
});
ws.addEventListener("message", (event) => {
  let msg;
  try {
    msg = JSON.parse(event.data);
  } catch (err) {
    return;
  }
  if (msg.id !== 1) return;
  if (done) return;
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


def capture_rec_during(call_fn, source_info_path: Path, rec_copy_path: Path, timeout_s: float = 8.0) -> tuple[object, dict]:
    rec_path = Path(str(source_info_path) + ".rec")
    capture = {
        "rec_path": str(rec_path),
        "captured": False,
        "capture_copy_path": str(rec_copy_path),
        "first_seen_at": None,
        "capture_error": "",
    }
    stop_flag = {"stop": False}

    def watcher():
        deadline = time.time() + timeout_s
        while time.time() < deadline and not stop_flag["stop"]:
            try:
                if rec_path.exists():
                    rec_copy_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(rec_path, rec_copy_path)
                    capture["captured"] = True
                    capture["first_seen_at"] = time.time()
                    return
            except Exception as exc:
                capture["capture_error"] = str(exc)
                return
            time.sleep(0.01)

    thread = threading.Thread(target=watcher, daemon=True)
    thread.start()
    try:
        result = call_fn()
        return result, capture
    finally:
        stop_flag["stop"] = True
        thread.join(timeout=1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a real GG runtime .rec and decrypted payload via CDP")
    parser.add_argument("source_info_path", help="official draft draft_content.json path")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222", help="CDP endpoint")
    parser.add_argument(
        "--config-path",
        default=str(Path.home() / "AppData" / "Roaming" / "gg-jy-assistant" / "config.json"),
        help="GG roaming config path",
    )
    parser.add_argument("--launch-exe", default="", help="optional GG exe path to launch with remote debugging")
    parser.add_argument("--launch-wait-s", type=float, default=6.0, help="wait after launch")
    parser.add_argument(
        "--replace-types",
        nargs="+",
        default=["video", "photo", "gif"],
        help="replaceTypes to pass to preReplaceMaterial",
    )
    parser.add_argument("--rec-out", default="", help="copy captured .rec to this path")
    parser.add_argument("--json-out", default="", help="write decrypted JSON to this path")
    parser.add_argument("--report-json", default="", help="write execution report to this path")
    args = parser.parse_args()

    source_info_path = Path(args.source_info_path).resolve()
    config_path = Path(args.config_path).resolve()
    rec_out = Path(args.rec_out).resolve() if args.rec_out else Path("build/reverse_capture/runtime_capture.rec").resolve()
    json_out = Path(args.json_out).resolve() if args.json_out else Path("build/reverse_capture/runtime_capture.decrypted_utf8.json").resolve()
    report_json = Path(args.report_json).resolve() if args.report_json else Path("build/reverse_capture/runtime_capture.report.json").resolve()

    report = {
        "source_info_path": str(source_info_path),
        "config_path": str(config_path),
        "cdp_url": args.cdp_url,
        "replace_types": list(args.replace_types),
        "launch_exe": args.launch_exe,
        "pre_replace_result": None,
        "rec_capture": {},
        "decrypt": {"ok": False, "json_out": str(json_out), "error": ""},
    }

    original_config, patched_config = patch_trial_time(config_path)
    report["config_snapshot"] = {
        "t_before": original_config.get("t"),
        "t_during": patched_config.get("t"),
        "k6": patched_config.get("k6"),
        "g6_prefix": str(patched_config.get("g6") or "")[:10],
    }

    launched_proc = None
    try:
        if args.launch_exe:
            launched_proc = subprocess.Popen(
                [args.launch_exe, "--remote-debugging-port=9222"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **quiet_subprocess_kwargs(),
            )
            time.sleep(max(0.0, args.launch_wait_s))

        def invoke():
            return invoke_pre_replace_via_cdp(args.cdp_url, str(source_info_path), list(args.replace_types))

        result, capture = capture_rec_during(invoke, source_info_path, rec_out)
        report["pre_replace_result"] = result
        report["rec_capture"] = capture

        if rec_out.exists():
            try:
                decrypted = decrypt_rec(rec_out, str(patched_config.get("k6") or ""))
                json_out.parent.mkdir(parents=True, exist_ok=True)
                json_out.write_text(decrypted, encoding="utf-8")
                report["decrypt"]["ok"] = True
            except Exception as exc:
                report["decrypt"]["error"] = str(exc)
    finally:
        restore_config(config_path, original_config)
        if launched_proc is not None and launched_proc.poll() is None:
            launched_proc.terminate()

    save_json(report_json, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
