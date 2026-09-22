"""전결규정 RAG 라우트 — 질문→규정(결재선 등) 검색. A rag.py search 이식(표면만 C).

- POST /approval/search      : API키 인증(프로그램·Z SDK). tenant=키 고객사.
- POST /approval/test        : 세션 인증(콘솔, approval:test). tenant=__test__.
- GET  /approval/test/collections : 테스트 화면 컬렉션 드롭다운.
엔진(임베딩·검색)은 search.run_search(= A search_rules 이식). 여기선 인증·원장·envelope만.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends

from core.auth import Principal
from core.permissions import require_capability, require_permission
from core.user_auth import User
from core.envelope import success
from core.errors import ApiError
from core import ledger
from core.ledger import TEST_TENANT
import modules.approval.config as cfg
from modules.approval import search
from modules.recommend import engine        # 컬렉션 목록(공용 client)

router = APIRouter(prefix="/approval", tags=["approval"])


def _record(tenant: str, body: Dict[str, Any], result: Dict[str, Any]) -> None:
    ledger.append(tenant, "approval", result.get("TOTAL", 0), "request", "engine",
                  cfg.RAG_EMBED_MODEL, ok=True,
                  meta={"q": str(body.get("QUERY_TEXT") or "")[:100], "total": result.get("TOTAL", 0)})


@router.post("/search")
def approval_search(body: Dict[str, Any], principal: Principal = Depends(require_capability("approval"))):
    result = search.run_search(body)
    _record(principal.tenant, body, result)
    return success(result)


@router.get("/test/collections")
def approval_collections(user: User = Depends(require_permission("approval:test"))):
    """테스트 화면 드롭다운 — Qdrant 컬렉션 목록."""
    try:
        cols = [c.name for c in engine.client.get_collections().collections]
    except Exception as e:
        raise ApiError("APPROVAL_UNAVAILABLE", f"Qdrant 조회 실패: {e}", status=503)
    return success({"collections": sorted(cols), "default": cfg.RAG_COLLECTION})


@router.post("/test")
def approval_test(body: Dict[str, Any], user: User = Depends(require_permission("approval:test"))):
    """콘솔 전결규정 테스트 — 세션 인증. 엔진 동일(run_search). tenant=__test__."""
    result = search.run_search(body)
    _record(TEST_TENANT, body, result)
    return success(result)
