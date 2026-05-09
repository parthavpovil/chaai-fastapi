"""
Request-ID Middleware

Injects a unique X-Request-ID into every request so all log lines from a single
request share a correlation ID. Accepts a client-supplied X-Request-ID header
(useful when the caller already has an ID it wants to track) and falls back to a
server-generated UUID4.

The ID is stored in a ContextVar so it is readable anywhere in the call stack
(logger formatters, services, tasks) without being passed as an argument.
"""
import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.request_context import _request_id_var


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = _request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            _request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response
