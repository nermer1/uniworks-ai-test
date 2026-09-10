"""시스템 로깅 — stdlib logging + JSON 포매터 + request_id. 의존성 0.

출력: stdout(docker logs가 수집) + 회전 파일(log/app.log, 10MB×5).
매 로그 줄에 request_id를 박아, 응답 헤더 X-Request-ID로 로그를 바로 검색 가능.
'aiplatform' 네임스페이스만 설정(uvicorn 로깅과 안 싸우게, propagate=False).
"""
import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from core.config import PROJECT_ROOT
from core.context import request_id_var

LOG_DIR = PROJECT_ROOT / "log"
_EXTRA_KEYS = ("method", "path", "status", "ms")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "request_id": getattr(record, "request_id", "-"),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k in _EXTRA_KEYS:                 # method/path/status/ms 등 있으면 실음
            if hasattr(record, k):
                obj[k] = getattr(record, k)
        if record.exc_info:                   # 예외면 스택도
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = JsonFormatter()
    filt = RequestIdFilter()

    stream = logging.StreamHandler(sys.stdout)
    fileh = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=10 * 1024 * 1024,
                                backupCount=5, encoding="utf-8")
    for h in (stream, fileh):
        h.setFormatter(fmt)
        h.addFilter(filt)

    lg = logging.getLogger("aiplatform")
    lg.setLevel(level)
    lg.handlers.clear()
    lg.propagate = False
    lg.addHandler(stream)
    lg.addHandler(fileh)


def get_logger(name: str) -> logging.Logger:
    """모듈용 로거 — 'aiplatform.<name>' (설정된 aiplatform 핸들러로 전파)."""
    return logging.getLogger(f"aiplatform.{name}")
