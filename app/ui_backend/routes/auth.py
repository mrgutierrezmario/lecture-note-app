"""Login, logout, and user management (admin)."""

import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import mailer
import ratelimit
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
    RegistrationPending,
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
VERIFY_HOURS = 24
APPROVE_DAYS = 7


@router.get("/status", response_model=RegistrationStatus)
async def registration_status():
    """What the sign-in page may offer; readable without a login."""
    return RegistrationStatus(
        registration_open=get_settings().registration_open,
        registration_approval=get_settings().registration_approval,
        password_reset_available=mailer.configured(),
    )


def _public_base(request: Request) -> str:
    configured = get_settings().public_url.rstrip("/")
    return configured or str(request.base_url).rstrip("/")


def _client_ip(request: Request) -> str:
    """The caller's address (uvicorn runs with --proxy-headers, so this is the
    real client behind the Funnel/reverse proxy, not the proxy)."""
    return request.client.host if request.client else "unknown"


@router.post("/forgot", status_code=202)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Always 202: the response never reveals whether an account or email exists.
    The email is sent in the background so timing doesn't reveal it either.
    Each request counts as a "failure" for rate limiting, so one address can
    trigger at most a handful of reset emails per ten minutes."""
    key = f"forgot:{_client_ip(request)}"
    wait = ratelimit.retry_after(key)
    if wait:
        raise HTTPException(429, f"Too many requests — try again in {wait} seconds")
    ratelimit.record_failure(key)
    user = await _find_user(db, body.identifier)
    if user is None or user.disabled or not user.email or not mailer.configured():
        return Response(status_code=202)

    # Throttle: at most one link per user every 2 minutes.
    recent = await db.scalar(
        select(ResetToken)
        .where(
            ResetToken.user_id == user.id,
            ResetToken.purpose == "reset",
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
        await db.execute(
            select(ResetToken).where(
                ResetToken.token_hash == token_hash, ResetToken.purpose == "reset"
            )
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at < datetime.utcnow():
        raise HTTPException(400, "This reset link is invalid or has expired — request a new one")
    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if user is None or user.disabled:
        raise HTTPException(400, "This reset link is invalid or has expired — request a new one")
    user.password_hash = hash_password(_validate_password(body.new_password))
    row.used_at = datetime.utcnow()
    # Any other outstanding links for this account are void now. A password
    # reset also proves the mailbox, so it counts as verification.
    user.email_verified = True
    await db.execute(
        update(ResetToken)
        .where(ResetToken.user_id == user.id, ResetToken.used_at.is_(None))
        .values(used_at=datetime.utcnow())
    )
    await db.commit()
    logger.info("Password reset completed for %s", user.username)
    return Response(status_code=204)


async def _send_verification(
    db: AsyncSession, user: User, request: Request, background: BackgroundTasks
) -> bool:
    """Email a confirmation link (at most one every 2 minutes per user)."""
    recent = await db.scalar(
        select(ResetToken)
        .where(
            ResetToken.user_id == user.id,
            ResetToken.purpose == "verify",
            ResetToken.created_at > datetime.utcnow() - timedelta(minutes=2),
        )
        .limit(1)
    )
    if recent:
        return False
    token = secrets.token_urlsafe(32)
    db.add(
        ResetToken(
            user_id=user.id,
            purpose="verify",
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(hours=VERIFY_HOURS),
        )
    )
    await db.commit()
    link = f"{_public_base(request)}/api/auth/verify?token={token}"
    subject, text, html_body = mailer.verify_email(user.username, link, VERIFY_HOURS)
    background.add_task(mailer.send, user.email, subject, text, html_body)
    logger.info("Verification link issued for %s", user.username)
    return True


async def _request_approval(
    db: AsyncSession, user: User, request: Request, background: BackgroundTasks
) -> None:
    """Email every admin who has an address an approve link for ``user``."""
    if not mailer.configured():
        return
    admins = (
        (
            await db.execute(
                select(User).where(
                    User.is_admin.is_(True), User.disabled.is_(False), User.email.isnot(None)
                )
            )
        )
        .scalars()
        .all()
    )
    if not admins:
        return
    token = secrets.token_urlsafe(32)
    db.add(
        ResetToken(
            user_id=user.id,
            purpose="approve",
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(days=APPROVE_DAYS),
        )
    )
    await db.commit()
    link = f"{_public_base(request)}/api/auth/approve?token={token}"
    subject, text, html_body = mailer.approval_request_email(
        user.username, user.email or "", link, APPROVE_DAYS
    )
    for admin in admins:
        background.add_task(mailer.send, admin.email, subject, text, html_body)
    logger.info("Approval requested for %s (%d admin(s) emailed)", user.username, len(admins))


async def _approve(user: User, db: AsyncSession, request: Request, background: BackgroundTasks):
    """Activate a pending account and tell the user (if mail is configured)."""
    user.approved = True
    # Any other approve links for this account are void now.
    await db.execute(
        update(ResetToken)
        .where(
            ResetToken.user_id == user.id,
            ResetToken.purpose == "approve",
            ResetToken.used_at.is_(None),
        )
        .values(used_at=datetime.utcnow())
    )
    await db.commit()
    if user.email and mailer.configured():
        subject, text, html_body = mailer.account_approved_email(
            user.username, f"{_public_base(request)}/"
        )
        background.add_task(mailer.send, user.email, subject, text, html_body)
    logger.info("User %s approved", user.username)


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create a regular account (when self-registration is open).

    With outgoing mail configured the account starts unverified: a
    confirmation link is emailed and the reply is 202 with no login cookie —
    the link signs the user in. Without mail, the account is signed in at once.
    """
    if not get_settings().registration_open:
        raise HTTPException(403, "Registration is closed — ask an administrator for an account")
    username = _validate_username(body.username)
    email = _validate_email(body.email)
    if not email:
        raise HTTPException(400, "Email is required")
    await _ensure_unique(db, username, email)
    verify = mailer.configured()
    needs_approval = get_settings().registration_approval
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(_validate_password(body.password)),
        is_admin=False,
        email_verified=not verify,
        approved=not needs_approval,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(
        "User %s registered%s%s",
        username,
        " (pending verification)" if verify else "",
        " (needs approval)" if needs_approval else "",
    )
    if verify:
        # Admins are asked to approve only once the address is confirmed
        # (see verify_email), so they never get requests for junk sign-ups.
        await _send_verification(db, user, request, background)
        return JSONResponse(
            status_code=202,
            content=RegistrationPending(
                email=email,
                message=(
                    f"We sent a confirmation link to {email}. Open it to finish creating "
                    "your account (check spam if it doesn't arrive)."
                    + (
                        " After that, an administrator has to approve the account before "
                        "you can sign in."
                        if needs_approval
                        else ""
                    )
                ),
            ).model_dump(),
        )
    if needs_approval:
        await _request_approval(db, user, request, background)
        return JSONResponse(
            status_code=202,
            content=RegistrationPending(
                email=email,
                message=(
                    "Your account has been created and is waiting for an administrator to "
                    "approve it. You'll be able to sign in once that's done."
                ),
            ).model_dump(),
        )
    set_login_cookie(response, request, user.id)
    return UserResponse.model_validate(user)


