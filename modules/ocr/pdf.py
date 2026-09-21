"""PDF 입력 전처리 — PyMuPDF로 페이지를 이미지(PNG)로 렌더.

PDF는 '새 문서종류'가 아니라 '입력 컨테이너'(문서종류와 직교). 각 페이지를 이미지로 펼쳐
페이지마다 기존 추출(extract.format_image)을 그대로 재사용한다 — 라우트 본체 불변.
"""
import fitz  # PyMuPDF

from core.config import load_config

_PDF_MAGIC = b"%PDF-"
_MAX_PAGES = 20          # 방어: 초대형 PDF 상한
_ZOOM_DEFAULT = 2.0      # ~144dpi — OCR용 해상도 보강 (config.ocr.pdf_zoom로 덮어쓰기)


def _zoom() -> float:
    """PDF 렌더 배율 — config에서 매번 읽음(hot-reload). 배율↓ = 이미지 작아짐 = 토큰·비용↓."""
    return float(load_config().get("ocr", {}).get("pdf_zoom", _ZOOM_DEFAULT))


def is_pdf(data: bytes, mime: str | None) -> bool:
    if mime and "pdf" in mime.lower():
        return True
    return data[:5] == _PDF_MAGIC


def render_pages(data: bytes) -> list[bytes]:
    """PDF 각 페이지를 PNG 바이트 리스트로. (최대 _MAX_PAGES)"""
    pages: list[bytes] = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        z = _zoom()
        mat = fitz.Matrix(z, z)
        for page in doc:
            if len(pages) >= _MAX_PAGES:
                break
            pix = page.get_pixmap(matrix=mat)
            pages.append(pix.tobytes("png"))
    finally:
        doc.close()
    return pages
