import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class PropLensError(Exception):
    code = "internal_error"
    status_code = 500
    public_message = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.public_message)


class LLMError(PropLensError):
    code = "llm_error"
    status_code = 502
    public_message = "The assistant is temporarily unavailable."


class RetrievalError(PropLensError):
    code = "retrieval_error"
    status_code = 503
    public_message = "Property search is temporarily unavailable."


class DataNotLoadedError(PropLensError):
    code = "data_not_loaded"
    status_code = 503
    public_message = "Property data is not loaded yet."


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(PropLensError)
    async def handle_proplens_error(_request: Request, exc: PropLensError) -> JSONResponse:
        logger.warning("Application error: %s", exc)
        return error_response(exc.status_code, exc.code, exc.public_message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(422, "validation_error", "Invalid request data.")

    @app.exception_handler(HTTPException)
    async def handle_http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        return error_response(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=exc)
        return error_response(500, "internal_error", "An unexpected error occurred.")
