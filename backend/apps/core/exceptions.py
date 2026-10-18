"""Domain exceptions -> HTTP errors with one consistent JSON shape: {"error": {"code", "message"}}."""

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

log = logging.getLogger(__name__)


class DomainError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundInIndex(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class UpstreamError(DomainError):
    """The serving microservice (or EDGAR) failed or timed out."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_error"


def api_exception_handler(exc, context):  # type: ignore[no-untyped-def]
    if isinstance(exc, DomainError):
        if exc.status_code >= 500:
            log.error("domain error: %s", exc.message, extra={"code": exc.code})
        return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.status_code)
    response = exception_handler(exc, context)
    if response is not None:
        detail = response.data
        response.data = {"error": {"code": getattr(exc, "default_code", "error"), "message": detail}}
    return response
