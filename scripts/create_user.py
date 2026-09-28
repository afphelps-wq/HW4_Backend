"""Create (or reset the password of) a user. Signup is invite-only, so this
is how accounts get made.

Usage (from the repo root, with DATABASE_URL set):
    python -m scripts.create_user alice@lab.org            # prompts for password
    python -m scripts.create_user alice@lab.org --admin
    python -m scripts.create_user alice@lab.org --reset    # change existing user's password
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.db import get_engine
from app.models import User
from app.security import hash_password, normalize_email
from sqlalchemy.orm import Session


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("email")
    parser.add_argument("--admin", action="store_true")
    parser.add_argument("--reset", action="store_true", help="update an existing user's password")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if len(password.encode()) < 10:
        print("Password must be at least 10 characters.", file=sys.stderr)
        return 1
    if len(password.encode()) > 72:
        print("Password must be at most 72 bytes (bcrypt limit).", file=sys.stderr)
        return 1
    if getpass.getpass("Confirm: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    email = normalize_email(args.email)
    with Session(get_engine()) as db:
        user = db.scalar(select(User).where(User.email == email))
        if user and not args.reset:
            print(f"{email} already exists (use --reset to change the password).", file=sys.stderr)
            return 1
        if user is None:
            if args.reset:
                print(f"No user {email} to reset.", file=sys.stderr)
                return 1
            user = User(email=email, is_admin=args.admin)
            db.add(user)
        user.password_hash = hash_password(password)
        db.commit()
    print(f"{'Updated' if args.reset else 'Created'} {email}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
