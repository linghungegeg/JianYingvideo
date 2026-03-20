import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import urlparse, quote, urlencode


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _percent_encode(value: str) -> str:
    return quote(value, safe="-_.~")


def _canonical_query(params: dict) -> str:
    if not params:
        return ""
    items = []
    for k in sorted(params.keys()):
        v = params[k]
        if v is None:
            continue
        items.append((_percent_encode(str(k)), _percent_encode(str(v))))
    return "&".join([f"{k}={v}" for k, v in items])


def sign_volc_request(method: str, url: str, headers: dict, body: bytes, access_key: str, secret_key: str, region: str, service: str):
    method = method.upper()
    parsed = urlparse(url)
    host = parsed.netloc
    canonical_uri = parsed.path or "/"

    query_params = {}
    if parsed.query:
        for kv in parsed.query.split("&"):
            if not kv:
                continue
            if "=" in kv:
                k, v = kv.split("=", 1)
            else:
                k, v = kv, ""
            query_params[k] = v
    canonical_query = _canonical_query(query_params)

    now = datetime.now(timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = now.strftime("%Y%m%d")

    payload_hash = _sha256_hex(body or b"")
    headers = headers or {}
    headers["Host"] = host
    headers["X-Date"] = x_date
    headers["X-Content-Sha256"] = payload_hash

    # Canonical headers
    canon_items = []
    for k in sorted(headers.keys(), key=lambda x: x.lower()):
        canon_items.append(f"{k.lower()}:{str(headers[k]).strip()}")
    canonical_headers = "\n".join(canon_items) + "\n"
    signed_headers = ";".join([k.split(":", 1)[0] for k in canon_items])

    canonical_request = "\n".join([
        method,
        canonical_uri,
        canonical_query,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    algorithm = "HMAC-SHA256"
    credential_scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join([
        algorithm,
        x_date,
        credential_scope,
        _sha256_hex(canonical_request.encode("utf-8")),
    ])

    k_date = _hmac_sha256(secret_key.encode("utf-8"), short_date)
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode("utf-8"), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"request", hashlib.sha256).digest()
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers["Authorization"] = authorization

    return headers
