import base64
import json
import secrets
from pathlib import Path

try:
    from Crypto.Cipher import AES
except Exception:
    AES = None


OFFICIAL_DRAFT_CONTENT_EMBEDDED_KEY_OFFSETS = (0, 7, 20, 33, 40, 47, 59, 66)
OFFICIAL_DRAFT_CONTENT_EMBEDDED_IV_OFFSETS = (76, 89, 99, 127)
OFFICIAL_DRAFT_CONTENT_CRYPT_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def decode_official_encrypted_draft_content_inprocess(draft_content_path: str) -> tuple[dict, dict]:
    if AES is None:
        raise ValueError("pycryptodome AES runtime is unavailable")

    container_text = Path(draft_content_path).read_text(encoding="utf-8").strip()
    offsets = (
        *OFFICIAL_DRAFT_CONTENT_EMBEDDED_KEY_OFFSETS,
        *OFFICIAL_DRAFT_CONTENT_EMBEDDED_IV_OFFSETS,
    )
    if len(container_text) < offsets[-1] + 4:
        raise ValueError("official encrypted payload is too short")

    extracted_parts: list[str] = []
    body_parts: list[str] = []
    last_offset = 0
    for offset in offsets:
        extracted_parts.append(container_text[offset : offset + 4])
        if offset - last_offset > 4:
            body_parts.append(container_text[last_offset + 4 : offset])
        last_offset = offset
    body_parts.append(container_text[last_offset + 4 :])

    key_text = "".join(extracted_parts[: len(OFFICIAL_DRAFT_CONTENT_EMBEDDED_KEY_OFFSETS)])
    iv_text = "".join(extracted_parts[len(OFFICIAL_DRAFT_CONTENT_EMBEDDED_KEY_OFFSETS) :])
    encrypted_bytes = base64.b64decode("".join(body_parts), validate=True)
    if len(encrypted_bytes) <= 16:
        raise ValueError("official encrypted payload body is too short")

    cipher = AES.new(key_text.encode("utf-8"), AES.MODE_GCM, nonce=iv_text.encode("utf-8"))
    plain_bytes = cipher.decrypt_and_verify(encrypted_bytes[:-16], encrypted_bytes[-16:])
    data = json.loads(plain_bytes.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("official encrypted payload decoded to non-object JSON")

    diagnostics = {
        "reader": "official_inprocess_aesgcm",
        "matched_candidate": draft_content_path,
        "embedded_key_offsets": list(OFFICIAL_DRAFT_CONTENT_EMBEDDED_KEY_OFFSETS),
        "embedded_iv_offsets": list(OFFICIAL_DRAFT_CONTENT_EMBEDDED_IV_OFFSETS),
        "container_length": len(container_text),
        "body_base64_length": sum(len(item) for item in body_parts),
        "body_binary_length": len(encrypted_bytes),
        "plain_length": len(plain_bytes),
    }
    return data, diagnostics


def encode_official_encrypted_draft_content_inprocess(data: dict) -> tuple[str, dict]:
    if AES is None:
        raise ValueError("pycryptodome AES runtime is unavailable")
    if not isinstance(data, dict):
        raise ValueError("official payload writer expects object JSON")

    plain_text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    key_text = "".join(secrets.choice(OFFICIAL_DRAFT_CONTENT_CRYPT_ALPHABET) for _ in range(32))
    iv_text = "".join(secrets.choice(OFFICIAL_DRAFT_CONTENT_CRYPT_ALPHABET) for _ in range(16))
    cipher = AES.new(key_text.encode("utf-8"), AES.MODE_GCM, nonce=iv_text.encode("utf-8"))
    encrypted_bytes, auth_tag = cipher.encrypt_and_digest(plain_text.encode("utf-8"))
    body_text = base64.b64encode(encrypted_bytes + auth_tag).decode("ascii")

    offsets = (
        *OFFICIAL_DRAFT_CONTENT_EMBEDDED_KEY_OFFSETS,
        *OFFICIAL_DRAFT_CONTENT_EMBEDDED_IV_OFFSETS,
    )
    embedded_chunks = [key_text[index * 4 : (index + 1) * 4] for index in range(8)]
    embedded_chunks.extend(iv_text[index * 4 : (index + 1) * 4] for index in range(4))

    container_parts = [embedded_chunks[0]]
    body_cursor = 0
    previous_offset = offsets[0]
    for offset, chunk in zip(offsets[1:], embedded_chunks[1:]):
        body_slice_len = offset - previous_offset - 4
        if body_slice_len < 0:
            raise ValueError("official encrypted payload offsets are invalid")
        if body_cursor + body_slice_len > len(body_text):
            raise ValueError("official encrypted payload body is too short for embedded offsets")
        container_parts.append(body_text[body_cursor : body_cursor + body_slice_len])
        container_parts.append(chunk)
        body_cursor += body_slice_len
        previous_offset = offset
    container_parts.append(body_text[body_cursor:])

    container_text = "".join(container_parts)
    diagnostics = {
        "writer": "official_inprocess_aesgcm",
        "plain_length": len(plain_text),
        "body_binary_length": len(encrypted_bytes) + len(auth_tag),
        "body_base64_length": len(body_text),
        "container_length": len(container_text),
        "embedded_key_offsets": list(OFFICIAL_DRAFT_CONTENT_EMBEDDED_KEY_OFFSETS),
        "embedded_iv_offsets": list(OFFICIAL_DRAFT_CONTENT_EMBEDDED_IV_OFFSETS),
    }
    return container_text, diagnostics


def load_official_draft_payload(draft_content_path: str) -> tuple[dict, dict]:
    return decode_official_encrypted_draft_content_inprocess(draft_content_path)


def dump_official_draft_payload(data: dict) -> tuple[str, dict]:
    return encode_official_encrypted_draft_content_inprocess(data)


def write_official_draft_payload(draft_content_path: str, data: dict) -> dict:
    container_text, diagnostics = dump_official_draft_payload(data)
    Path(draft_content_path).write_text(container_text, encoding="utf-8")
    return {
        "path": str(draft_content_path),
        "payload_length": len(container_text),
        **diagnostics,
    }


__all__ = [
    "OFFICIAL_DRAFT_CONTENT_EMBEDDED_KEY_OFFSETS",
    "OFFICIAL_DRAFT_CONTENT_EMBEDDED_IV_OFFSETS",
    "decode_official_encrypted_draft_content_inprocess",
    "encode_official_encrypted_draft_content_inprocess",
    "load_official_draft_payload",
    "dump_official_draft_payload",
    "write_official_draft_payload",
]
