"""AI API Platform — 앱 조립점.

코어 초기화(DB) → 미들웨어(요청ID·접근로그) → 전역 에러 핸들러 → 코어 라우트 → 계약 모듈 mount.
실행: py -m uvicorn app:app --port 8080
"""
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from core.logging_setup import setup_logging, get_logger
from core.config import PROJECT_ROOT
from core.db import init_db
from core.monitoring import AccessLogMiddleware, RequestContextMiddleware, recent_logs
from core.errors import register_error_handlers
from core.envelope import success
from core.registry import mount_modules
from core.permissions import require_permission
from core.user_auth import User
from core.auth_routes import router as auth_router
from core.admin_routes import router as admin_router
from core import ledger

setup_logging()          # 로깅 먼저 (이후 모든 로그가 JSON+request_id로)
init_db()
_log = get_logger("app")

app = FastAPI(title="AI API Platform")

# 미들웨어: 나중에 add한 게 최외곽. RequestContext가 최외곽이라 request_id가 제일 먼저 셋됨.
app.add_middleware(AccessLogMiddleware)
app.add_middleware(RequestContextMiddleware)

# 전역 에러 핸들러 — 모든 실패를 통일 envelope로.
register_error_handlers(app)


@app.get("/core/health")
def health():
    return success({"status": "ok"})


@app.get("/core/usage")
def usage(user: User = Depends(require_permission("usage:read"))):
    """고객사별 사용량 롤업 — 회계 화면(회계/관리자 role)이 소비."""
    return success({"rollup": ledger.rollup()})


@app.get("/core/logs")
def logs(user: User = Depends(require_permission("logs:read"))):
    """최근 접근 로그 — 개발자 관측 화면이 소비."""
    return success({"logs": recent_logs()})


# ── 사내 화면(HTML) 서빙 ──
WEB_DIR = PROJECT_ROOT / "web"


@app.get("/")
def index_page():
    return FileResponse(WEB_DIR / "app.html")


@app.get("/login")
def login_page():
    return FileResponse(WEB_DIR / "login.html")


app.include_router(auth_router)          # /auth/login · logout · me
app.include_router(admin_router)         # /admin/users (관리자 유저 관리)
_mounted = mount_modules(app)

# 정적 자원(css/js) — /static/styles.css, /static/app.js
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

_log.info("platform started", extra={"path": f"modules={_mounted}"})
print(f"[platform] mounted modules: {_mounted}")
