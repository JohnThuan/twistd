"""Pure-ASGI middleware: request body size limit and security response headers."""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_JSON = [(b"content-type", b"application/json")]

# The API only returns JSON, so lock everything down. The interactive docs pages
# load Swagger/ReDoc assets from a CDN and need a looser policy.
_API_CSP = b"default-src 'none'; frame-ancestors 'none'"
_DOCS_CSP = (
    b"default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    b"font-src https://fonts.gstatic.com; img-src 'self' data: https://fastapi.tiangolo.com; "
    b"connect-src 'self'; worker-src blob:; frame-ancestors 'none'"
)
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

_BASE_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"cache-control", b"no-store"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        csp = _DOCS_CSP if scope["path"].startswith(_DOCS_PATHS) else _API_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in _BASE_HEADERS if k not in present]
                extra.append((b"content-security-policy", csp))
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Reject request bodies over `max_bytes` with 413, without buffering them.

    Checks Content-Length up front, and also counts streamed bytes so a client
    that lies about (or omits) Content-Length can't get past the limit.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    await self._reject(send, 400, "invalid Content-Length header")
                    return
                if declared > self.max_bytes:
                    await self._reject(send, 413, self._too_large())
                    return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not response_started:
                await self._reject(send, 413, self._too_large())

    def _too_large(self) -> str:
        return f"request body exceeds {self.max_bytes} bytes"

    @staticmethod
    async def _reject(send: Send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode()
        headers = [*_JSON, (b"content-length", str(len(body)).encode())]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass
