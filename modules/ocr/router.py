"""POST /ocr — 인증→권한→추출→원장 기록. 응답은 코어 envelope(success/ApiError)로 통일.

모듈은 인증/모델선택/과금을 '모른다'. 코어가 준 Principal만 받고,
프롬프트·모델 호출은 코어를 통하며, 처리 수량(페이지 수)만 원장에 보고한다.
"""
from fastapi import APIRouter, UploadFile, File, Form, Depends

from core.auth import Principal
from core.permissions import require_capability, check_model
from core.config import default_model
from core.envelope import success
from core.errors import ApiError
from core import ledger
from modules.ocr import extract, pdf

router = APIRouter(prefix="/ocr", tags=["ocr"])

_TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


@router.post("")
def ocr(
    file: UploadFile = File(...),
    model: str = Form(default=""),
    principal: Principal = Depends(require_capability("ocr")),
):
    alias = model or default_model()
    check_model(principal, alias)   # 이 키가 이 모델 쓸 수 있나

    data = file.file.read()
    mime = file.content_type or "image/jpeg"

    if pdf.is_pdf(data, mime):
        return _process_pdf(data, alias, principal)
    return _process_image(data, mime, alias, principal)


def _process_image(data: bytes, mime: str, alias: str, principal: Principal):
    try:
        result, out = extract.format_image(data, mime, alias)
    except Exception as e:
        ledger.append(principal.tenant, "ocr", 1, "page", "-", alias, ok=False, meta={"error": str(e)})
        raise ApiError("OCR_FAILED", f"OCR 처리 실패: {e}", status=502)

    ledger.append(
        principal.tenant, "ocr", 1, "page",
        out.get("provider", "-"), out.get("model", alias),
        ok=True, meta={"tokens": out.get("usage", {})},
    )
    return success(
        {"result": result},
        usage={"pages": 1, "provider": out.get("provider"),
               "model": out.get("model"), "tokens": out.get("usage", {})},
    )


def _process_pdf(data: bytes, alias: str, principal: Principal):
    try:
        page_images = pdf.render_pages(data)
    except Exception as e:
        raise ApiError("PDF_INVALID", f"PDF 처리 실패: {e}", status=400)
    if not page_images:
        raise ApiError("PDF_EMPTY", "빈 PDF입니다", status=400)

    pages = []
    totals = {k: 0 for k in _TOKEN_KEYS}
    provider = alias
    model_name = alias
    for i, png in enumerate(page_images):
        try:
            result, out = extract.format_image(png, "image/png", alias)
            provider = out.get("provider", provider)
            model_name = out.get("model", alias)
            usage = out.get("usage", {})
            for k in _TOKEN_KEYS:
                totals[k] += usage.get(k, 0) or 0
            pages.append({"page_index": i, "result": result, "ok": True})
        except Exception as e:
            pages.append({"page_index": i, "result": None, "ok": False, "error": str(e)})

    n = len(page_images)
    # 페이지 수만큼 quantity 기록 (= 페이지당 과금 근거).
    ledger.append(
        principal.tenant, "ocr", n, "page", provider, model_name,
        ok=True, meta={"tokens": totals, "pages": n},
    )
    return success(
        {"is_pdf": True, "page_count": n, "pages": pages},
        usage={"pages": n, "provider": provider, "model": model_name, "tokens": totals},
    )
