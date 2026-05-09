"""
Request-ID Middleware

Injects a unique X-Request-ID into every request so all log lines from a single
request share a correlation ID. Accepts a client-supplied X-Request-ID header
(useful when the caller already has an ID it wants to track) and falls back to a
server-generated UUID4.

The ID is stored in a ContextVar so it is readable anywhere in the call stack
(logger formatters, services, tasks) without being passed as an argument.

Implemented as a pure ASGI middleware (not BaseHTTPMiddleware) to avoid the
known Starlette bug where BaseHTTPMiddleware mishandles anyio ExceptionGroups
on Python 3.11+, causing spurious "No response returned." RuntimeErrors.
"""
import uuid
from starlette.types import ASGIApp, Receive, Scope, Send

from app.utils.request_context import _request_id_var


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        request_id = (
            headers.get(b"x-request-id", b"").decode() or str(uuid.uuid4())
        )
        token = _request_id_var.set(request_id)

        async def send_with_request_id(message: dict) -> None:
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))
                raw_headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": raw_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _request_id_var.reset(token)
