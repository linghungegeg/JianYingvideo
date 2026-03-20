import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


BASE_URL = os.getenv("VF_BASE_URL", "http://127.0.0.1:5000").rstrip("/") + "/"
USERNAME = os.getenv("VF_USER") or ""
PASSWORD = os.getenv("VF_PASS") or ""
TIMEOUT = int(os.getenv("VF_TIMEOUT", "10"))


def request_json(method, path, payload=None, token=None):
    url = urljoin(BASE_URL, path.lstrip("/"))
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body or "{}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(body or "{}")
        except Exception:
            payload = {"raw": body}
        return exc.code, payload
    except URLError as exc:
        raise RuntimeError(f"request failed: {exc}; ensure run.py is running and VF_BASE_URL is correct") from exc


def main():
    if not USERNAME or not PASSWORD:
        print("missing VF_USER/VF_PASS")
        sys.exit(1)

    try:
        status, login_data = request_json(
            "POST",
            "/api/auth/login",
            {"account": USERNAME, "password": PASSWORD},
        )
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)

    if status != 200 or not login_data.get("ok") or not login_data.get("token"):
        print("login failed", status, login_data)
        sys.exit(1)

    token = login_data["token"]
    status, data = request_json("POST", "/api/split", {}, token=token)
    print("status", status)
    print("payload", json.dumps(data, ensure_ascii=False))

    expected = "source_path 和 output_dir 不能为空"
    if status != 400 or data.get("error") != expected:
        print("unexpected split validation response")
        sys.exit(1)

    print("OK split api smoke passed")


if __name__ == "__main__":
    main()
