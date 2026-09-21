"""POST /ocr — 인증→권한→검증→service 위임→envelope. (Controller: HTTP만 담당)

파일 여러 개 업로드 지원. 각 파일은 이미지 또는 PDF(다중 페이지). doc_type은
card/jiro/tax 명시 또는 'auto'(페이지별 분류 후 추출) — 뒤섞인 증빙도 페이지 단위로 처리.
오케스트레이션(멀티파일·재시도·부분성공·원장)은 modules/ocr/service.py 참고.

두 진입점:
- POST /ocr       : API키 인증(프로그램·자바클라 Z). tenant=키의 고객사. 과금 대상.
- POST /ocr/test  : 세션 인증(콘솔 사람, ocr:test 권한). tenant=__test__로 실데이터와 분리.
  엔진(service.process)은 완전히 동일 — 인증/표면만 다르다.
"""
from fastapi import APIRouter, UploadFile, File, Form, Depends
from pydantic import BaseModel

from core.auth import Principal
from core.permissions import require_capability, check_model, require_permission
from core.user_auth import User
from core.config import default_model, available_models
from core.envelope import success
from core.errors import ApiError
from core import test_runs
from modules.ocr import extract, service

router = APIRouter(prefix="/ocr", tags=["ocr"])

TEST_TENANT = "__test__"      # 콘솔 테스트 사용량 — 실데이터 롤업과 분리(나중에 제외)


def _validate(alias: str, doc_type: str) -> None:
    """두 진입점 공통 입력 검증 — 모델 별칭·문서종류."""
    if alias not in available_models():
        raise ApiError("INVALID_MODEL",
                       f"모델 별칭은 {available_models()} 중 하나여야 합니다", status=400)
    if doc_type != "auto" and doc_type not in extract.valid_doc_types():
        raise ApiError("INVALID_DOC_TYPE",
                       f"문서종류는 {extract.valid_doc_types() + ['auto']} 중 하나여야 합니다", status=400)


def _read_uploads(files: list[UploadFile]) -> list[service.UploadItem]:
    """HTTP(UploadFile) → 서비스가 아는 순수 자료(UploadItem)."""
    return [service.UploadItem(f.filename or "unnamed", f.file.read(),
                               f.content_type or "image/jpeg") for f in files]


@router.post("")
def ocr(
    files: list[UploadFile] = File(...),
    model: str = Form(default=""),
    doc_type: str = Form(default="card"),
    principal: Principal = Depends(require_capability("ocr")),
):
    alias = model or default_model()
    _validate(alias, doc_type)
    check_model(principal, alias)                          # 이 키가 이 모델 쓸 권한 있나
    payload, usage = service.process(_read_uploads(files), alias, doc_type, principal.tenant)
    return success(payload, usage=usage)


@router.get("/test/models")
def ocr_test_models(user: User = Depends(require_permission("ocr:test"))):
    """테스트 화면의 모델 드롭다운용 — config에 정의된 별칭 목록 + 기본값."""
    return success({"models": available_models(), "default": default_model()})


@router.get("/test/groups")
def ocr_test_groups(user: User = Depends(require_permission("ocr:test"))):
    """그룹명 목록 (테스트 화면 자동완성·비교뷰용)."""
    return success({"groups": test_runs.groups()})


@router.get("/test/history")
def ocr_test_history(user: User = Depends(require_permission("ocr:test"))):
    """테스트 실행 이력 목록 (요약)."""
    return success({"runs": test_runs.recent()})


class DeleteRunsReq(BaseModel):
    ids: list[int]


@router.post("/test/history/delete")
def ocr_test_history_delete(req: DeleteRunsReq, user: User = Depends(require_permission("ocr:test"))):
    """이력 삭제(개별=1개 리스트, 선택 삭제=여러 개)."""
    return success({"deleted": test_runs.delete(req.ids)})


@router.get("/test/history/{run_id}")
def ocr_test_history_detail(run_id: int, user: User = Depends(require_permission("ocr:test"))):
    """이력 단건 상세 (결과 JSON 포함)."""
    run = test_runs.get(run_id)
    if run is None:
        raise ApiError("NOT_FOUND", "해당 이력이 없습니다", status=404)
    return success(run)


@router.post("/test")
def ocr_test(
    files: list[UploadFile] = File(...),
    model: str = Form(default=""),
    doc_type: str = Form(default="auto"),
    group: str = Form(default=""),
    user: User = Depends(require_permission("ocr:test")),
):
    """콘솔 OCR 테스트 — 사람(세션) 전용. 엔진은 /ocr와 동일(service.process 재사용).
    tenant=__test__로 기록해 실데이터 사용량과 섞이지 않고, 결과는 test_runs에 보관.
    group: 비교용 그룹 태그(선택)."""
    alias = model or default_model()
    _validate(alias, doc_type)
    payload, usage = service.process(_read_uploads(files), alias, doc_type, TEST_TENANT)
    tok = usage.get("tokens") or {}
    test_runs.record(
        username=user.username, kind="ocr", group_name=group.strip(),
        provider=usage.get("provider"), model=usage.get("model"), doc_type=doc_type,
        file_count=payload.get("file_count"), page_count=usage.get("pages"),
        ok_count=usage.get("ok_count"), fail_count=usage.get("fail_count"),
        wall_ms=usage.get("wall_ms"), work_ms=usage.get("work_ms"),
        total_tokens=tok.get("total_tokens"), result=payload,
    )
    return success(payload, usage=usage)
