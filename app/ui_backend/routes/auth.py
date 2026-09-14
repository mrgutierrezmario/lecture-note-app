"""Login, logout, and user management (admin)."""

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import mailer
from auth import (
    CurrentUser,
    clear_login_cookie,
    current_user,
    hash_password,
    require_admin,
    set_login_cookie,
    verify_password,
)
from config import get_settings
from database import get_db
from models import PasswordReset as ResetToken
from models import Session, User
from schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    PasswordChange,
    PasswordReset,
    ProfileUpdate,
    RegisterRequest,
    RegistrationStatus,
    ResetPasswordRequest,
    UserCreate,
    UserResponse,
    UserUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{2,64}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


def _validate_username(username: str) -> str:
    username = username.strip().lower()
    if not _USERNAME_RE.match(username):
        raise HTTPException(400, "Username: 2-64 letters, digits, dots, dashes or underscores")
    return username


def _validate_email(email: str | None) -> str | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(400, "That doesn't look like a valid email address")
    return email


async def _find_user(db: AsyncSession, identifier: str) -> User | None:
    """Look a user up by username or email, case-insensitively."""
    ident = identifier.strip().lower()
    result = await db.execute(select(User).where(or_(User.username == ident, User.email == ident)))
    return result.scalar_one_or_none()


async def _ensure_unique(db: AsyncSession, username: str, email: str | None) -> None:
    if (await db.execute(select(User).where(User.username == username))).scalar_one_or_none():
        raise HTTPException(409, "That username is taken")
    if email and (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(409, "An account with that email already exists")


def _validate_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD} characters")
    return password


RESET_MINUTES = 60


@router.get("/status", response_model=RegistrationStatus)
async def registration_status():
    """What the sign-in page may offer; readable without a login."""
    return RegistrationStatus(
        registration_open=get_settings().registration_open,
        password_reset_available=mailer.configured(),
    )


def _public_base(request: Request) -> str:
    configured = get_settings().public_url.rstrip("/")
    return configured or str(request.base_url).rstrip("/")


@router.post("/forgot", status_code=202)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Always 202: the response never reveals whether an account or email exists.
    The email is sent in the background so timing doesn't reveal it either."""
    user = await _find_user(db, body.identifier)
    if user is None or user.disabled or not user.email or not mailer.configured():
        return Response(status_code=202)

    # Throttle: at most one link per user every 2 minutes.
    recent = await db.scalar(
        select(ResetToken)
        .where(
            ResetToken.user_id == user.id,
            ResetToken.created_at > datetime.utcnow() - timedelta(minutes=2),
        )
        .limit(1)
    )
    if recent:
        return Response(status_code=202)

    token = secrets.token_urlsafe(32)
    db.add(
        ResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(minutes=RESET_MINUTES),
        )
    )
    await db.commit()

    link = f"{_public_base(request)}/reset-password?token={token}"
    subject, text, html_body = mailer.password_reset_email(user.username, link, RESET_MINUTES)
    background.add_task(mailer.send, user.email, subject, text, html_body)
    logger.info("Password reset link issued for %s", user.username)
    return Response(status_code=202)


