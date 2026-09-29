from __future__ import annotations

import uuid
from typing import Any

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    request_id = str(uuid.uuid4())
    detail = response.data
    field_errors: dict[str, Any] = {}
    message = "Request failed"
    if isinstance(detail, dict):
        if "detail" in detail:
            message = str(detail["detail"])
        else:
            field_errors = detail
    elif isinstance(detail, list):
        field_errors = {"non_field_errors": detail}
    else:
        message = str(detail)
    code = {
        400: "invalid_request",
        401: "authentication_required",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        429: "rate_limited",
    }.get(response.status_code, "request_failed")
    response.data = {
        "code": code,
        "message": message,
        "field_errors": field_errors,
        "request_id": request_id,
    }
    response.headers["X-Request-ID"] = request_id
    return response
