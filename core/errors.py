"""에러 모델 + 전역 예외 핸들러 — 모든 실패를 통일된 envelope로.

모듈/코어는 ApiError(code, message, status)를 raise만 하면 됨.
안 잡힌 예외는 스택을 로그로 남기고, 클라이언트엔 일반 메시지만(내부정보 유출 방지).
"""
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.envelope import error_body
from core.logging_setup import get_logger

logger = get_logger("errors")


class ApiError(Exception):
    """도메인 에러 — code(기계용)·message(사람용)·status·detail(선택)."""
    def __init__(self, code: str, message: str, status: int = 400, detail=None):
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail
        super().__init__(message)


_HTTP_CODE = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN",
              404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 429: "RATE_LIMITED"}


def register_error_handlers(app) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request, exc: ApiError):
        return JSONResponse(error_body(exc.code, exc.message, exc.detail), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request, exc: RequestValidationError):
        # 요청 형식 오류(422) — 어느 필드가 문제인지 detail에.
        return JSONResponse(
            error_body("VALIDATION_ERROR", "요청 형식이 올바르지 않습니다", exc.errors()),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request, exc: StarletteHTTPException):
        # 인증/권한(HTTPException)·404 등 → 같은 envelope로.
        code = _HTTP_CODE.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request, exc: Exception):
        # 안 잡힌 예외: 스택은 로그로, 클라이언트엔 일반 메시지(내부 유출 X).
        logger.exception("unhandled error: %s %s", request.method, request.url.path)
        return JSONResponse(error_body("INTERNAL_ERROR", "서버 내부 오류가 발생했습니다"), status_code=500)
