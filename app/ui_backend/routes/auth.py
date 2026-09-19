"""Login, logout, and user management (admin)."""

import contextlib
import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from accounts import ratelimit
from accounts.auth import (
    CurrentUser,
    clear_login_cookie,
    current_user,
    forbid_demo,
    hash_password,
    require_admin,
    set_login_cookie,
    verify_password,
)
from core.config import get_settings
from core.database import get_db
from core.models import (
    AudioChunk,
    DocumentUpload,
    DriveFile,
    DriveLink,
    NotesVersion,
    Session,
    TranscriptSegment,
    User,
)
from core.models import PasswordReset as ResetToken
from core.schemas import (
    AccountDelete,
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
from integrations import google_drive, mailer
from storage.s3_client import s3_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{2,64}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8
MAX_PASSWORD_BYTES = 72  # bcrypt's input limit; newer bcrypt raises instead of truncating


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
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        raise HTTPException(400, f"Password must be at most {MAX_PASSWORD_BYTES} characters")
    return password


RESET_MINUTES = 60
VERIFY_HOURS = 24
APPROVE_DAYS = 7


async def _demo_user(db: AsyncSession) -> User | None:
    """The demo account, if an admin created one (and it is not disabled)."""
    return (
        await db.execute(
            select(User).where(User.is_demo.is_(True), User.disabled.is_(False)).limit(1)
        )
    ).scalar_one_or_none()


async def _demo_available(db: AsyncSession) -> bool:
    """Whether to offer "Try the demo". The sign-in page must render even when
    the database is unreachable, so a failed lookup just means "no"."""
    try:
        return await _demo_user(db) is not None
    except Exception:  # noqa: BLE001 — degrade to "no demo", never a 500 on the sign-in page
        return False


@router.get("/status", response_model=RegistrationStatus)
async def registration_status(db: AsyncSession = Depends(get_db)):
    """What the sign-in page may offer; readable without a login."""
    return RegistrationStatus(
        registration_open=get_settings().registration_open,
        registration_approval=get_settings().registration_approval,
        password_reset_available=mailer.configured(),
        demo_available=await _demo_available(db),
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
        cfg = get_settings()
        subject, text, html_body = mailer.account_approved_email(
            user.username,
            f"{_public_base(request)}/",
            cfg.audio_retention_days,
            cfg.max_locked_lectures,
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
        raise HTTPException(404, "User not found") from None
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


@router.delete("/me", status_code=204)
async def delete_own_account(
    body: AccountDelete,
    response: Response,
    user: CurrentUser = Depends(forbid_demo),
    db: AsyncSession = Depends(get_db),
):
    """Delete your own account and everything in it: lectures (transcripts,
    notes, documents, audio objects), the Google Drive link (revoked at
    Google; files already in the Drive are the user's and stay). Requires
    the current password. The last admin cannot delete themselves."""
    row = await db.get(User, user.id)
    if row is None or not verify_password(body.password, row.password_hash):
        raise HTTPException(403, "Incorrect password")
    if row.is_admin:
        admins = await db.scalar(
            select(func.count()).select_from(User).where(User.is_admin.is_(True))
        )
        if (admins or 0) <= 1:
            raise HTTPException(400, "You are the only administrator — add another before deleting")

    # Google Drive: revoke and forget.
    link = await db.get(DriveLink, row.id)
    if link is not None:
        with contextlib.suppress(google_drive.DriveError):
            await google_drive.revoke(google_drive.decrypt(link.refresh_token))
        await db.delete(link)

    # Lectures and their audio objects.
    session_ids = (
        (await db.execute(select(Session.id).where(Session.user_id == row.id))).scalars().all()
    )
    if session_ids:
        chunks = (
            (await db.execute(select(AudioChunk).where(AudioChunk.session_id.in_(session_ids))))
            .scalars()
            .all()
        )
        for chunk in chunks:
            if chunk.s3_key and not chunk.deleted_from_s3:
                try:
                    s3_client.delete_object(chunk.s3_bucket, chunk.s3_key)
                except Exception as e:  # noqa: BLE001 — best effort; the row goes anyway
                    logger.warning("Could not delete %s: %s", chunk.s3_key, e)
        for model in (TranscriptSegment, AudioChunk, NotesVersion, DocumentUpload, DriveFile):
            await db.execute(delete(model).where(model.session_id.in_(session_ids)))
        await db.execute(delete(Session).where(Session.id.in_(session_ids)))
    await db.execute(delete(ResetToken).where(ResetToken.user_id == row.id))
    await db.delete(row)
    await db.commit()
    clear_login_cookie(response)
    logger.info(
        "User %s deleted their own account (%d lectures removed)", row.username, len(session_ids)
    )
    return Response(status_code=204)


@router.post("/demo", response_model=UserResponse)
async def demo_login(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """ "Try the demo": sign in as the read-only demo account, no password.

    Rate-limited per address like sign-in, so it can't be used to hammer the
    server; what the account can do is limited by ``forbid_demo``."""
    key = f"demo:{_client_ip(request)}"
    allowed, wait = ratelimit.allow(key, 10, 10 * 60)
    if not allowed:
        raise HTTPException(429, f"Too many demo sign-ins — try again in {wait} seconds")
    user = await _demo_user(db)
    if user is None:
        raise HTTPException(404, "There is no demo account on this server")
    set_login_cookie(response, request, user.id)
    logger.info("Demo sign-in from %s", _client_ip(request))
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
    user: CurrentUser = Depends(forbid_demo),
    db: AsyncSession = Depends(get_db),
):
    """Let the signed-in user set or change their email address."""
    row = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
    email = _validate_email(body.email)
    if (
        email
        and email != row.email
        and (
            await db.execute(select(User).where(User.email == email, User.id != user.id))
        ).scalar_one_or_none()
    ):
        raise HTTPException(409, "An account with that email already exists")
    row.email = email
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChange,
    user: CurrentUser = Depends(forbid_demo),
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
    if body.is_admin and body.is_demo:
        raise HTTPException(400, "A demo account can't be an admin")
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(_validate_password(body.password)),
        is_admin=body.is_admin,
        is_demo=body.is_demo,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("User %s created (admin=%s, demo=%s)", username, body.is_admin, body.is_demo)
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
