"""Outgoing email over SMTP (Gmail App Password by default).

Same transport as the stock-tracker project: SMTP over SSL, credentials from
.env. Sending runs in a thread so the event loop never blocks on the network.
"""

import asyncio
import html
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from core.config import get_settings

logger = logging.getLogger(__name__)


def configured() -> bool:
    """``True`` when an SMTP username, password and sender are all set."""
    s = get_settings()
    return bool(s.mail_username and s.mail_password and (s.mail_from or s.mail_username))


def _clean(value: str) -> str:
    # Header values must never carry CR/LF (header injection).
    return (value or "").replace("\r", "").replace("\n", "").strip()


LOGO_URL = "https://mgnetsolutions.com/email-logo.png"
PRODUCT = "AI Lecture Notes"
COMPANY = "M.G. Network and Technology Solutions"


_FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_CARD = (
    "max-width:600px;background:#ffffff;border:1px solid #dfe5ee;"
    f"border-radius:10px;overflow:hidden;font-family:{_FONT};"
)
_BAR = (
    "height:4px;line-height:4px;font-size:0;background:#12bceb;"
    "background-image:linear-gradient(90deg,#0B74F6,#12BCEB 52%,#11D4B2);"
)
_FOOT = (
    "padding:18px 28px 24px;color:#51607a;font-size:12px;line-height:1.5;"
    "border-top:1px solid #dfe5ee;"
)
_NAME = "vertical-align:middle;color:#ffffff;font-size:20px;font-weight:800;"
_TABLE = 'role="presentation" width="100%" cellpadding="0" cellspacing="0"'


def _shell(title: str, body: str) -> str:
    """The layout every email shares with the other M.G. apps and
    mgnetsolutions.com: navy header with the MG logo and the product name, the
    blue-teal line, a light card, and a footer naming the company. Table layout
    and inline styles, because that is what mail clients render reliably."""
    site = (get_settings().public_url or "").rstrip("/")
    home = ""
    if site:
        host = html.escape(site.split("://", 1)[-1])
        href = html.escape(site, quote=True)
        home = f' · <a href="{href}" style="color:#51607a;">{host}</a>'
    logo = (
        f'<img src="{LOGO_URL}" width="120" height="65" alt="{COMPANY}" '
        'style="display:block;border:0;">'
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{html.escape(title)}</title>
</head>
<body style="margin:0;padding:0;background:#f4f6fa;">
<table {_TABLE} style="background:#f4f6fa;">
  <tr><td align="center" style="padding:24px 12px;">
    <table {_TABLE} style="{_CARD}">
      <tr><td style="background:#0a1430;padding:20px 28px;">
        <table {_TABLE}><tr>
          <td style="vertical-align:middle;">{logo}</td>
          <td align="right" style="{_NAME}">{PRODUCT}</td>
        </tr></table>
      </td></tr>
      <tr><td style="{_BAR}">&nbsp;</td></tr>
      <tr><td style="padding:8px 4px 4px;">{body}</td></tr>
      <tr><td style="{_FOOT}">{PRODUCT} by {COMPANY}{home}</td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def _send_sync(to: str, subject: str, text: str, html_body: str) -> None:
    s = get_settings()
    if not html_body.lstrip().lower().startswith("<!doctype"):
        html_body = _shell(subject, html_body)
    from_addr = _clean(s.mail_from or s.mail_username)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = _clean(subject)
    msg["From"] = formataddr((_clean(s.mail_from_name), from_addr))
    msg["To"] = _clean(to)
    if s.mail_reply_to:
        msg["Reply-To"] = _clean(s.mail_reply_to)
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL(s.mail_server, s.mail_port, timeout=30) as server:
        server.login(s.mail_username, s.mail_password)
        server.sendmail(from_addr, [msg["To"]], msg.as_string())


async def send(to: str, subject: str, text: str, html_body: str) -> bool:
    """Send one email; returns ``False`` (and logs) instead of raising on failure."""
    if not configured():
        logger.warning("Mail not configured; would have sent %r to %s", subject, to)
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, text, html_body)
        logger.info("Sent %r to %s", subject, to)
        return True
    except Exception as e:
        logger.error("Failed to send %r to %s: %s: %s", subject, to, type(e).__name__, e)
        return False


