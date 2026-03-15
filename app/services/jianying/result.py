from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ServiceResult:
    ok: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    code: str = "ok"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "code": self.code,
            "data": self.data or {},
        }


def from_tool_response(resp) -> ServiceResult:
    if resp is None:
        return ServiceResult(False, "empty response", code="empty_response")
    try:
        ok = bool(resp.success)
        return ServiceResult(ok, resp.message or "", data=resp.data or {}, code="ok" if ok else "error")
    except Exception:
        return ServiceResult(False, "invalid response", code="invalid_response")
