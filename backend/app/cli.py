"""Small operator commands. Run from the backend directory."""

import sys

from app.database import init_db, session_scope
from app.models import User
from app.security import hash_password


def reset_password(email: str, password: str) -> None:
    if len(password) < 8:
        raise SystemExit("Use at least 8 characters.")
    init_db()
    db = session_scope()
    try:
        user = db.query(User).filter(User.email == email.strip().lower()).one_or_none()
        if user is None:
            raise SystemExit(f"No account for {email}.")
        user.password_hash = hash_password(password)
        db.commit()
        print(f"Password updated for {user.email}.")
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "reset-password":
        reset_password(sys.argv[2], sys.argv[3])
        return
    raise SystemExit("Usage: python -m app.cli reset-password EMAIL NEWPASSWORD")


if __name__ == "__main__":
    main()
