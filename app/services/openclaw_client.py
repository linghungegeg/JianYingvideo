import logging
from typing import Any, Dict

import requests


class OpenClawClient:
    """Simple OpenClaw HTTP client."""

    def __init__(self, base_url: str, token: str = ""):
        self.base_url = (base_url or "").rstrip("/")
        self.session = requests.Session()
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_connection(self) -> bool:
        """Test service connectivity via /health."""
        if not self.base_url:
            return False
        try:
            resp = self.session.get(f"{self.base_url}/health", timeout=5)
            return resp.status_code == 200
        except Exception as exc:
            logging.error("OpenClaw connection test failed: %s", exc)
            return False

    def generate_manga(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Call manga-drama skill and return JSON payload."""
        if not self.base_url:
            raise ValueError("OpenClaw base_url is empty")
        skill_url = f"{self.base_url}/skill/manga-drama"
        resp = self.session.post(skill_url, json=params, timeout=120)
        resp.raise_for_status()
        return resp.json()
