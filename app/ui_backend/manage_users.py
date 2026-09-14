#!/usr/bin/env python
"""Manage accounts from the shell — needed once to create the first admin.

venv/bin/python manage_users.py create <username> [--admin]   (prompts for a password,
                                                                or generates one with --generate)
venv/bin/python manage_users.py list
venv/bin/python manage_users.py passwd <username>
venv/bin/python manage_users.py delete <username>
"""

import argparse
import asyncio
import getpass
import secrets
import sys

from sqlalchemy import select, update

from auth import hash_password
from database import AsyncSessionLocal
from models import Session, User


async def _get(db, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username.lower()))
    return result.scalar_one_or_none()


def _password(args) -> str:
    if getattr(args, "generate", False):
        pw = secrets.token_urlsafe(12)
        print(f"Generated password: {pw}")
        return pw
    pw = getpass.getpass("Password: ")
    if len(pw) < 8:
        sys.exit("Password must be at least 8 characters")
    if pw != getpass.getpass("Repeat: "):
        sys.exit("Passwords do not match")
    return pw


async def create(args):
    """Create a user; ``--admin`` grants admin, ``--generate`` prints a random password."""
    async with AsyncSessionLocal() as db:
        if await _get(db, args.username):
            sys.exit(f"User {args.username} already exists")
        db.add(
            User(
                username=args.username.lower(),
                email=(args.email or None) and args.email.lower(),
                password_hash=hash_password(_password(args)),
                is_admin=args.admin,
            )
        )
        await db.commit()
    print(f"Created {'admin ' if args.admin else ''}user {args.username.lower()}")


async def list_users(args):
    """Print every account with its email and flags."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    for u in rows:
        flags = " admin" if u.is_admin else ""
        flags += " disabled" if u.disabled else ""
        print(f"{u.username:24}{(u.email or ''):32}{flags}")
    if not rows:
        print("(no users)")


async def passwd(args):
    """Set a new password for an existing user."""
    async with AsyncSessionLocal() as db:
        user = await _get(db, args.username)
        if not user:
            sys.exit("No such user")
        user.password_hash = hash_password(_password(args))
        await db.commit()
    print("Password updated")


async def delete(args):
    """Delete a user; their lectures are kept and become admin-only."""
    async with AsyncSessionLocal() as db:
        user = await _get(db, args.username)
        if not user:
            sys.exit("No such user")
        await db.execute(update(Session).where(Session.user_id == user.id).values(user_id=None))
        await db.delete(user)
        await db.commit()
    print(f"Deleted {args.username}")


def main():
    """Parse the sub-command and run it."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create")
    p.add_argument("username")
    p.add_argument("--admin", action="store_true")
    p.add_argument("--generate", action="store_true")
    p.add_argument("--email")
    p.set_defaults(fn=create)
    p = sub.add_parser("list")
    p.set_defaults(fn=list_users)
    p = sub.add_parser("passwd")
    p.add_argument("username")
    p.add_argument("--generate", action="store_true")
    p.set_defaults(fn=passwd)
    p = sub.add_parser("delete")
    p.add_argument("username")
    p.set_defaults(fn=delete)
    args = parser.parse_args()
    asyncio.run(args.fn(args))


if __name__ == "__main__":
    main()