def password_reset_email(username: str, link: str, minutes: int) -> tuple[str, str, str]:
    """(subject, text, html) for a reset link."""
    subject = "Reset your AI Lecture Notes password"
    text = (
        f"Hi {username},\n\n"
        f"Someone asked to reset the password for your AI Lecture Notes account. "
        f"Open this link within {minutes} minutes to choose a new password:\n\n{link}\n\n"
        "If you didn't ask for this, you can ignore this email. Your password stays the same.\n\n"
        "This is an automated message; replies are not monitored."
    )
    body = f"""
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:480px;
            margin:0 auto;padding:24px;color:#0f1f3d">
  <h2 style="margin:0 0 12px;font-size:20px">Reset your password</h2>
  <p style="margin:0 0 16px;line-height:1.5">Hi {html.escape(username)}, someone asked to reset
  the password for your
  AI Lecture Notes account. This link works for {minutes} minutes:</p>
  <p style="margin:0 0 20px"><a href="{html.escape(link, quote=True)}"
     style="display:inline-block;background:#0a5fd1;color:#fff;text-decoration:none;
            padding:12px 18px;border-radius:8px;font-weight:600">
     Choose a new password</a></p>
  <p style="margin:0 0 8px;font-size:13px;color:#5b6b86">Or paste this into your browser:<br>
     <span style="word-break:break-all">{html.escape(link)}</span></p>
  <p style="margin:16px 0 0;font-size:13px;color:#5b6b86">If you didn't ask for this, ignore this
  email. Your password stays the same.</p>
  <p style="margin:16px 0 0;font-size:12px;color:#8a97ae">This is an automated message; replies
  are not monitored.</p>
</div>"""
    return subject, text, body


def verify_email(username: str, link: str, hours: int) -> tuple[str, str, str]:
    """(subject, text, html) for the address-confirmation link sent on sign-up."""
    subject = "Confirm your email for AI Lecture Notes"
    text = (
        f"Hi {username},\n\n"
        f"Welcome to AI Lecture Notes. Confirm this email address to finish creating your "
        f"account. The link works for {hours} hours:\n\n{link}\n\n"
        "If you didn't sign up, you can ignore this email.\n\n"
        "This is an automated message; replies are not monitored."
    )
    body = f"""
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:480px;
            margin:0 auto;padding:24px;color:#0f1f3d">
  <h2 style="margin:0 0 12px;font-size:20px">Confirm your email</h2>
  <p style="margin:0 0 16px;line-height:1.5">Hi {html.escape(username)}, welcome to AI Lecture
  Notes. Confirm this address to finish creating your account. The link works for {hours}
  hours:</p>
  <p style="margin:0 0 20px"><a href="{html.escape(link, quote=True)}"
     style="display:inline-block;background:#0a5fd1;color:#fff;text-decoration:none;
            padding:12px 18px;border-radius:8px;font-weight:600">
     Confirm email</a></p>
  <p style="margin:0 0 8px;font-size:13px;color:#5b6b86">Or paste this into your browser:<br>
     <span style="word-break:break-all">{html.escape(link)}</span></p>
  <p style="margin:16px 0 0;font-size:13px;color:#5b6b86">If you didn't sign up, ignore this
  email.</p>
  <p style="margin:16px 0 0;font-size:12px;color:#8a97ae">This is an automated message; replies
  are not monitored.</p>
</div>"""
    return subject, text, body


