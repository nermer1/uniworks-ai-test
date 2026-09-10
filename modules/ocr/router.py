"""POST /ocr — 인증→권한→(문서종류별/자동분류)추출→원장 기록. 응답은 코어 envelope.

doc_type: card/jiro/tax 명시 또는 'auto'(분류 LLM이 종류 판정 후 추출).
PDF는 페이지마다 extract_one → auto면 페이지별로 종류가 달라도 됨(뒤섞인 증빙 PDF 대응).
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
    doc_type: str = Form(default="card"),
    principal: Principal = Depends(require_capability("ocr")),
):
    alias = model or default_model()
    check_model(principal, alias)
    if doc_type != "auto" and doc_type not in extract.valid_doc_types():
        raise ApiError("INVALID_DOC_TYPE",
                       f"문서종류는 {extract.valid_doc_types() + ['auto']} 중 하나여야 합니다", status=400)

    data = file.file.read()
    mime = file.content_type or "image/jpeg"

    if pdf.is_pdf(data, mime):
        return _process_pdf(data, alias, doc_type, principal)
    return _process_image(data, mime, alias, doc_type, principal)


def _process_image(data: bytes, mime: str, alias: str, doc_type: str, principal: Principal):
    try:
        payload, out = extract.extract_one(data, mime, alias, doc_type)
    except Exception as e:
        ledger.append(principal.tenant, "ocr", 1, "page", "-", alias, ok=False, meta={"error": str(e)})
        raise ApiError("OCR_FAILED", f"OCR 처리 실패: {e}", status=502)

    usage = {"pages": 1, "provider": out.get("provider"), "model": out.get("model"),
             "tokens": out.get("usage", {}), "ms": out.get("ms")}
    if out.get("classify_ms") is not None:                 # auto면 분류/추출 분해
        usage["classify_ms"] = out["classify_ms"]
        usage["extract_ms"] = out["extract_ms"]
    ledger.append(
        principal.tenant, "ocr", 1, "page",
        out.get("provider", "-"), out.get("model", alias),
        ok=True, meta={"tokens": out.get("usage", {}), "doc_type": payload["doc_type"], "ms": out.get("ms")},
    )
    return success(payload, usage=usage)


def _process_pdf(data: bytes, alias: str, doc_type: str, principal: Principal):
    try:
        page_images = pdf.render_pages(data)
    except Exception as e:
        raise ApiError("PDF_INVALID", f"PDF 처리 실패: {e}", status=400)
    if not page_images:
        raise ApiError("PDF_EMPTY", "빈 PDF입니다", status=400)

    pages = []
    totals = {k: 0 for k in _TOKEN_KEYS}
    total_ms = 0
    provider = alias
    model_name = alias
    for i, png in enumerate(page_images):
        try:
            payload, out = extract.extract_one(png, "image/png", alias, doc_type)
            provider = out.get("provider", provider)
            model_name = out.get("model", alias)
            usage = out.get("usage", {})
            for k in _TOKEN_KEYS:
                totals[k] += usage.get(k, 0) or 0
            total_ms += out.get("ms", 0) or 0
            pages.append({"page_index": i, "doc_type": payload["doc_type"],
                          "result": payload["result"], "ms": out.get("ms"), "ok": True})
        except Exception as e:
            pages.append({"page_index": i, "doc_type": None, "result": None, "ok": False, "error": str(e)})

    n = len(page_images)
    ledger.append(
        principal.tenant, "ocr", n, "page", provider, model_name,
        ok=True, meta={"tokens": totals, "pages": n, "doc_type": doc_type, "ms": total_ms},
    )
    return success(
        {"is_pdf": True, "doc_type": doc_type, "page_count": n, "pages": pages},
        usage={"pages": n, "provider": provider, "model": model_name, "tokens": totals, "ms": total_ms},
    )
