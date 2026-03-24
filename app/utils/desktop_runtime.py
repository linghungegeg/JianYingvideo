import logging
import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
import sqlalchemy as sa

from app.utils.helpers import cleanup_legacy_runtime_session_state
from app.utils.runtime_paths import app_install_root, runtime_path


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _pick_desktop_port(preferred_port: int, host: str) -> int:
    candidates = [preferred_port]
    if preferred_port == 5000:
        candidates.extend([5001, 5050, 8000, 8765])

    for port in candidates:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
            return port
        except OSError:
            continue
        finally:
            sock.close()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def ensure_runtime_dirs(app) -> None:
    targets = {
        Path(app.config.get("UPLOAD_FOLDER") or runtime_path("uploads")),
        Path(app.config.get("LOG_FOLDER") or runtime_path("logs")),
        runtime_path("user_data"),
        runtime_path("runtime_tools"),
        runtime_path("duo_cache"),
        runtime_path("mcp_cache"),
    }
    for path in targets:
        path.mkdir(parents=True, exist_ok=True)
    cleanup_legacy_runtime_session_state()


def validate_installer_config(app) -> None:
    if not _env_flag("VF_REQUIRE_PRODUCTION_CONFIG", False):
        return

    errors = []
    db_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    remote_auth_mode = _env_flag("VF_REMOTE_AUTH_MODE", False)
    official_site_url = str(os.getenv("VF_OFFICIAL_SITE_URL") or app.config.get("OFFICIAL_SITE_URL") or "").strip()

    if not remote_auth_mode and not db_uri.startswith("mysql+"):
        errors.append("SQLALCHEMY_DATABASE_URI must point to MySQL")
    if remote_auth_mode and not official_site_url:
        errors.append("VF_OFFICIAL_SITE_URL is required when VF_REMOTE_AUTH_MODE=1")

    secret = str(app.config.get("SECRET_KEY") or "")
    if secret == "hard-to-guess-string-change-in-production":
        errors.append("SECRET_KEY is still using the default placeholder")

    byok_key = str(app.config.get("BYOK_ENCRYPTION_KEY") or "")
    if not byok_key:
        errors.append("VIDEOFACTORY_KEY_ENCRYPTION_KEY / BYOK_ENCRYPTION_KEY is missing")

    if errors:
        joined = "; ".join(errors)
        raise RuntimeError(f"installer startup blocked: {joined}")


def _load_runtime_models() -> None:
    from app.models import (
        ai_generation_log,
        ai_provider,
        ai_task,
        api_audit,
        api_key,
        api_quota,
        api_quota_template,
        api_quota_usage,
        api_usage,
        cdk_code,
        cdk_template,
        config,
        license_binding,
        manga_generation_log,
        manga_template,
        resource_exchange_post,
        task,
        task_effect_log,
        template,
        template_model,
        user,
        user_api_key,
        user_material,
        user_quota,
        user_quota_log,
        user_token,
    )


