"""Request correlation: every log line emitted while handling a request carries its request_id (and user_id)."""

import logging
import re
import uuid
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_user_id: ContextVar[str] = ContextVar("user_id", default="-")
_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.user_id = _user_id.get()
        return True


class RequestIdMiddleware:
    def __init__(self, get_response):  # type: ignore[no-untyped-def]
        self.get_response = get_response

    def __call__(self, request):  # type: ignore[no-untyped-def]
        # accept an upstream id (proxy / client) only if it is harmless to put in logs and headers
        incoming = request.headers.get("X-Request-ID", "")
        rid = incoming if _SAFE.match(incoming) else uuid.uuid4().hex
        t1 = _request_id.set(rid)
        t2 = _user_id.set("-")
        request.request_id = rid
        try:
            response = self.get_response(request)
            user = getattr(request, "user", None)  # resolved by auth middleware / DRF during the request
            if user is not None and getattr(user, "is_authenticated", False):
                _user_id.set(str(user.pk))
            response["X-Request-ID"] = rid
            return response
        finally:
            _request_id.reset(t1)
            _user_id.reset(t2)
