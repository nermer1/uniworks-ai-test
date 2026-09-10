"""모니터링/컨텍스트 미들웨어.

- RequestContextMiddleware: 요청마다 request_id 생성 → contextvar set + 응답 헤더(X-Request-ID).
  순수 ASGI 미들웨어라 contextvar가 라우트 핸들러·예외 핸들러까지 확실히 전파됨
  (BaseHTTPMiddleware는 별 태스크로 돌아 contextvar 전파가 안 될 수 있음).
- AccessLogMiddleware: 접근 로그(method/path/status/ms)를 SQLite access_log에.
"""
import time
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware

from core.db import connect
from core.context import request_id_var
from core.logging_setup import get_logger

_access_log = get_logger("access")


def recent_logs(limit: int = 100) -> list[dict]:
    """최근 접근 로그 (개발자 관측 화면용)."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT ts, method, path, status, ms FROM access_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = "req_" + uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        ms = round((time.perf_counter() - t0) * 1000)
        # 스트림/파일 로그 (request_id 포함) — 쿼리는 access_log 테이블, 스트림은 여기.
        _access_log.info("request", extra={"method": request.method, "path": request.url.path,
                                           "status": response.status_code, "ms": ms})
        try:
            conn = connect()
            conn.execute(
                "INSERT INTO access_log (ts, method, path, status, ms) VALUES (?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), request.method,
                 request.url.path, response.status_code, ms),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass  # 로깅 실패가 요청을 죽이지 않게
        return response
