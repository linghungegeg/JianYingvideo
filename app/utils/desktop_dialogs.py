from __future__ import annotations

from threading import Lock
from typing import Any


_ACTIVE_WINDOW = None
_WINDOW_LOCK = Lock()


def set_active_window(window: Any) -> None:
    global _ACTIVE_WINDOW
    with _WINDOW_LOCK:
        _ACTIVE_WINDOW = window


def get_active_window() -> Any:
    with _WINDOW_LOCK:
        return _ACTIVE_WINDOW

