"""전결규정 RAG 검색 — A(unirec) rag.py의 search_rules + 필터 헬퍼 고스란히 이식.

client·임베딩 모델은 recommend.engine(공용 vector 인프라) 재사용. 로직·필터·후처리는 A와 동일.
A의 모니터링(set_monitor_extra/write_detail_log)은 C 표면(ledger/access_log)으로 대체 → 라우터에서.
HTTPException → C ApiError.
"""
import time
from typing import Any, Dict, List, Optional

from qdrant_client import models

from core.errors import ApiError
from modules.recommend import engine          # 공용 client + get_model_for_collection 재사용
import modules.approval.config as cfg


# ── 필터 헬퍼 (A rag.py 이식) ──
def _requester_matches(requester_group: str, rule_group: Any) -> bool:
    """기안자 그룹 매칭 — 규칙 값이 비면 공통규칙(통과). 정규화 후 양방향 부분일치."""
    rg = str(rule_group or "").replace(" ", "")
    if not rg:
        return True
    for t in [t for t in requester_group.split() if t]:
        if t in rg or rg in t:                 # "팀장" in "팀장이하" = True
            return True
    return False


def _kv_conditions(meta: Dict[str, Any]) -> List[models.FieldCondition]:
    out: List[models.FieldCondition] = []
    for key, value in (meta or {}).items():
        if value is None:
            continue
        s = str(value).strip()
        if s:
            out.append(models.FieldCondition(key=key, match=models.MatchValue(value=s)))
    return out


def _build_search_filter(bukrs: str, meta: Dict[str, Any],
                         include_superseded: bool = False) -> Optional[models.Filter]:
    must: List[Any] = list(_kv_conditions(meta))
    if not include_superseded:                 # 폐지본 제외
        must.append(models.FieldCondition(key="status", match=models.MatchValue(value="active")))
    if bukrs:                                   # 회사코드: 해당 or 공통(빈값)
        must.append(models.Filter(should=[
            models.FieldCondition(key="BUKRS", match=models.MatchValue(value=bukrs)),
            models.FieldCondition(key="BUKRS", match=models.MatchValue(value="")),
        ]))
    return models.Filter(must=must) if must else None


def _serialize_hit(hit) -> Dict[str, Any]:
    pl = hit.payload or {}
    src = pl.get("source") or {}
    cond = pl.get("conditions") or {}
    amount = cond.get("amount") or {}
    output = pl.get("output") or {}
    text = pl.get("text") or {}
    return {
        "RULE_ID": pl.get("rule_id", ""), "DOCUMENT_TYPE": pl.get("document_type", ""),
        "RULE_TYPE": pl.get("rule_type", ""), "STATUS": pl.get("status", ""),
        "SOURCE": {"SOURCE_NAME": src.get("source_name", ""), "SOURCE_SHEET": src.get("source_sheet", ""),
                   "SOURCE_ROWS": src.get("source_rows") or []},
        "CONDITIONS": {"CATEGORY": cond.get("category", ""), "REQUESTER_GROUP": cond.get("requester_group", ""),
                       "AMOUNT": {"MIN_KRW": amount.get("min_krw"), "MIN_INCLUSIVE": amount.get("min_inclusive", True),
                                  "MAX_KRW": amount.get("max_krw"), "MAX_INCLUSIVE": amount.get("max_inclusive", True)}},
        "OUTPUT": {"APPROVAL_LINE_REQUIRED": output.get("approval_line_required", ""),
                   "APPROVER_CODES": output.get("approver_codes") or []},
        "TEXT": {"PASSAGE": text.get("passage", ""), "EMBEDDING_TEXT": text.get("embedding_text", "")},
        "DOC_NAME": pl.get("DOC_NAME", ""), "DOC_ID": pl.get("DOC_ID", ""), "BUKRS": pl.get("BUKRS", ""),
    }


