"""OCR 모듈 진입점 — 코어가 mount_modules에서 호출하는 register(app)를 노출."""
from modules.ocr.router import router


def register(app):
    app.include_router(router)
