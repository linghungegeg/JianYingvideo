import base64
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import requests

from app.extensions import db
from app.models.ai_generation_log import AIGenerationLog
from app.models.user_material import UserMaterial
from app.models.user_api_key import UserApiKey
from app.utils.helpers import get_material_folder
from app.utils.volc_signer import sign_volc_request


DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
VOLC_TTS_URL = "https://openspeech.bytedance.com/api/v1/tts"


def _ensure_material_folder() -> Optional[str]:
    folder = get_material_folder()
    if not folder:
        return None
    os.makedirs(folder, exist_ok=True)
    return folder


def _user_ai_root(user_id: int) -> Optional[str]:
    base = _ensure_material_folder()
    if not base:
        return None
    root = os.path.join(base, f"user_{user_id}", "ai_generated")
    os.makedirs(root, exist_ok=True)
    return root


def _user_ai_folder(user_id: int, task_type: str) -> Optional[str]:
    root = _user_ai_root(user_id)
    if not root:
        return None
    sub = {
        "text": "texts",
        "image": "images",
        "audio": "audios",
        "video": "videos",
    }.get(task_type, "others")
    folder = os.path.join(root, sub)
    os.makedirs(folder, exist_ok=True)
    return folder


def _save_text(content: str, folder: str) -> str:
    name = f"ai_text_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.txt"
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content or "")
    return path


def _save_binary(data: bytes, folder: str, ext: str) -> str:
    ext = ext.lstrip(".") or "bin"
    name = f"ai_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _download_to_file(url: str, folder: str, ext: str) -> str:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return _save_binary(resp.content, folder, ext)


def _guess_ext(content_type: str, fallback: str) -> str:
    if not content_type:
        return fallback
    ct = content_type.lower()
    if "jpeg" in ct:
        return "jpg"
    if "png" in ct:
        return "png"
    if "webp" in ct:
        return "webp"
    if "mp3" in ct or "mpeg" in ct:
        return "mp3"
    if "wav" in ct:
        return "wav"
    if "ogg" in ct:
        return "ogg"
    if "mp4" in ct:
        return "mp4"
    return fallback


def _normalize_openai_base(base_url: str) -> str:
    if not base_url:
        return DEFAULT_OPENAI_BASE
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base


