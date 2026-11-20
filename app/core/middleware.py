import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.logging import reset_request_id, set_request_id

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid4().hex
        token = set_request_id(request_id)
        request.state.request_id = request_id
        start = perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            logger.info(
                "request method=%s path=%s status=%s latency_ms=%.2f",
                request.method,
                request.url.path,
                status,
                (perf_counter() - start) * 1000,
            )
            reset_request_id(token)