@router.post("/reset", status_code=204)
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Complete a password reset from an emailed link.

    The token is valid once, for ``RESET_MINUTES``; finishing a reset also
    voids any other outstanding tokens for the account.
    """
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    row = (
        await db.execute(select(ResetToken).where(ResetToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at < datetime.utcnow():
        raise HTTPException(400, "This reset link is invalid or has expired — request a new one")
    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if user is None or user.disabled:
        raise HTTPException(400, "This reset link is invalid or has expired — request a new one")
    user.password_hash = hash_password(_validate_password(body.new_password))
    row.used_at = datetime.utcnow()
    # Any other outstanding links for this account are void now.
    await db.execute(
        update(ResetToken)
        .where(ResetToken.user_id == user.id, ResetToken.used_at.is_(None))
        .values(used_at=datetime.utcnow())
    )
    await db.commit()
    logger.info("Password reset completed for %s", user.username)
    return Response(status_code=204)


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    """Create a regular account and sign it in (when self-registration is open)."""
    if not get_settings().registration_open:
        raise HTTPException(403, "Registration is closed — ask an administrator for an account")
    username = _validate_username(body.username)
    email = _validate_email(body.email)
    if not email:
        raise HTTPException(400, "Email is required")
    await _ensure_unique(db, username, email)
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(_validate_password(body.password)),
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    set_login_cookie(response, request, user.id)
    logger.info("User %s registered", username)
    return user


@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    """Sign in with a username or email; sets the login cookie."""
    user = await _find_user(db, body.username)
    # Same error for unknown user and wrong password so accounts can't be probed.
    if user is None or user.disabled or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect username/email or password")
    set_login_cookie(response, request, user.id)
    logger.info("User %s signed in", user.username)
    return user


@router.post("/logout", status_code=204)
async def logout(response: Response):
    """Sign out by clearing the login cookie."""
    clear_login_cookie(response)
    return Response(status_code=204)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """The signed-in user's own account."""
    result = await db.execute(select(User).where(User.id == user.id))
    return result.scalar_one()


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    body: ProfileUpdate,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Let the signed-in user set or change their email address."""
    row = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
    email = _validate_email(body.email)
    if email and email != row.email:
        if (
            await db.execute(select(User).where(User.email == email, User.id != user.id))
        ).scalar_one_or_none():
            raise HTTPException(409, "An account with that email already exists")
    row.email = email
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChange,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the signed-in user's password after re-checking the current one."""
    result = await db.execute(select(User).where(User.id == user.id))
    row = result.scalar_one()
    if not verify_password(body.current_password, row.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    row.password_hash = hash_password(_validate_password(body.new_password))
    await db.commit()
    return Response(status_code=204)


# ── Admin: user management ────────────────────────────────────────────────────


@router.get("/users", response_model=list[UserResponse], dependencies=[Depends(require_admin)])
async def list_users(db: AsyncSession = Depends(get_db)):
    """Admin: every account, oldest first."""
    result = await db.execute(select(User).order_by(User.created_at))
    return result.scalars().all()


@router.post(
    "/users", response_model=UserResponse, status_code=201, dependencies=[Depends(require_admin)]
)
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)):
    """Admin: create an account (optionally an admin) with a chosen password."""
    username = _validate_username(body.username)
    email = _validate_email(body.email)
    await _ensure_unique(db, username, email)
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(_validate_password(body.password)),
        is_admin=body.is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("User %s created (admin=%s)", username, body.is_admin)
    return user


@router.post("/users/{user_id}/password", status_code=204, dependencies=[Depends(require_admin)])
async def admin_reset_password(
    user_id: str, body: PasswordReset, db: AsyncSession = Depends(get_db)
):
    """Admin: set a new password for another user."""
    result = await db.execute(select(User).where(User.id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "User not found")
    row.password_hash = hash_password(_validate_password(body.new_password))
    await db.commit()
    return Response(status_code=204)


@router.patch(
    "/users/{user_id}", response_model=UserResponse, dependencies=[Depends(require_admin)]
)
async def update_user(user_id: str, body: UserUpdate, db: AsyncSession = Depends(get_db)):
    """Admin: set or clear a user's personal audio-storage quota."""
    result = await db.execute(select(User).where(User.id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "User not found")
    if body.clear_quota:
        row.quota_mb = None
    elif body.quota_mb is not None:
        if body.quota_mb < 0:
            raise HTTPException(400, "Quota must be 0 (unlimited) or more")
        row.quota_mb = body.quota_mb
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str, admin: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """Admin: delete an account. Their lectures are kept but lose their owner
    (becoming admin-only). You cannot delete yourself.
    """
    if str(admin.id) == user_id:
        raise HTTPException(400, "You cannot delete your own account")
    result = await db.execute(select(User).where(User.id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "User not found")
    # Keep their lectures; the rows just lose their owner and become admin-only.
    await db.execute(update(Session).where(Session.user_id == row.id).values(user_id=None))
    await db.delete(row)
    await db.commit()
    logger.info("User %s deleted by %s", row.username, admin.username)
    return Response(status_code=204)