def _should_stamp_existing_sqlite(app) -> bool:
    from app.extensions import db

    _load_runtime_models()
    engine = db.engine
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return False

    managed_tables = set(db.metadata.tables.keys())
    present_runtime_tables = existing_tables & managed_tables
    # create_app() may pre-create only the config table on a fresh desktop DB.
    # That should not force a stamp-to-head decision.
    if not (present_runtime_tables - {"config"}):
        return False

    current_version = ""
    if "alembic_version" in existing_tables:
        try:
            with engine.connect() as connection:
                version = connection.execute(sa.text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            current_version = str(version or "").strip()
        except Exception:
            current_version = ""

    base_dir = app_install_root()
    alembic_ini = base_dir / "migrations" / "alembic.ini"
    script_location = base_dir / "migrations"
    cfg = AlembicConfig(str(alembic_ini))
    cfg.set_main_option("script_location", str(script_location))
    script_dir = ScriptDirectory.from_config(cfg)
    head_revision = str(script_dir.get_current_head() or "").strip()

    if current_version and head_revision and current_version == head_revision:
        return False
    # Desktop local SQLite may contain tables created by earlier packaged builds
    # while alembic_version is missing or lagging behind. In that case rerunning
    # intermediate migrations causes duplicate-table crashes on startup.
    return True


def _sqlite_server_default(column: sa.Column):
    if column.server_default is not None:
        return column.server_default.arg

    default = getattr(column, "default", None)
    if default is None or not getattr(default, "is_scalar", False):
        return None

    value = default.arg
    if callable(value) or value is None:
        return None
    if isinstance(value, bool):
        return sa.text("1" if value else "0")
    if isinstance(value, (int, float)):
        return sa.text(str(value))
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return sa.text(f"'{escaped}'")
    return None


def _clone_sqlite_add_column(column: sa.Column) -> sa.Column:
    try:
        column_type = column.type.copy()
    except Exception:
        column_type = column.type

    server_default = _sqlite_server_default(column)
    nullable = column.nullable if (column.nullable or server_default is not None) else True
    return sa.Column(
        column.name,
        column_type,
        nullable=nullable,
        server_default=server_default,
    )


def _ensure_sqlite_runtime_columns(app) -> None:
    from app.extensions import db

    _load_runtime_models()
    engine = db.engine
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return

    preparer = engine.dialect.identifier_preparer
    with engine.begin() as connection:
        for table in db.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            try:
                existing_columns = {
                    column["name"]
                    for column in inspector.get_columns(table.name)
                }
            except Exception as exc:
                logging.warning("inspect sqlite columns failed for %s: %s", table.name, exc)
                continue

            for column in table.columns:
                if column.primary_key or column.name in existing_columns:
                    continue
                try:
                    add_column = _clone_sqlite_add_column(column)
                    column_sql = str(
                        sa.schema.CreateColumn(add_column).compile(dialect=engine.dialect)
                    )
                    table_sql = preparer.quote(table.name)
                    connection.execute(sa.text(f"ALTER TABLE {table_sql} ADD COLUMN {column_sql}"))
                    existing_columns.add(column.name)
                except Exception as exc:
                    logging.warning(
                        "add sqlite column failed for %s.%s: %s",
                        table.name,
                        column.name,
                        exc,
                    )


def _ensure_sqlite_runtime_indexes(app) -> None:
    from app.extensions import db

    _load_runtime_models()
    engine = db.engine
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return

    with engine.begin() as connection:
        for table in db.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue

            try:
                existing_indexes = {
                    index["name"]
                    for index in inspector.get_indexes(table.name)
                    if index.get("name")
                }
                unique_sets = {
                    tuple(constraint.get("column_names") or [])
                    for constraint in inspector.get_unique_constraints(table.name)
                    if constraint.get("column_names")
                }
                existing_index_sets = {
                    tuple(index.get("column_names") or [])
                    for index in inspector.get_indexes(table.name)
                    if index.get("column_names")
                }
            except Exception as exc:
                logging.warning("inspect sqlite indexes failed for %s: %s", table.name, exc)
                continue

            for index in table.indexes:
                if index.name in existing_indexes:
                    continue
                try:
                    connection.execute(sa.schema.CreateIndex(index))
                    existing_indexes.add(index.name)
                    existing_index_sets.add(tuple(column.name for column in index.columns))
                except Exception as exc:
                    logging.warning("create sqlite index failed for %s: %s", index.name, exc)

            for column in table.columns:
                if not column.unique:
                    continue
                column_key = (column.name,)
                if column_key in unique_sets or column_key in existing_index_sets:
                    continue
                index_name = f"uq_{table.name}_{column.name}"
                unique_index = sa.Index(index_name, column, unique=True)
                try:
                    connection.execute(sa.schema.CreateIndex(unique_index))
                    existing_indexes.add(index_name)
                    existing_index_sets.add(column_key)
                    unique_sets.add(column_key)
                except Exception as exc:
                    logging.warning(
                        "create sqlite unique index failed for %s.%s: %s",
                        table.name,
                        column.name,
                        exc,
                    )


def _ensure_sqlite_runtime_schema(app) -> None:
    db_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip().lower()
    if not db_uri.startswith("sqlite:///"):
        return

    with app.app_context():
        from app.extensions import db
        _load_runtime_models()

        # Desktop local SQLite can lag behind migrations or carry stamped
        # databases from older packaged builds. create_all(checkfirst) only
        # fills missing tables and leaves existing ones intact.
        db.create_all()
        _ensure_sqlite_runtime_columns(app)
        _ensure_sqlite_runtime_indexes(app)


def run_startup_migrations(app) -> None:
    if not _env_flag("VF_AUTO_MIGRATE", True):
        return

    base_dir = app_install_root()
    alembic_ini = base_dir / "migrations" / "alembic.ini"
    script_location = base_dir / "migrations"

    cfg = AlembicConfig(str(alembic_ini))
    cfg.set_main_option("script_location", str(script_location))

    with app.app_context():
        if _should_stamp_existing_sqlite(app):
            command.stamp(cfg, "head")
        command.upgrade(cfg, "head")
    _ensure_sqlite_runtime_schema(app)


def desktop_server_options() -> dict:
    host = os.getenv("VF_HOST", "127.0.0.1")
    preferred_port = _env_int("VF_PORT", 5000)
    return {
        "host": host,
        "port": _pick_desktop_port(preferred_port, host),
        "debug": _env_flag("VF_DEBUG", False),
        "threaded": True,
        "use_reloader": False,
    }


def desktop_target_url(server_options: dict) -> str:
    host = server_options.get("host", "127.0.0.1")
    port = server_options.get("port", 5000)
    start_path = os.getenv("VF_START_PATH", "/user").strip() or "/user"
    if not start_path.startswith("/"):
        start_path = "/" + start_path
    return f"http://{host}:{port}{start_path}"


def open_browser_later(url: str) -> None:
    if not _env_flag("VF_OPEN_BROWSER", True):
        return

    delay = max(float(os.getenv("VF_OPEN_BROWSER_DELAY", "1.2")), 0.0)

    def _open() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"open browser skipped: {exc}")

    threading.Thread(target=_open, daemon=True).start()
