"""Browser security headers on every HTTP response.

Plain ASGI (not BaseHTTPMiddleware) so streamed downloads such as the MP3
export pass through untouched; WebSocket traffic is left alone.

The content policy allows only this site plus what the UI loads from Google:
the Plus Jakarta Sans font, and the Drive folder picker (lib/drivePicker.js),
which runs Google's script and opens its dialog in a frame.
"""

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' https://apis.google.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: blob: https://*.googleusercontent.com https://*.gstatic.com",
        "media-src 'self' blob:",
        "connect-src 'self' https://*.googleapis.com",
        "frame-src https://docs.google.com https://drive.google.com https://accounts.google.com "
        "https://content.googleapis.com",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self' https://accounts.google.com",
        "frame-ancestors 'self'",
    ]
)

HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-frame-options", b"SAMEORIGIN"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"strict-transport-security", b"max-age=31536000"),
    # The recorder needs the microphone on this site; nothing needs the rest.
    (b"permissions-policy", b"microphone=(self), camera=(), geolocation=()"),
]
_NAMES = {name for name, _ in HEADERS}


class SecurityHeadersMiddleware:
    """Add ``HEADERS`` to every HTTP response (replacing any the app set)."""

    def __init__(self, app):
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope, receive, send):
        """Pass the request through, adding the headers to its response."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in _NAMES]
                message["headers"] = kept + HEADERS
            await send(message)

        await self.app(scope, receive, send_with_headers)
