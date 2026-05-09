"""
Request-scoped context variables.

Import get_request_id() anywhere — logging, services — to read the current
X-Request-ID without threading the value through every function signature.
"""
from contextvars import ContextVar

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    return _request_id_var.get()