def _openai_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _openai_text(api_key: str, base_url: str, payload: Dict[str, Any]) -> str:
    params = {
        "model": payload.get("model") or "gpt-4o-mini",
        "messages": [{"role": "user", "content": payload.get("prompt", "")}],
        "temperature": payload.get("temperature", 0.7),
    }
    if payload.get("max_tokens"):
        params["max_tokens"] = int(payload["max_tokens"])
    if payload.get("extra_body"):
        params.update(payload["extra_body"])

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=_normalize_openai_base(base_url))
        response = client.chat.completions.create(**params)
        return response.choices[0].message.content or ""
    except Exception:
        url = _normalize_openai_base(base_url) + "/chat/completions"
        resp = requests.post(url, headers=_openai_headers(api_key), json=params, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        item = (data.get("choices") or [{}])[0]
        msg = item.get("message") or {}
        return msg.get("content") or ""


def _openai_image(api_key: str, base_url: str, payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[bytes], str]:
    url = _normalize_openai_base(base_url) + "/images/generations"
    body = {
        "model": payload.get("model") or "gpt-image-1",
        "prompt": payload.get("prompt", ""),
        "size": payload.get("size") or "1024x1024",
    }
    if payload.get("extra_body"):
        body.update(payload["extra_body"])
    resp = requests.post(url, headers=_openai_headers(api_key), json=body, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        return None, base64.b64decode(item["b64_json"]), "png"
    if item.get("url"):
        return item["url"], None, "png"
    return None, None, "png"


def _openai_audio(api_key: str, base_url: str, payload: Dict[str, Any]) -> Tuple[bytes, str]:
    url = _normalize_openai_base(base_url) + "/audio/speech"
    fmt = payload.get("format") or "mp3"
    body = {
        "model": payload.get("model") or "gpt-4o-mini-tts",
        "input": payload.get("prompt", ""),
        "voice": payload.get("voice") or "alloy",
        "response_format": fmt,
    }
    if payload.get("extra_body"):
        body.update(payload["extra_body"])
    resp = requests.post(url, headers=_openai_headers(api_key), json=body, timeout=180)
    resp.raise_for_status()
    return resp.content, fmt


def _volc_tts_http(api_key: str, app_id: str, cluster: str, payload: Dict[str, Any]) -> Tuple[bytes, str]:
    if not app_id or not cluster:
        raise ValueError("缺少 AppID 或 Cluster")
    voice_type = payload.get("voice") or payload.get("voice_type") or payload.get("voiceType")
    if not voice_type:
        raise ValueError("缺少 voice_type")
    text = payload.get("prompt") or ""
    encoding = payload.get("format") or "mp3"
    req = {
        "app": {
            "appid": str(app_id),
            "token": str(api_key or "token"),
            "cluster": str(cluster),
        },
        "user": {
            "uid": payload.get("uid") or "video_factory",
        },
        "audio": {
            "voice_type": voice_type,
            "encoding": encoding,
            "rate": payload.get("rate") or 24000,
            "speed_ratio": payload.get("speed_ratio") or 1.0,
            "volume_ratio": payload.get("volume_ratio") or 1.0,
            "pitch_ratio": payload.get("pitch_ratio") or 1.0,
        },
        "request": {
            "reqid": payload.get("reqid") or str(uuid.uuid4()),
            "text": text,
            "text_type": payload.get("text_type") or "plain",
            "operation": "query",
        },
    }
    if payload.get("emotion"):
        req["audio"]["emotion"] = payload.get("emotion")
    if payload.get("language"):
        req["audio"]["language"] = payload.get("language")

    url = payload.get("custom_url") or VOLC_TTS_URL
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer;{api_key}",
            "Content-Type": "application/json",
        },
        json=req,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 3000:
        raise ValueError(data.get("message") or "TTS 请求失败")
    audio_b64 = data.get("data") or ""
    return base64.b64decode(audio_b64), encoding


def _openai_video(api_key: str, base_url: str, payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[bytes], str]:
    path = payload.get("custom_path") or "/v1/videos"
    url = _normalize_openai_base(base_url).replace("/v1", "") + path
    form = {
        "model": payload.get("model") or "sora-2",
        "prompt": payload.get("prompt", ""),
    }
    if payload.get("size"):
        form["size"] = payload.get("size")
    if payload.get("seconds"):
        form["seconds"] = str(payload.get("seconds"))
    if payload.get("extra_body"):
        form.update(payload["extra_body"])

    resp = requests.post(url, headers={"Authorization": f"Bearer {api_key}"}, data=form, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    item = (data.get("data") or [{}])[0]
    video_id = item.get("id")
    status = item.get("status")
    if status == "completed" and video_id:
        content_url = _normalize_openai_base(base_url) + f"/videos/{video_id}/content"
        content = requests.get(content_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=300)
        content.raise_for_status()
        return None, content.content, "mp4"
    if video_id:
        for _ in range(30):
            time.sleep(2)
            check = requests.get(_normalize_openai_base(base_url) + f"/videos/{video_id}", headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
            if not check.ok:
                continue
            payload_data = check.json()
            item = (payload_data.get("data") or [{}])[0]
            status = item.get("status")
            if status == "completed":
                content = requests.get(_normalize_openai_base(base_url) + f"/videos/{video_id}/content", headers={"Authorization": f"Bearer {api_key}"}, timeout=300)
                content.raise_for_status()
                return None, content.content, "mp4"
            if status in {"failed", "canceled"}:
                break
    return None, None, "mp4"


def _jimeng_signed_request(ak: str, sk: str, endpoint: str, payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[bytes], str]:
    if not endpoint:
        raise ValueError("缺少 Endpoint")
    extra = payload.get("extra_body") or {}
    if not isinstance(extra, dict):
        extra = {}
    action = extra.pop("action", None) or extra.pop("Action", None)
    version = extra.pop("version", None) or extra.pop("Version", None)
    path = extra.pop("path", None) or "/"
    query = extra.pop("query", None) or {}
    if not action or not version:
        raise ValueError("缺少 Action 或 Version")
    query_params = {"Action": action, "Version": version}
    if isinstance(query, dict):
        query_params.update(query)
    body = {
        "prompt": payload.get("prompt", "")
    }
    body.update(extra)
    url = endpoint.rstrip("/") + path
    if query_params:
        from urllib.parse import urlencode
        url = url + "?" + urlencode(query_params)
    headers = {
        "Content-Type": "application/json",
    }
    body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = sign_volc_request(
        "POST",
        url,
        headers,
        body_bytes,
        ak,
        sk,
        region="cn-north-1",
        service="cv",
    )
    resp = requests.post(url, headers=headers, data=body_bytes, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        result = data.get("result") or data.get("data") or data
        if isinstance(result, dict):
            for key in ("video_url", "videoUrl", "url"):
                if result.get(key):
                    return result.get(key), None, "mp4"
    return None, None, "mp4"


def generate_with_key(user_key: UserApiKey, task_type: str, payload: Dict[str, Any], save_text_file: bool = True) -> Dict[str, Any]:
    folder = _user_ai_folder(user_key.user_id, task_type)
    if not folder:
        return {"ok": False, "error": "请先在软件设置中配置素材库路径"}

    provider_code = user_key.provider.provider_code if user_key.provider else ""
    api_key = user_key.get_api_key()
    endpoint = user_key.endpoint or DEFAULT_OPENAI_BASE
    base_url = user_key.base_url or DEFAULT_OPENAI_BASE
    result_path = None
    result_text = None
    status = "success"
    error_msg = None
    saved_path = None

    try:
        if provider_code == "openai":
            if task_type == "text":
                text = _openai_text(api_key, base_url, payload)
                result_text = text
                if save_text_file:
                    saved_path = _save_text(text, folder)
            elif task_type == "image":
                url, data, ext = _openai_image(api_key, base_url, payload)
                if data:
                    saved_path = _save_binary(data, folder, ext)
                elif url:
                    saved_path = _download_to_file(url, folder, ext)
                else:
                    raise ValueError("图片结果为空")
            elif task_type == "audio":
                data, ext = _openai_audio(api_key, base_url, payload)
                saved_path = _save_binary(data, folder, ext)
            elif task_type == "video":
                url, data, ext = _openai_video(api_key, base_url, payload)
                if data:
                    saved_path = _save_binary(data, folder, ext)
                elif url:
                    saved_path = _download_to_file(url, folder, ext)
                else:
                    raise ValueError("视频生成未返回结果，请稍后重试")
            else:
                raise ValueError("不支持的任务类型")
        elif provider_code == "volc":
            app_id = user_key.get_api_secret()
            cluster = user_key.endpoint
            extra = payload.get("extra_body") or {}
            if isinstance(extra, dict):
                app_id = extra.get("app_id") or extra.get("appid") or app_id
                cluster = extra.get("cluster") or cluster
                if extra.get("custom_url"):
                    payload["custom_url"] = extra.get("custom_url")
            data, ext = _volc_tts_http(api_key, app_id, cluster, payload)
            saved_path = _save_binary(data, folder, ext)
        elif provider_code == "jimeng":
            if task_type != "video":
                raise ValueError("即梦当前仅支持视频生成")
            ak = user_key.get_api_key()
            sk = user_key.get_api_secret()
            if not ak or not sk:
                raise ValueError("即梦需要 AK/SK")
            url, data, ext = _jimeng_signed_request(ak, sk, user_key.endpoint, payload)
            if data:
                saved_path = _save_binary(data, folder, ext)
            elif url:
                saved_path = _download_to_file(url, folder, ext)
            else:
                raise ValueError("生成结果为空")
        else:
            raise ValueError("未知的服务商类型")

        result_path = saved_path
        user_key.last_used_at = datetime.utcnow()
        user_key.usage_count = (user_key.usage_count or 0) + 1
        db.session.add(user_key)
        db.session.commit()
        if result_path and task_type != "text":
            material = UserMaterial(
                user_id=user_key.user_id,
                file_path=result_path,
                file_type=task_type,
                source=provider_code or "ai"
            )
            db.session.add(material)
            db.session.commit()
    except Exception as exc:
        db.session.rollback()
        status = "failed"
        error_msg = str(exc)

    log = AIGenerationLog(
        user_id=user_key.user_id,
        key_id=user_key.id,
        provider_code=provider_code,
        task_type=task_type,
        prompt=payload.get("prompt"),
        result_path=result_path,
        status=status,
        error_msg=error_msg,
    )
    db.session.add(log)
    db.session.commit()

    if status != "success":
        return {"ok": False, "error": error_msg or "生成失败"}
    if task_type == "text":
        return {"ok": True, "text": result_text or "", "path": result_path}
    return {"ok": True, "path": result_path}
