"""OCR 오케스트레이션 (Service 계층).

router(Controller)는 HTTP만 안다 — 파싱·검증·envelope. 여기는 HTTP를 전혀 모른다.
파일 여러 개를 받아 → 페이지로 펼치고 → 페이지마다 추출(재시도 포함) → 파일별로 다시 묶고
→ 원장에 기록. 스프링의 @Service 자리와 같은 개념(어노테이션 없이 그냥 모듈).

부분 성공(partial success): 페이지 하나가 실패해도 나머지는 살린다. 실패는 그 페이지만
ok:false + error로 결과에 담고, HTTP는 200. 재시도는 여기서 처리(C안: 재시도 후 부분성공).

병렬(Step 2): 페이지들을 스레드풀로 동시 발사한다. 모델 호출은 CPU가 아니라 네트워크
대기(I/O)라, 워커를 CPU 코어 수에 묶을 이유가 없다(B univision parallel.py의 통찰).
DB는 병렬 구간에서 안 건드림 — 추출(_run_page)은 모델 호출만, 원장 기록(_record)은
병렬 종료 후 메인 스레드에서 순차. 그래서 sqlite 동시성 이슈 없음.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from modules.ocr import extract, pdf
from core import ledger
from core.logging_setup import get_logger

log = get_logger("ocr")

_RETRY = 2                    # 페이지 추출 실패 시 추가 재시도 횟수(초기 시도 제외 → 최대 1+2회)
_MAX_WORKERS = 5              # 동시 모델 호출 상한 — provider rate limit 보호(페이지 많아도 5개씩)
_TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


@dataclass
class UploadItem:
    """업로드 원본 1건. 라우터가 HTTP(UploadFile)에서 뽑아 넘겨줌 — 서비스는 HTTP를 모름."""
    filename: str
    data: bytes
    mime: str


@dataclass
class _Page:
    """처리 단위 1개 = '한 파일의 한 페이지'. 이미지=1개, PDF=N개로 펼쳐진다."""
    file_index: int
    filename: str
    page_index: int
    image: bytes | None = None
    mime: str = "image/png"
    load_error: str | None = None      # 모델 호출 전에 이미 실패(PDF 렌더 실패 등)


# ── 1) 업로드 → 페이지 펼치기 ────────────────────────────────────────────────
def _expand(uploads: list[UploadItem]) -> list[_Page]:
    """각 업로드를 페이지 단위로 평면화. PDF 렌더 실패는 파일을 죽이지 않고 실패 페이지로."""
    pages: list[_Page] = []
    for fi, up in enumerate(uploads):
        if pdf.is_pdf(up.data, up.mime):
            try:
                images = pdf.render_pages(up.data)
            except Exception as e:                       # 깨진 PDF → 그 파일만 실패
                pages.append(_Page(fi, up.filename, 0, load_error=f"PDF_INVALID: {e}"))
                continue
            if not images:
                pages.append(_Page(fi, up.filename, 0, load_error="PDF_EMPTY"))
                continue
            for pi, img in enumerate(images):
                pages.append(_Page(fi, up.filename, pi, image=img, mime="image/png"))
        else:
            pages.append(_Page(fi, up.filename, 0, image=up.data, mime=up.mime))
    return pages


# ── 2) 페이지 1개 처리 (재시도 포함) ──────────────────────────────────────────
def _run_page(p: _Page, alias: str, doc_type: str) -> dict:
    """페이지 하나를 추출. 예외는 값(ok:false)으로 잡는다 — Step 2 병렬에서 하나가
    터져도 전체가 안 죽게(Promise.allSettled 개념). 실패 시 _RETRY회 재시도."""
    loc = {"file_index": p.file_index, "filename": p.filename, "page_index": p.page_index}
    if p.load_error:                                     # 이미 실패(렌더 등) → 모델 호출 생략
        return {**loc, "ok": False, "error": p.load_error, "out": None}

    last = None
    for attempt in range(_RETRY + 1):
        try:
            payload, out = extract.extract_one(p.image, p.mime, alias, doc_type)
            return {**loc, "ok": True, "doc_type": payload["doc_type"],
                    "result": payload["result"], "ms": out.get("ms"), "out": out}
        except Exception as e:
            last = e
            log.warning("ocr page failed",
                        extra={"file": p.filename, "page": p.page_index,
                               "attempt": attempt + 1, "err": str(e)})
    return {**loc, "ok": False, "error": str(last), "out": None}


# ── 2b) 페이지들 동시 발사 (병렬) ─────────────────────────────────────────────
def _run_pages(pages: list[_Page], alias: str, doc_type: str) -> list[dict]:
    """페이지들을 스레드풀로 동시 처리. 순서는 pool.map이 입력 순서대로 보존.

    _run_page는 예외를 값(ok:false)으로 반환하므로 스레드에서 터져도 전체가 안 죽는다
    (Promise.allSettled 개념). 1장이면 풀 오버헤드 없이 그냥 처리.
    """
    if len(pages) <= 1:
        return [_run_page(p, alias, doc_type) for p in pages]
    workers = min(_MAX_WORKERS, len(pages))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ocr") as pool:
        return list(pool.map(lambda p: _run_page(p, alias, doc_type), pages))


# ── 3) 페이지 결과 → 파일별로 다시 묶기 ───────────────────────────────────────
def _group_by_file(uploads: list[UploadItem], results: list[dict]) -> list[dict]:
    """평면 페이지 결과를 원래 파일 단위로 복원(page_index 순 정렬). 응답용 모양."""
    files = []
    for fi, up in enumerate(uploads):
        mine = sorted((r for r in results if r["file_index"] == fi),
                      key=lambda r: r["page_index"])
        pages = [{"page_index": r["page_index"], "doc_type": r.get("doc_type"),
                  "result": r.get("result"), "ms": r.get("ms"),
                  "ok": r["ok"], **({"error": r["error"]} if not r["ok"] else {})}
                 for r in mine]
        file_ok = bool(pages) and all(r["ok"] for r in mine)
        files.append({"file_index": fi, "filename": up.filename, "ok": file_ok,
                      "page_count": len(pages), "pages": pages})
    return files


# ── 4) 원장 기록 (성공 페이지만 청구 수량) ────────────────────────────────────
def _record(tenant: str, alias: str, doc_type: str, uploads: list[UploadItem], results: list[dict]) -> None:
    """파일 단위로 원장 1행. quantity=성공 페이지 수(실패는 청구 안 함), ok=파일 전체 성공 여부."""
    for fi, up in enumerate(uploads):
        mine = [r for r in results if r["file_index"] == fi]
        ok_pages = sum(1 for r in mine if r["ok"])
        provider, model = alias, alias
        totals = {k: 0 for k in _TOKEN_KEYS}
        for r in mine:
            out = r.get("out") or {}
            provider = out.get("provider", provider)
            model = out.get("model", model)
            for k in _TOKEN_KEYS:
                totals[k] += (out.get("usage", {}) or {}).get(k, 0) or 0
        ledger.append(tenant, "ocr", ok_pages, "page", provider, model,
                      ok=bool(mine) and all(r["ok"] for r in mine),
                      meta={"filename": up.filename, "doc_type": doc_type,
                            "pages": len(mine), "ok_pages": ok_pages, "tokens": totals})


def _aggregate_usage(results: list[dict], wall_ms: int) -> dict:
    """응답 meta.usage — 토큰·시간 합산 + 성공/실패 카운트 + 실패 사유별 집계.

    wall_ms = 실제 경과(병렬 이득이 보이는 값). work_ms = 페이지 모델시간 합(총 연산량,
    병렬해도 안 줄어듦). 예: 3장 각 20초 → work_ms≈60000, wall_ms≈20000.
    """
    totals = {k: 0 for k in _TOKEN_KEYS}
    work_ms = 0
    provider = model = None
    ok_count = 0
    errors: dict[str, int] = {}
    for r in results:
        if r["ok"]:
            ok_count += 1
            work_ms += r.get("ms") or 0
        else:
            errors[r["error"]] = errors.get(r["error"], 0) + 1   # 실패 사유별 건수(관측)
        out = r.get("out") or {}
        provider = out.get("provider", provider)
        model = out.get("model", model)
        for k in _TOKEN_KEYS:
            totals[k] += (out.get("usage", {}) or {}).get(k, 0) or 0
    return {"pages": len(results), "ok_count": ok_count, "fail_count": len(results) - ok_count,
            "provider": provider, "model": model, "tokens": totals,
            "wall_ms": wall_ms, "work_ms": work_ms, "errors": errors}


# ── 진입점 ────────────────────────────────────────────────────────────────────
def process(uploads: list[UploadItem], alias: str, doc_type: str, tenant: str) -> tuple[dict, dict]:
    """(payload, usage) 반환 — 라우터가 success(payload, usage=usage)로 감싸기만 하면 됨."""
    pages = _expand(uploads)                                   # 1) 펼치기
    t0 = time.perf_counter()
    results = _run_pages(pages, alias, doc_type)               # 2) 처리 (병렬)
    wall_ms = round((time.perf_counter() - t0) * 1000)         #    실제 경과(병렬 이득)
    files = _group_by_file(uploads, results)                  # 3) 파일별로 묶기
    _record(tenant, alias, doc_type, uploads, results)        # 4) 원장
    payload = {"file_count": len(uploads), "doc_type": doc_type, "files": files}
    return payload, _aggregate_usage(results, wall_ms)
