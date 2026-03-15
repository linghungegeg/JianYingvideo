import os

from .errors import ValidationError


def require_path(path: str, label: str) -> None:
    if not path:
        raise ValidationError(f"{label} is required")
    if not os.path.exists(path):
        raise ValidationError(f"{label} not found: {path}")


def require_non_empty(value, label: str) -> None:
    if value is None or value == "":
        raise ValidationError(f"{label} is required")


def require_timerange(value: str) -> None:
    if not value or "-" not in value:
        raise ValidationError(f"invalid timerange: {value}")