def run_search(body: Dict[str, Any]) -> Dict[str, Any]:
    """규칙 검색 — A search_rules 이식. body: {QUERY_TEXT, TOP_K, FILTERS{...}, MIN_SCORE, INCLUDE_SUPERSEDED, COLLECTION?}."""
    query_text = str(body.get("QUERY_TEXT") or body.get("query_text") or "").strip()
    if not query_text:
        raise ApiError("INVALID_INPUT", "QUERY_TEXT는 필수입니다", status=400)

    top_k = int(body.get("TOP_K") or body.get("top_k") or cfg.RAG_TOP_K_DEFAULT)
    filters = body.get("FILTERS") or body.get("filters") or {}
    if not isinstance(filters, dict):
        raise ApiError("INVALID_INPUT", "FILTERS는 객체여야 합니다", status=400)

    bukrs = str(filters.get("BUKRS") or "").strip()
    document_type = str(filters.get("DOCUMENT_TYPE") or "").strip()
    if document_type and document_type not in cfg.DOCUMENT_TYPES:
        raise ApiError("INVALID_INPUT", f"DOCUMENT_TYPE은 {', '.join(cfg.DOCUMENT_TYPES)} 중 하나여야 합니다", status=400)
    rule_type = str(filters.get("RULE_TYPE") or "").strip()
    if rule_type and rule_type not in cfg.RULE_TYPES:
        raise ApiError("INVALID_INPUT", f"RULE_TYPE은 {', '.join(cfg.RULE_TYPES)} 중 하나여야 합니다", status=400)
    category = str(filters.get("CATEGORY") or "").strip()

    meta: Dict[str, str] = {}
    if document_type:
        meta["document_type"] = document_type
    if rule_type:
        meta["rule_type"] = rule_type
    if category:
        meta["conditions.category"] = category
    if filters.get("DOC_ID"):
        meta["DOC_ID"] = str(filters["DOC_ID"]).strip()

    requester_group = str(filters.get("REQUESTER_GROUP") or "").strip()
    amount_krw_raw = filters.get("AMOUNT_KRW")
    amount_krw = None
    if amount_krw_raw is not None and str(amount_krw_raw).strip() != "":
        try:
            amount_krw = float(amount_krw_raw)
        except (TypeError, ValueError):
            raise ApiError("INVALID_INPUT", "AMOUNT_KRW는 숫자여야 합니다", status=400)

    min_score = body.get("MIN_SCORE")
    min_score = float(min_score) if min_score is not None else float(cfg.RAG_MIN_SCORE)
    include_superseded = bool(body.get("INCLUDE_SUPERSEDED", False))
    collection = str(body.get("COLLECTION") or cfg.RAG_COLLECTION).strip()   # 테스트용 컬렉션 오버라이드

    start = time.time()
    try:
        engine.client.get_collection(collection)
    except Exception:
        return {"STATUS": "SUCCESS", "ITEMS": [], "TOTAL": 0, "ELAPSED": 0.0,
                "META": {"MESSAGE": f"컬렉션 '{collection}'이 없습니다. 규정을 먼저 업로드하세요."}}

    search_model = engine.get_model_for_collection(collection)   # payload EMBED_MODEL 자동감지(BGE)
    vec = search_model.encode([query_text], convert_to_numpy=True).tolist()[0]

    qf = _build_search_filter(bukrs, meta, include_superseded=include_superseded)
    needs_postfilter = bool(requester_group or amount_krw is not None)
    candidate_limit = int(cfg.RAG_CANDIDATE_LIMIT) if needs_postfilter else top_k
    try:
        hits = engine.client.query_points(
            collection_name=collection, query=vec, query_filter=qf,
            limit=candidate_limit, with_payload=True,
        ).points
    except Exception as e:
        cfg.logger.error(f"[approval] 검색 실패: {e}")
        raise ApiError("APPROVAL_SEARCH_FAILED", f"규정 검색 실패: {e}", status=500)

    hits = [h for h in hits if h.score is not None and h.score >= min_score]

    if requester_group:
        hits = [h for h in hits
                if _requester_matches(requester_group,
                                      ((h.payload or {}).get("conditions") or {}).get("requester_group", ""))]

    if amount_krw is not None:
        def _in_range(pl: Dict[str, Any]) -> bool:
            amt = (pl.get("conditions") or {}).get("amount") or {}
            lo, hi = amt.get("min_krw"), amt.get("max_krw")
            if lo is not None:
                if amt.get("min_inclusive", True):
                    if amount_krw < lo:
                        return False
                elif amount_krw <= lo:
                    return False
            if hi is not None:
                if amt.get("max_inclusive", True):
                    if amount_krw > hi:
                        return False
                elif amount_krw >= hi:
                    return False
            return True
        hits = [h for h in hits if _in_range(h.payload or {})]

    hits = hits[:top_k]

    items = []
    for h in hits:
        it = _serialize_hit(h)
        it["SIMILARITY"] = round(float(h.score) * 100, 2)
        items.append(it)

    applied: Dict[str, Any] = {"BUKRS": bukrs}
    if document_type:
        applied["DOCUMENT_TYPE"] = document_type
    if rule_type:
        applied["RULE_TYPE"] = rule_type
    if category:
        applied["CATEGORY"] = category
    if meta.get("DOC_ID"):
        applied["DOC_ID"] = meta["DOC_ID"]
    if requester_group:
        applied["REQUESTER_GROUP"] = requester_group
    if amount_krw is not None:
        applied["AMOUNT_KRW"] = amount_krw

    return {
        "STATUS": "SUCCESS", "ITEMS": items, "TOTAL": len(items),
        "ELAPSED": round(time.time() - start, 3),
        "META": {"MODEL": (hits[0].payload or {}).get("EMBED_MODEL", "") if hits else "",
                 "MIN_SCORE": min_score, "APPLIED_FILTERS": applied},
    }
