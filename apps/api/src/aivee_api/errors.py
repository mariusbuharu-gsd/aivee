"""Domain errors and their HTTP mapping. Messages are Romanian: the dashboard shows them."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aivee_api.rules.translator import TranslationError


class DomainError(Exception):
    status = 400
    code = "error"

    def __init__(self, message_ro: str) -> None:
        super().__init__(message_ro)
        self.message_ro = message_ro


class Unauthenticated(DomainError):
    status = 401
    code = "unauthenticated"


class Forbidden(DomainError):
    status = 403
    code = "forbidden"


class RateLimited(DomainError):
    status = 429
    code = "rate_limited"


class NotFound(DomainError):
    status = 404
    code = "not_found"


class Conflict(DomainError):
    status = 409
    code = "conflict"


class Invalid(DomainError):
    status = 422
    code = "invalid"


class Unavailable(DomainError):
    status = 503
    code = "unavailable"


_TRANSLATION_STATUS = {"rate_limited": 429, "unavailable": 503}


def _body(code: str, message_ro: str) -> dict[str, dict[str, str]]:
    return {"detail": {"code": code, "message_ro": message_ro}}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, e: DomainError) -> JSONResponse:
        return JSONResponse(_body(e.code, e.message_ro), e.status)

    @app.exception_handler(TranslationError)
    async def _translation(_: Request, e: TranslationError) -> JSONResponse:
        return JSONResponse(_body(e.code, e.message_ro), _TRANSLATION_STATUS.get(e.code, 422))
