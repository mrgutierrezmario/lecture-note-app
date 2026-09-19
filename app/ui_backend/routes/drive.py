"""Per-user Google Drive connection: status, connect (OAuth), disconnect, options.

The OAuth round trip is two requests: ``GET /api/drive/connect`` sends the
browser to Google's consent page; Google sends it back to
``GET /api/drive/callback`` with a code, which is exchanged for a refresh
token and stored. Both run with the normal login cookie, and the ``state``
parameter is bound to the signed-in user so a callback can't be replayed
into someone else's account.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from accounts.auth import CurrentUser, current_user
from core.database import get_db
from core.models import DriveLink
from core.schemas import DrivePickerToken, DriveStatus, DriveUpdate
from integrations import google_drive

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drive", tags=["drive"])


def _status(link: DriveLink | None) -> DriveStatus:
    return DriveStatus(
        available=google_drive.configured(),
        connected=link is not None,
        email=link.google_email if link else None,
        auto_export=bool(link.auto_export) if link else False,
        folder_name=link.folder_name if link else "AI Lecture Notes",
        folder_url=(
            f"https://drive.google.com/drive/folders/{link.folder_id}"
            if link and link.folder_id
            else None
        ),
        picker_available=google_drive.picker_available(),
    )


@router.get("", response_model=DriveStatus)
async def read_status(
    user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Whether Drive export is available, and this user's connection."""
    return _status(await db.get(DriveLink, user.id))


@router.get("/connect")
async def connect(user: CurrentUser = Depends(current_user)):
    """Send the browser to Google to authorise the app (drive.file scope only)."""
    if not google_drive.configured():
        raise HTTPException(status_code=400, detail="Google Drive is not set up on this server")
    return RedirectResponse(google_drive.auth_url(user.id), status_code=302)


@router.get("/callback")
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Google's return trip: store the refresh token, then land back in the app."""
    if error or not code or not state:
        return RedirectResponse(f"/?drive=error&reason={error or 'cancelled'}", status_code=302)
    if not google_drive.check_state(state, user.id):
        return RedirectResponse("/?drive=error&reason=expired", status_code=302)
    try:
        refresh_token, email = await google_drive.exchange_code(code)
    except google_drive.DriveError as e:
        logger.warning("Drive connect failed for %s: %s", user.username, e)
        return RedirectResponse("/?drive=error&reason=google", status_code=302)

    link = await db.get(DriveLink, user.id)
    if link is None:
        link = DriveLink(user_id=user.id, auto_export=True)
        db.add(link)
    link.refresh_token = google_drive.encrypt(refresh_token)
    link.google_email = email
    await db.commit()
    logger.info("User %s connected Google Drive (%s)", user.username, email)
    return RedirectResponse("/?drive=connected", status_code=302)


@router.get("/picker-token", response_model=DrivePickerToken)
async def picker_token(
    user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Credentials for Google's folder picker: the user's own short-lived access
    token (their Drive, drive.file scope), the Picker API key and the app id."""
    if not google_drive.picker_available():
        raise HTTPException(
            status_code=400, detail="The folder chooser is not set up on this server"
        )
    link = await db.get(DriveLink, user.id)
    if link is None:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
    try:
        token = await google_drive.access_token_for(link)
    except google_drive.DriveError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return DrivePickerToken(
        access_token=token,
        api_key=google_drive.settings.google_picker_api_key.strip(),
        app_id=google_drive.app_id(),
    )


@router.patch("", response_model=DriveStatus)
async def update(
    body: DriveUpdate,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Turn automatic saving on or off, or change the folder path in Drive.

    A new path is created in the user's Drive right away, so the folder link
    works immediately; lectures already saved keep updating where they are."""
    link = await db.get(DriveLink, user.id)
    if link is None:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
    if body.auto_export is not None:
        link.auto_export = body.auto_export
    if body.folder_id is not None:
        # An existing folder chosen with Google's picker: the picker granted the
        # app access to it, so it can be read back to confirm and get its name.
        try:
            name = await google_drive.folder_name_of(link, body.folder_id.strip())
        except google_drive.DriveError as e:
            raise HTTPException(status_code=400, detail=str(e))
        link.folder_id = body.folder_id.strip()
        link.folder_name = name
    elif body.folder_name is not None:
        name = google_drive.clean_folder_path(body.folder_name)
        if not name:
            raise HTTPException(status_code=422, detail="Folder name can't be empty")
        if name != link.folder_name or not link.folder_id:
            link.folder_name = name
            try:
                link.folder_id = await google_drive.create_folder_now(link)
            except google_drive.DriveError as e:
                raise HTTPException(status_code=502, detail=str(e))
    await db.commit()
    return _status(link)


@router.delete("", response_model=DriveStatus)
async def disconnect(user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Forget the connection and ask Google to revoke it. Files already in
    the Drive stay there — they belong to the user."""
    link = await db.get(DriveLink, user.id)
    if link is not None:
        try:
            await google_drive.revoke(google_drive.decrypt(link.refresh_token))
        except google_drive.DriveError:
            pass  # unreadable token: nothing to revoke
        await db.delete(link)
        await db.commit()
        logger.info("User %s disconnected Google Drive", user.username)
    return _status(None)
