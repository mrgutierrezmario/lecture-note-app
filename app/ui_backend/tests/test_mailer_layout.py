"""Every Lecture Notes email goes out in the shared M.G. layout, with its
plain-text part, and user-supplied names stay escaped."""

import email
from unittest.mock import patch

from integrations import mailer


class _FakeSMTP:
    sent: list[str] = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a):
        pass

    def sendmail(self, _from, _to, raw):
        _FakeSMTP.sent.append(raw)


def test_shell_brands_and_escapes():
    doc = mailer._shell("<b>t</b>", "<p>body</p>")
    assert doc.lstrip().lower().startswith("<!doctype html>")
    assert "https://mgnetsolutions.com/email-logo.png" in doc
    assert "AI Lecture Notes by M.G. Network and Technology Solutions" in doc
    assert "<b>t</b>" not in doc and "&lt;b&gt;t&lt;/b&gt;" in doc
    assert "<p>body</p>" in doc


def test_sent_mail_is_wrapped_and_keeps_its_text_part():
    subject, text, body = mailer.password_reset_email("<jane>", "https://x.test/r?t=1", 60)
    _FakeSMTP.sent = []
    with patch("smtplib.SMTP_SSL", _FakeSMTP):
        mailer._send_sync("u@example.com", subject, text, body)
    msg = email.message_from_string(_FakeSMTP.sent[0])
    parts = {
        p.get_content_type(): p.get_payload(decode=True).decode()
        for p in msg.walk()
        if p.get_content_type() in ("text/plain", "text/html")
    }
    assert set(parts) == {"text/plain", "text/html"}
    assert "AI Lecture Notes by M.G. Network and Technology Solutions" in parts["text/html"]
    assert "<jane>" not in parts["text/html"] and "&lt;jane&gt;" in parts["text/html"]
    assert "https://x.test/r?t=1" in parts["text/plain"]