@router.get("/verify")
async def verify_email(
    token: str,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """The emailed confirmation link: mark the address verified and sign in."""
    row = await db.scalar(
        select(ResetToken).where(
            ResetToken.token_hash == hashlib.sha256(token.encode()).hexdigest(),
            ResetToken.purpose == "verify",
        )
    )
    if row is None or row.used_at is not None or row.expires_at < datetime.utcnow():
        return RedirectResponse("/?verified=expired", status_code=302)
    user = await db.get(User, row.user_id)
    if user is None or user.disabled:
        return RedirectResponse("/?verified=expired", status_code=302)
    user.email_verified = True
    row.used_at = datetime.utcnow()
    await db.commit()
    logger.info("User %s verified their email", user.username)
    if not user.approved:
        await _request_approval(db, user, request, background)
        return RedirectResponse("/?verified=pending", status_code=302)
    response = RedirectResponse("/?verified=1", status_code=302)
    set_login_cookie(response, request, user.id)
    return response


@router.post("/verify/resend", status_code=202)
async def resend_verification(
    body: ForgotPasswordRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Send the confirmation link again. Always 202 (never reveals accounts)."""
    key = f"forgot:{_client_ip(request)}"
    wait = ratelimit.retry_after(key)
    if wait:
        raise HTTPException(429, f"Too many requests — try again in {wait} seconds")
    ratelimit.record_failure(key)
    user = await _find_user(db, body.identifier)
    if user and not user.disabled and not user.email_verified and mailer.configured():
        await _send_verification(db, user, request, background)
    return Response(status_code=202)


@router.get("/approve")
async def approve_by_link(
    token: str,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """The approve link emailed to admins. One-time; no sign-in needed, the
    token itself is the authority (only admins' mailboxes receive it)."""
    row = await db.scalar(
        select(ResetToken).where(
            ResetToken.token_hash == hashlib.sha256(token.encode()).hexdigest(),
            ResetToken.purpose == "approve",
        )
    )
    if row is None or row.expires_at < datetime.utcnow():
        return RedirectResponse("/?approved=expired", status_code=302)
    user = await db.get(User, row.user_id)
    if user is None:
        return RedirectResponse("/?approved=expired", status_code=302)
    if user.approved:
        return RedirectResponse(f"/?approved=already&user={user.username}", status_code=302)
    await _approve(user, db, request, background)
    return RedirectResponse(f"/?approved=1&user={user.username}", status_code=302)


@router.post(
    "/users/{user_id}/approve", response_model=UserResponse, dependencies=[Depends(require_admin)]
)
async def approve_user(
    user_id: str,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Admin: activate a pending account from Settings → Users."""
    try:
        user = await db.get(User, uuid.UUID(user_id))
    except ValueError:
        raise HTTPException(404, "User not found")
    if user is None:
        raise HTTPException(404, "User not found")
    if not user.approved:
        await _approve(user, db, request, background)
    return user


@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    """Sign in with a username or email; sets the login cookie.

    Wrong passwords count against both the client address and the account
    name; five in ten minutes locks that pair out for a minute, doubling each
    time (see ``ratelimit``)."""
    keys = (f"ip:{_client_ip(request)}", f"user:{body.username.strip().lower()}")
    wait = ratelimit.retry_after(*keys)
    if wait:
        raise HTTPException(
            429,
            f"Too many failed sign-in attempts — try again in {wait} seconds",
            headers={"Retry-After": str(wait)},
        )
    user = await _find_user(db, body.username)
    # Same error for unknown user and wrong password so accounts can't be probed.
    if user is None or user.disabled or not verify_password(body.password, user.password_hash):
        ratelimit.record_failure(*keys)
        raise HTTPException(401, "Incorrect username/email or password")
    ratelimit.record_success(*keys)
    if not user.email_verified:
        # Right password, so it is safe to say why — and to offer a resend.
        raise HTTPException(
            403,
            {
                "code": "verification_required",
                "message": f"Confirm your email first — we sent a link to {user.email}.",
            },
        )
    if not user.approved:
        raise HTTPException(
            403,
            {
                "code": "approval_pending",
                "message": (
                    "Your account is waiting for an administrator to approve it. "
                    "You'll get an email when it's active."
                ),
            },
        )
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
