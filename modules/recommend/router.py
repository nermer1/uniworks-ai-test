"""POST /recommend — 증빙 → 계정과목 추천. OCR과 같은 코어(인증·권한·원장)를 재사용.

핵심: 이 모듈은 코어를 1도 안 고치고 꽂힌다. 인증·tenant·원장이 공짜로 딸려온다.
OCR과 달리 model_gateway를 안 쓴다(추천=벡터검색). provider는 인프로세스 'engine'.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import Principal
from core.permissions import require_capability
from core.envelope import success
from core import ledger
from modules.recommend import engine

router = APIRouter(prefix="/recommend", tags=["recommend"])


class RecommendRequest(BaseModel):
    merchant_name: str
    mcc_name: str | None = None
    amount: int | None = None


@router.post("")
def recommend(
    req: RecommendRequest,
    principal: Principal = Depends(require_capability("recommend")),
):
    results = engine.recommend(req.merchant_name, req.mcc_name, req.amount)
    # 추천은 인프로세스 엔진 → provider='engine'(상용 아님, 과금 대상 아님). unit='request'.
    ledger.append(
        principal.tenant, "recommend", 1, "request", "engine", "mock-v1",
        ok=True, meta={"query": req.merchant_name},
    )
    return success(
        {"recommendations": results},
        usage={"requests": 1, "provider": "engine", "model": "mock-v1"},
    )
