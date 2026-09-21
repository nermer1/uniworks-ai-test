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
# OpenAPI 3.0 고정 — 3.0에선 file 바이너리 정식 표기가 format:"binary". (Z 자바 클라
# 생성 툴 호환에도 3.0이 무난)
app.openapi_version = "3.0.3"


# ── Swagger UI 파일 업로드 렌더 보정 ──
# FastAPI(0.141)는 list[UploadFile] 바이너리를 3.1식 contentMediaType으로 표기하는데,
# Swagger UI는 그걸 파일버튼이 아니라 텍스트칸(array<string>)으로 그린다. Swagger가
# 인식하는 format:"binary"를 스키마에 덧발라 파일 선택 버튼이 뜨게 한다(모든 업로드 공통).
def _mark_binary(node) -> None:
    if isinstance(node, dict):
        if node.get("type") == "string" and node.get("contentMediaType") == "application/octet-stream":
            node["format"] = "binary"
        for v in node.values():
            _mark_binary(v)
    elif isinstance(node, list):
        for v in node:
            _mark_binary(v)


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(title=app.title, version=app.version,
                         openapi_version=app.openapi_version, routes=app.routes)
    _mark_binary(schema)
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi

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
    """고객사별 사용량 롤업 — 회계 화면(회계/관리자 role)이 소비. 실/테스트 필터는 화면에서."""
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
