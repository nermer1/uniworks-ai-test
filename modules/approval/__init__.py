"""approval(전결규정 RAG) 모듈 진입점 — 코어 mount_modules가 호출하는 register(app) 노출."""
from modules.approval.router import router


def register(app):
    app.include_router(router)