def _wrap(title: str, intro: str, button: str, link: str, outro: str) -> str:
    """Shared HTML frame for the short transactional emails."""
    button_html = ""
    if link:
        safe_link = html.escape(link, quote=True)
        button_html = (
            f"<p style='margin:0 0 20px'><a href='{safe_link}' style='display:inline-block;"
            "background:#0a5fd1;color:#fff;text-decoration:none;padding:12px 18px;"
            f"border-radius:8px;font-weight:600'>{html.escape(button)}</a></p>"
            "<p style='margin:0 0 8px;font-size:13px;color:#5b6b86'>Or paste this into your "
            f"browser:<br><span style='word-break:break-all'>{html.escape(link)}</span></p>"
        )
    return f"""
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:480px;
            margin:0 auto;padding:24px;color:#0f1f3d">
  <h2 style="margin:0 0 12px;font-size:20px">{html.escape(title)}</h2>
  <p style="margin:0 0 16px;line-height:1.5">{intro}</p>
  {button_html}
  <p style="margin:16px 0 0;font-size:13px;color:#5b6b86">{outro}</p>
  <p style="margin:16px 0 0;font-size:12px;color:#8a97ae">This is an automated message; replies
  are not monitored.</p>
</div>"""


def approval_request_email(username: str, email: str, link: str, days: int) -> tuple[str, str, str]:
    """(subject, text, html) sent to admins when a new account needs approval."""
    subject = f"New account request: {username}"
    text = (
        f"{username} ({email}) has created an AI Lecture Notes account and confirmed their "
        f"email. They can't sign in until you approve the account.\n\n"
        f"Approve: {link}\n\n"
        f"The link works for {days} days. You can also approve or delete the account under "
        "Settings → Users.\n\nThis is an automated message; replies are not monitored."
    )
    body = _wrap(
        "New account request",
        f"<strong>{html.escape(username)}</strong> ({html.escape(email)}) has created an "
        "account and confirmed their email. They can't sign in until you approve it.",
        "Approve this account",
        link,
        f"The link works for {days} days. You can also approve or delete the account under "
        "Settings → Users.",
    )
    return subject, text, body


def account_approved_email(
    username: str, link: str, retention_days: int, keep_limit: int
) -> tuple[str, str, str]:
    """(subject, text, html) telling a user their account is active, with the
    things they must know before the first lecture (audio retention above all)."""
    subject = "Your AI Lecture Notes account is active"
    keep = f" (up to {keep_limit} lectures)" if keep_limit else ""
    guide = link.rstrip("/") + "/guide"
    text = (
        f"Hi {username},\n\n"
        f"Your account has been approved, so you can sign in now:\n\n{link}\n\n"
        "A few things worth knowing before your first lecture:\n\n"
        f"- Recordings are kept for {retention_days} days. After that the audio is deleted "
        "automatically; the transcript and notes stay. Download the MP3 from History before "
        f"then, or mark the lecture as Kept to protect it{keep}.\n"
        "- Save everything to your own Google Drive. Connect your Google account under "
        "Settings > Google Drive and each lecture's notes, transcript and MP3 are saved there "
        "automatically when you stop recording.\n"
        "- Online class? For Zoom in a browser tab, turn on Tab audio before you start. On a "
        "phone, use speakerphone.\n\n"
        f"The User Guide covers the rest: {guide}\n\n"
        "This is an automated message; replies are not monitored."
    )
    outro = (
        "<strong>A few things worth knowing before your first lecture:</strong>"
        "<ul style='margin:8px 0 0;padding-left:20px;line-height:1.5'>"
        f"<li><strong>Recordings are kept for {retention_days} days.</strong> After that the "
        "audio is deleted automatically; the transcript and notes stay. Download the MP3 from "
        "History before then, or mark the lecture as <strong>Kept</strong> to protect it"
        f"{html.escape(keep)}.</li>"
        "<li><strong>Save everything to your own Google Drive.</strong> Connect your Google "
        "account under Settings → Google Drive and each lecture's notes, transcript and MP3 "
        "are saved there automatically when you stop recording.</li>"
        "<li><strong>Online class?</strong> For Zoom in a browser tab, turn on <em>Tab audio</em> "
        "before you start. On a phone, use speakerphone.</li>"
        "</ul>"
        f"<p style='margin:12px 0 0'>The <a href='{html.escape(guide, quote=True)}'>User Guide</a> "
        "covers the rest.</p>"
    )
    body = _wrap(
        "Your account is active",
        f"Hi {html.escape(username)}, your account has been approved, so you can sign in now.",
        "Sign in",
        link,
        outro,
    )
    return subject, text, body
