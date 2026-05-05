from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _read_password() -> str:
    password = getpass.getpass("Admin password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Password confirmation does not match.")
    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters.")
    return password


def _table_exists(engine, table_name: str) -> bool:
    return inspect(engine).has_table(table_name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or repair an admin user after database migrations.",
    )
    parser.add_argument("--username", required=True, help="Admin username to create or promote.")
    parser.add_argument("--email", default="", help="Optional admin email.")
    parser.add_argument("--quota", type=int, default=None, help="Optional initial quota.")
    parser.add_argument(
        "--update-password",
        action="store_true",
        help="Reset password when the admin user already exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    from app import create_app
    from app.extensions import db
    from app.models.user import User
    from app.models.user_quota import UserQuota

    app = create_app()
    with app.app_context():
        if not _table_exists(db.engine, "users"):
            raise SystemExit(
                "Database is not initialized. Run `flask db upgrade` before creating admin users."
            )

        username = args.username.strip()
        email = args.email.strip() or None
        if not username:
            raise SystemExit("--username cannot be empty.")

        user = User.query.filter_by(username=username).first()
        creating = user is None
        if creating:
            user = User(username=username, role="admin")
            user.password = _read_password()
            db.session.add(user)
        else:
            user.role = "admin"
            if args.update_password:
                user.password = _read_password()

        if email:
            owner = User.query.filter(User.email == email, User.id != getattr(user, "id", None)).first()
            if owner:
                raise SystemExit(f"Email already belongs to another user: {email}")
            user.email = email

        try:
            db.session.flush()
            if _table_exists(db.engine, "user_quota"):
                quota = UserQuota.query.filter_by(user_id=user.id).first()
                if quota is None:
                    default_quota = args.quota
                    if default_quota is None:
                        default_quota = int(app.config.get("DEFAULT_USER_QUOTA", 0) or 0)
                    quota = UserQuota(user_id=user.id, remaining=max(int(default_quota), 0))
                    db.session.add(quota)
                elif args.quota is not None:
                    quota.remaining = max(int(args.quota), 0)
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise SystemExit(f"Admin user could not be saved because of a uniqueness conflict: {exc}") from exc
        except SQLAlchemyError as exc:
            db.session.rollback()
            raise SystemExit(f"Admin user could not be saved: {exc}") from exc

        action = "created" if creating else "updated"
        print(f"Admin user {action}: {username}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
