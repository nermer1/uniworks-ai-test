"""추천 라우트 — 증빙→계정과목(HKONT) 추천. A(unirec) search.py 검색 흐름 이식.

두 진입점(엔진 동일, 표면만 다름):
- POST /recommend       : API키 인증(프로그램·Z SDK). tenant=키 고객사. 과금 대상.
- POST /recommend/test  : 세션 인증(콘솔 사람, recommend:test). tenant=__test__(실집계 분리).
엔진(modules.recommend.engine = A core.py 고스란히)의 함수를 그대로 호출한다.
"""
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from qdrant_client import models as qmodels

from core.auth import Principal
from core.permissions import require_capability, require_permission
from core.user_auth import User
from core.envelope import success
from core.errors import ApiError
from core import ledger
from core.ledger import TEST_TENANT
import modules.recommend.config as cfg
from modules.recommend import engine
from modules.recommend.fit_messages import fit_msg

router = APIRouter(prefix="/recommend", tags=["recommend"])


class RecommendRequest(BaseModel):
    form_type: str = "CD"                       # CD(법인카드) / ET(세금계산서·지로)
    queries: list[dict[str, Any]]               # QUERY_COLUMNS 필드 맵 배열 (MERCH_NAME 등)
    collection: str | None = None               # 지정 시 alias 해소 건너뛰고 직접 검색


def _run(form_type: str, queries: list[dict], collection: str | None):
    """검색+스코어링 실행 → (results, ok_count, ms). /recommend·/recommend/test 공용."""
    if not queries:
        raise ApiError("INVALID_INPUT", "queries가 비어 있습니다", status=400)
    base_form_type = form_type.split("_")[0].upper() if "_" in form_type else form_type.upper()
    try:
        col = (engine._resolve_target_collection(collection) if collection
               else engine._resolve_target_collection(engine.get_collection_name(form_type)))
        model = engine.get_model_for_collection(col)
    except Exception as e:
        raise ApiError("RECOMMEND_UNAVAILABLE", f"컬렉션/모델 준비 실패: {e}", status=503)

    t0 = time.perf_counter()
    items = [{**(q or {}), "FORM_TYPE": form_type} for q in queries]
    texts = [engine.build_comprehensive_text(d, is_query=True) for d in items]
    vectors = model.encode(texts, show_progress_bar=False)

    results, ok = [], 0
    for d, text, vec in zip(items, texts, vectors):
        try:
            points = engine.client.query_points(
                collection_name=col, query=vec.tolist(), limit=cfg.SEARCH_LIMIT,
                with_payload=True,
                search_params=qmodels.SearchParams(hnsw_ef=cfg.HNSW_EF, exact=False),
            ).points
            recs = engine.get_hybrid_recommendation(points, d, base_form_type)
        except Exception as e:                  # 건별 격리 — A와 동일 철학
            cfg.logger.error(f"recommend 스코어링 실패: {e}", exc_info=True)
            recs = None

        if recs:
            top = recs[0]
            results.append({"query_text": text, "ok": True,
                            "HKONT": top["HKONT"], "HKONT_TXT": top["HKONT_TXT"], "SCORE": top["SCORE"],
                            "FIT_FLAG": top["FIT_FLAG"], "FIT_REASON": top["FIT_REASON"],
                            "CONFIDENCE": top.get("CONFIDENCE"), "ALL_RECOMMENDATIONS": recs[:5]})
            ok += 1
        else:
            results.append({"query_text": text, "ok": False, "HKONT": None, "HKONT_TXT": "",
                            "SCORE": 0.0, "FIT_FLAG": engine.FIT_NG,
                            "FIT_REASON": fit_msg("msg.no_result"), "ALL_RECOMMENDATIONS": []})
    return results, ok, round((time.perf_counter() - t0) * 1000)


def _envelope(form_type: str, results: list, ok: int, ms: int):
    return success(
        {"form_type": form_type, "count": len(results), "results": results},
        usage={"requests": len(results), "ok_count": ok,
               "provider": "engine", "model": cfg.MODEL_NAME, "ms": ms},
    )


@router.post("")
def recommend(req: RecommendRequest, principal: Principal = Depends(require_capability("recommend"))):
    results, ok, ms = _run(req.form_type, req.queries, req.collection)
    ledger.append(principal.tenant, "recommend", len(req.queries), "request", "engine",
                  cfg.MODEL_NAME, ok=True, meta={"form_type": req.form_type, "ok": ok, "ms": ms})
    return _envelope(req.form_type, results, ok, ms)


@router.get("/test/collections")
def recommend_collections(user: User = Depends(require_permission("recommend:test"))):
    """추천 테스트 화면 드롭다운용 — Qdrant 컬렉션 목록."""
    try:
        cols = [c.name for c in engine.client.get_collections().collections]
    except Exception as e:
        raise ApiError("RECOMMEND_UNAVAILABLE", f"Qdrant 조회 실패: {e}", status=503)
    return success({"collections": sorted(cols)})


@router.post("/test")
def recommend_test(req: RecommendRequest, user: User = Depends(require_permission("recommend:test"))):
    """콘솔 추천 테스트 — 세션 인증. 엔진 동일(_run 재사용). tenant=__test__로 실집계 분리."""
    results, ok, ms = _run(req.form_type, req.queries, req.collection)
    ledger.append(TEST_TENANT, "recommend", len(req.queries), "request", "engine",
                  cfg.MODEL_NAME, ok=True, meta={"form_type": req.form_type, "ok": ok, "ms": ms})
    return _envelope(req.form_type, results, ok, ms)
