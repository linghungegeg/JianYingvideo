import os

from dotenv import load_dotenv


load_dotenv()


def _default_sqlite_uri() -> str:
    base_dir = os.path.abspath(os.path.dirname(__file__))
    return "sqlite:///" + os.path.join(base_dir, "data-dev.sqlite")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "hard-to-guess-string-change-in-production"
    BYOK_ENCRYPTION_KEY = os.environ.get("VIDEOFACTORY_KEY_ENCRYPTION_KEY") or os.environ.get("BYOK_ENCRYPTION_KEY")

    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("SQLALCHEMY_DATABASE_URI")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("DEV_DATABASE_URL")
        or _default_sqlite_uri()
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload/log folders
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), "app", "uploads")
    LOG_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), "logs")

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(LOG_FOLDER, exist_ok=True)

    # Redis
    REDIS_URL = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"

    # Default free quota for new users
    DEFAULT_USER_QUOTA = int(os.environ.get("DEFAULT_USER_QUOTA", "5"))

    # Legacy template-library endpoints. Keep enabled during migration, disable later.
    LEGACY_TEMPLATE_ENDPOINTS_ENABLED = os.environ.get("LEGACY_TEMPLATE_ENDPOINTS_ENABLED", "0") == "1"

    # Optional feature groups for lean desktop builds.
    DUO_FEATURES_ENABLED = os.environ.get("DUO_FEATURES_ENABLED", "1") == "1"
    OPENCLAW_FEATURES_ENABLED = os.environ.get("OPENCLAW_FEATURES_ENABLED", "1") == "1"
    MANGA_FEATURES_ENABLED = os.environ.get("MANGA_FEATURES_ENABLED", "1") == "1"
