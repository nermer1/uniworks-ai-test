"""요청 단위 컨텍스트 — request_id를 어디서나(envelope·로그·에러) 읽게.

미들웨어가 요청마다 set. contextvar라 파라미터로 안 넘겨도 됨.
"""
import contextvars

request_id_var: "contextvars.ContextVar[str]" = contextvars.ContextVar("request_id", default="-")
