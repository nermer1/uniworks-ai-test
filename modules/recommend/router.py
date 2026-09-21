"""POST /recommend — 증빙 → 계정과목(HKONT) 추천. A(unirec) search.py 검색 흐름 이식.

엔진(modules.recommend.engine = A core.py 고스란히)의 함수를 그대로 호출한다.
여기(라우터)는 C 표면만: capability 인증 · 원장 · envelope. 입력/출력 필드는 A 기준
(form_type, queries[], HKONT/HKONT_TXT/SCORE/FIT_FLAG/FIT_REASON/ALL_RECOMMENDATIONS).
"""
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from qdrant_client import models as qmodels

from core.auth import Principal
from core.permissions import require_capability
from core.envelope import success
from core.errors import ApiError
from core import ledger
import modules.recommend.config as cfg
from modules.recommend import engine
from modules.recommend.fit_messages import fit_msg

router = APIRouter(prefix="/recommend", tags=["recommend"])


class RecommendRequest(BaseModel):
    form_type: str = "CD"                       # CD(법인카드) / ET(세금계산서·지로)
    queries: list[dict[str, Any]]               # QUERY_COLUMNS 필드 맵 배열 (MERCH_NAME 등)
    collection: str | None = None               # 지정 시 alias 해소 건너뛰고 직접 검색(테스트용)


def _resolve(form_type: str, collection: str | None) -> str:
    """A와 동일: collection 지정이면 그대로, 아니면 form_type→alias→물리컬렉션."""
    if collection:
        return engine._resolve_target_collection(collection)
    return engine._resolve_target_collection(engine.get_collection_name(form_type))


@router.post("")
def recommend(req: RecommendRequest, principal: Principal = Depends(require_capability("recommend"))):
    if not req.queries:
        raise ApiError("INVALID_INPUT", "queries가 비어 있습니다", status=400)

    form_type = req.form_type
    base_form_type = form_type.split("_")[0].upper() if "_" in form_type else form_type.upper()
    try:
        collection = _resolve(form_type, req.collection)
        model = engine.get_model_for_collection(collection)
    except Exception as e:
        raise ApiError("RECOMMEND_UNAVAILABLE", f"컬렉션/모델 준비 실패: {e}", status=503)

    t0 = time.perf_counter()
    # 쿼리 텍스트 생성(A build_comprehensive_text) + 일괄 인코딩
    items = [{**(q or {}), "FORM_TYPE": form_type} for q in req.queries]
    texts = [engine.build_comprehensive_text(d, is_query=True) for d in items]
    vectors = model.encode(texts, show_progress_bar=False)

    results, ok = [], 0
    for d, text, vec in zip(items, texts, vectors):
        try:
            points = engine.client.query_points(
                collection_name=collection, query=vec.tolist(), limit=cfg.SEARCH_LIMIT,
                with_payload=True,
                search_params=qmodels.SearchParams(hnsw_ef=cfg.HNSW_EF, exact=False),
            ).points
            recs = engine.get_hybrid_recommendation(points, d, base_form_type)
        except Exception as e:                  # 건별 격리(배치 전체 안 죽게) — A와 동일 철학
            cfg.logger.error(f"recommend 스코어링 실패: {e}", exc_info=True)
            recs = None

        if recs:
            top = recs[0]
            results.append({
                "query_text": text, "ok": True,
                "HKONT": top["HKONT"], "HKONT_TXT": top["HKONT_TXT"], "SCORE": top["SCORE"],
                "FIT_FLAG": top["FIT_FLAG"], "FIT_REASON": top["FIT_REASON"],
                "CONFIDENCE": top.get("CONFIDENCE"),
                "ALL_RECOMMENDATIONS": recs[:5],
            })
            ok += 1
        else:
            results.append({
                "query_text": text, "ok": False,
                "HKONT": None, "HKONT_TXT": "", "SCORE": 0.0,
                "FIT_FLAG": engine.FIT_NG, "FIT_REASON": fit_msg("msg.no_result"),
                "ALL_RECOMMENDATIONS": [],
            })

    ms = round((time.perf_counter() - t0) * 1000)
    ledger.append(principal.tenant, "recommend", len(req.queries), "request",
                  "engine", cfg.MODEL_NAME, ok=True,
                  meta={"form_type": form_type, "ok": ok, "ms": ms})
    return success(
        {"form_type": form_type, "count": len(results), "results": results},
        usage={"requests": len(req.queries), "ok_count": ok,
               "provider": "engine", "model": cfg.MODEL_NAME, "ms": ms},
    )
