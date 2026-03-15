import os
import json
import time
import argparse
from typing import Dict, Any, List

import requests


DEFAULT_BASE = "https://www.duoec.com/api/jy/resource/list"


def fetch_page(base_url: str, resource_type: str, page_no: int, page_size: int,
               secret_id: str, secret_key: str) -> Dict[str, Any]:
    params = {
        "type": resource_type,
        "pageNo": page_no,
        "pageSize": page_size
    }
    headers = {
        "x-secret-id": secret_id,
        "x-secret-key": secret_key,
    }
    resp = requests.get(base_url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def normalize_items(items: List[Dict[str, Any]], category: str) -> List[Dict[str, Any]]:
    out = []
    for it in items:
        rid = it.get("id") or it.get("resourceId") or it.get("resource_id") or it.get("effectId") or it.get("effect_id")
        if not rid:
            continue
        out.append({
            "id": str(rid),
            "name": it.get("name") or it.get("title") or "",
            "category": category,
            "type": category,
            "url": it.get("url") or it.get("cover") or it.get("coverUrl"),
            "meta": it,
        })
    return out


def fetch_all(base_url: str, types: List[str], page_size: int,
              secret_id: str, secret_key: str, sleep_sec: float) -> Dict[str, Any]:
    all_items = []
    for t in types:
        page = 1
        while True:
            data = fetch_page(base_url, t, page, page_size, secret_id, secret_key)
            # try common response shapes
            items = data.get("data") or data.get("list") or data.get("items") or []
            if isinstance(items, dict) and "records" in items:
                items = items.get("records") or []
            if not items:
                break
            all_items.extend(normalize_items(items, t))
            page += 1
            time.sleep(sleep_sec)
    return {
        "version": "duo-api",
        "items": all_items,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--types", default="text_template,video_effect,face_effect,transition,sticker")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--output", default="app/utils/duo_resources/resources.json")
    args = parser.parse_args()

    secret_id = os.getenv("DUO_SECRET_ID", "")
    secret_key = os.getenv("DUO_SECRET_KEY", "")
    if not secret_id or not secret_key:
        raise SystemExit("Missing DUO_SECRET_ID / DUO_SECRET_KEY in environment.")

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    payload = fetch_all(args.base_url, types, args.page_size, secret_id, secret_key, args.sleep)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(payload['items'])} items to {args.output}")


if __name__ == "__main__":
    main()
