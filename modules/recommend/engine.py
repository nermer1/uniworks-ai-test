"""
Recommend 엔진 — A(unirec) app/core.py 고스란히 이식.
---------------------------
1. 모델 및 DB 클라이언트 싱글톤 관리
2. 임베딩용 텍스트 생성 및 시간대 변환
3. Adaptive Max-Weighted 스코어링 엔진
(C 적용: import 경로만 modules.recommend.* 로 변경. 로직·동작은 A와 동일.)
"""
import re
import time
import threading
from typing import Dict, Any, Optional, List
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

from modules.recommend.config import (
    logger, QDRANT_HOST, QDRANT_PORT, MODEL_NAME, VECTOR_SIZE,
)
from modules.recommend.fit_messages import fit_msg

# ============================================================
# 싱글톤 인스턴스 초기화
# ============================================================
logger.info("✅ 모델 및 Qdrant 초기화 중...")
model = SentenceTransformer(MODEL_NAME)
client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=3600)
logger.info(f"✅ 준비 완료! (Qdrant: {QDRANT_HOST}:{QDRANT_PORT})")

# ============================================================
# 컬렉션별 임베딩 모델 자동 감지
# ============================================================
_collection_model_cache: Dict[str, Any] = {}
_collection_model_lock = threading.Lock()

# 벡터 차원 → 모델명 매핑 (EMBED_MODEL 필드가 없는 레거시 컬렉션용)
_DIMENSION_MODEL_MAP = {
    768: MODEL_NAME,                           # BM-K/KoSimCSE-roberta-multitask
    1024: "dragonkue/BGE-m3-ko",               # BGE-m3-ko
}

def get_model_for_collection(collection_name: str):
    """
    컬렉션에 사용된 임베딩 모델을 자동 감지하여 반환.
    1순위: 포인트 payload의 EMBED_MODEL 필드
    2순위: 컬렉션 벡터 차원으로 모델 추정
    3순위: 서비스 모델 폴백
    """
    # 빠른 경로: lock 없이 먼저 확인
    if collection_name in _collection_model_cache:
        return _collection_model_cache[collection_name]

    with _collection_model_lock:
        # 이중 체크: lock 취득 후 재확인 (다른 스레드가 먼저 로드했을 수 있음)
        if collection_name in _collection_model_cache:
            return _collection_model_cache[collection_name]

        detected_model_name = None

        # 1순위: 포인트 payload에서 EMBED_MODEL 확인
        try:
            scroll_result = client.scroll(
                collection_name=collection_name, limit=1, with_payload=["EMBED_MODEL"]
            )
            points = scroll_result[0]
            if points:
                detected_model_name = points[0].payload.get("EMBED_MODEL", "")
        except Exception as e:
            logger.warning(f"⚠️ 컬렉션 포인트 조회 실패 ({collection_name}): {e}")

        # 2순위: 컬렉션 벡터 차원으로 모델 추정
        if not detected_model_name:
            try:
                col_info = client.get_collection(collection_name)
                vec_size = col_info.config.params.vectors.size
                detected_model_name = _DIMENSION_MODEL_MAP.get(vec_size, "")
                if detected_model_name:
                    logger.info(f"🔍 컬렉션 '{collection_name}' 벡터 차원({vec_size}d)으로 모델 추정: {detected_model_name}")
            except Exception as e:
                logger.warning(f"⚠️ 컬렉션 정보 조회 실패 ({collection_name}): {e}")

        # 모델 로드
        if detected_model_name and detected_model_name != MODEL_NAME:
            try:
                loaded_model = get_embed_model_by_name(detected_model_name)
                _collection_model_cache[collection_name] = loaded_model
                logger.info(f"✅ 컬렉션 '{collection_name}' → 모델 '{detected_model_name}' 로드 완료")
                return loaded_model
            except Exception as e:
                logger.error(f"❌ 모델 로드 실패 ({detected_model_name}): {e}, 서비스 모델로 폴백")

        _collection_model_cache[collection_name] = model
        return model


def invalidate_collection_model_cache(collection_name: str):
    """컬렉션 모델 캐시 무효화 (업로드 후 alias 변경 시 호출)"""
    keys_to_remove = [k for k in _collection_model_cache if k == collection_name or k.startswith(collection_name)]
    for k in keys_to_remove:
        del _collection_model_cache[k]


# ============================================================
# 이름 기반 임베딩 모델 lazy 로드 (RAG 등 서비스 모델 외 모델용)
# ============================================================
_named_model_cache: Dict[str, Any] = {}
_named_model_lock = threading.Lock()


def get_embed_model_by_name(model_name: str):
    """모델명으로 SentenceTransformer를 lazy 로드 (캐시). 서비스 모델은 싱글톤 재사용."""
    if not model_name or model_name == MODEL_NAME:
        return model
    if model_name in _named_model_cache:
        return _named_model_cache[model_name]
    with _named_model_lock:
        if model_name in _named_model_cache:
            return _named_model_cache[model_name]
        logger.info(f"🔄 임베딩 모델 로딩: {model_name}")
        loaded = SentenceTransformer(model_name)
        _named_model_cache[model_name] = loaded
        logger.info(f"✅ 모델 로딩 완료: {model_name}")
        return loaded


def get_rag_embed_model():
    """RAG 규정 청크용 임베딩 모델."""
    import modules.recommend.config as cfg
    return get_embed_model_by_name(cfg.RAG_EMBED_MODEL)


try:
    get_rag_embed_model()
except Exception as _rag_preload_err:
    logger.error(f"❌ RAG 임베딩 모델 사전 로드 실패: {_rag_preload_err} (lazy 로드로 폴백)")


def get_collection_name(form_type: Optional[str]) -> str:
    """FORM_TYPE에 따른 컬렉션 Alias 반환 (Java에서 보내는 값을 그대로 alias로 사용)"""
    return (form_type or "CD")


# ============================================================
# 임베딩 텍스트 생성 및 시간대 변환
# ============================================================
def _stopword_targets_for(form_type: Optional[str]) -> List[str]:
    """STOPWORD_TARGETS에서 form_type에 해당하는 컬럼 목록 조회"""
    import modules.recommend.config as cfg
    if not form_type:
        return []
    ft = str(form_type).upper()
    base = ft.split("_")[0] if "_" in ft else ft
    return cfg.STOPWORD_TARGETS.get(ft) or cfg.STOPWORD_TARGETS.get(base) or []


def is_stopword_target(form_type: Optional[str], column: str) -> bool:
    """(form_type, column) 페어가 STOPWORD_TARGETS의 대상이면 True."""
    targets = _stopword_targets_for(form_type)
    if not targets or not column:
        return False
    col_upper = str(column).upper()
    return any(col_upper == t.upper() for t in targets)


def remove_stopwords(text: str, form_type: Optional[str], column: str) -> str:
    """
    settings의 STOPWORDS·STOPWORD_TARGETS 기반 불용어 제거.
    긴 불용어부터 제거하여 부분 문자열 간섭 방지 (예: '주식회사' 먼저, '주식' 나중).
    """
    import modules.recommend.config as cfg
    if not text or not cfg.STOPWORDS:
        return text
    if not is_stopword_target(form_type, column):
        return text
    for w in sorted(set(cfg.STOPWORDS), key=len, reverse=True):
        if w:
            text = text.replace(w, "")
    return " ".join(text.split())


def build_comprehensive_text(r: Dict[str, Any], is_query=False) -> str:
    """
    임베딩용 텍스트 생성기 — settings의 QUERY_COLUMNS 설정 기반
    - FORM_TYPE별 컬럼 목록을 app.config.QUERY_COLUMNS에서 읽어 공백 join.
    - Java 클라이언트(RecommendAPI, VectorDataSchedulingTask)와 동일한 포맷으로 생성하여
      업로드 벡터와 쿼리 벡터의 포맷 일치를 보장합니다.
    - 대소문자 키(MERCH_NAME vs merch_name) 양방향 지원.
    - APPR_TIME 컬럼은 시간대 슬롯(출근/점심/회식/야근)으로 자동 변환.
    - STOPWORDS(불용어)를 각 컬럼값에서 제거 후 join.
    - is_query 파라미터는 호환성을 위해 유지 (동작 동일).
    """
    import modules.recommend.config as cfg  # 모듈 객체 참조 → 런타임 설정 변경 자동 반영
    form_type = str(r.get("FORM_TYPE") or r.get("form_type") or "CD").upper()
    base_form_type = form_type.split("_")[0] if "_" in form_type else form_type
    columns = cfg.QUERY_COLUMNS.get(form_type) or cfg.QUERY_COLUMNS.get(base_form_type, [])

    parts = []
    for col in columns:
        val = str(r.get(col) or r.get(col.lower()) or "").strip()
        if not val:
            continue
        if col.upper() == "APPR_TIME":
            slot = _get_time_slot(val)
            if slot:
                parts.append(slot)
        else:
            val = remove_stopwords(val, form_type, col)
            if val:
                parts.append(val)
    return " ".join(parts)


def _get_time_slot(val) -> Optional[str]:
    """
    시간 문자열을 소비 맥락 기반 시간대 슬롯으로 변환
    출근(06~12), 점심(12~18), 회식(18~22), 야근(22~06)
    - 오전/오후는 임베딩 변별력이 낮아(한 글자 차이) 소비 패턴 반영 단어로 대체
    """
    if not val:
        return None
    try:
        s = str(val).strip()
        hour = int(s.split(":")[0]) if ":" in s else int(s[:2])
        if 6 <= hour < 12:
            return "출근"
        elif 12 <= hour < 18:
            return "점심"
        elif 18 <= hour < 22:
            return "회식"
        else:
            return "야근"
    except (ValueError, TypeError, IndexError):
        return None


# 시간값 정규식 (모듈 레벨 사전 컴파일)
_RE_TIME_HHMMSS = re.compile(r'\b\d{2}:\d{2}:\d{2}\b')
_RE_TIME_HHMM = re.compile(r'\b\d{2}:\d{2}\b')
_RE_TIME_HHMM_PLAIN = re.compile(r'\b\d{4}\b')


def normalize_query_time(query_text: str) -> str:
    """
    검색 쿼리 텍스트에서 시간값(4자리 숫자 HHMM 또는 HH:MM)을 감지하여
    _get_time_slot()과 동일한 시간대 슬롯(출근/점심/회식/야근)으로 변환.
    """
    def _replace_time(match):
        time_str = match.group(0)
        slot = _get_time_slot(time_str)
        return slot if slot else time_str

    # HH:MM:SS 형태 (예: 14:30:00) — HH:MM보다 먼저 매칭해야 함
    result = _RE_TIME_HHMMSS.sub(_replace_time, query_text)
    # HH:MM 형태 (예: 14:30)
    result = _RE_TIME_HHMM.sub(_replace_time, result)
    # HHMM 형태 (예: 1430) — 4자리 숫자가 단독으로 있을 때만
    result = _RE_TIME_HHMM_PLAIN.sub(_replace_time, result)
    return result


# ============================================================
# 스코어링 엔진 (Adaptive Max-Weighted)
# ============================================================
# ============================================================
# 계정 적합성 판정 (FIT_FLAG / FIT_REASON)
#   판별: 독립 축(가맹점/카드/조직/종합) 중 강한 근거 유무
#   문구: 충족된 근거 '조각' 조합 (개수는 설명 두께에만, 판별엔 미반영)
#   코드 필드(MERCH_BIZ_NO/MCC_CODE/KOSTL/CARDNO) 매칭은 임베딩(이름 기반)과
#   독립이라 SCORE에 없는 근거 → 조각으로 정당. 이름(TXT)은 표기용.
#
#   FIT_FLAG — SAP DOMAIN 값 (SAP 측에서 도메인으로 관리, 화면 라벨은 도메인 텍스트 사용)
#     "1" = 추천   : 강한 근거 있음 + 경쟁 계정과 격차 뚜렷 → 그대로 사용 가능
#     "2" = 검토   : 근거가 약하거나 경쟁 계정이 있음 → 확인 후 사용
#     "3" = 미추천 : 추천할 계정 자체를 못 찾음 (HKONT 없음)
#   ※ 값은 '계정의 옳고 그름'이 아니라 '추천 근거의 강도'다. 계정을 내놓고서
#     그 계정을 부정하는 판정("추천했는데 부적합")이 나오지 않도록, 계정이 있으면
#     최소 "2"까지만 준다. "3"은 추천이 없는 경우 전용.
#     배치에 넣지 않은 증빙은 UNIREC이 값을 쓰지 않으므로 SAP 초기값(공란)으로 남는다.
#   FIT_REASON — 위 판정의 근거 문장(툴팁용). 유사도(%) 등 내부 지표는 노출하지 않음.
# ============================================================
# form_type별 조각 축 — CD/ET는 payload 필드 자체가 다르다.
#   party    : (코드필드, 이름필드) — 거래 상대. CD=가맹점, ET=거래처
#   pay      : 코드필드 — 결제수단. ET는 결제수단 개념이 없고 SU_ID가
#              party와 같은 신호라 중복을 피해 None
#   industry : (코드필드, 이름필드) — 가맹점 이력이 없을 때의 폴백. ET는 업종코드 없음
#   ※ 호칭·표현(가맹점 / 같은 카드 / sim_word …)은 여기가 아니라 app/fit_messages.py의
#     `axis.{form_type}.*` 키에 있다 — Settings 화면에서 고칠 수 있어야 하기 때문.
_FIT_AXES = {
    "CD": {"party": ("MERCH_BIZ_NO", "MERCH_NAME"),
           "pay": "CARDNO",
           "industry": ("MCC_CODE", "MCC_NAME")},
    "ET": {"party": ("SU_ID", "SU_NAME"),
           "pay": None,
           "industry": None},
}
FITNESS_STRONG_SIM = 85.0  # ponytail: 유사이력 '강함' 임계, 튜닝 필요하면 settings로 승격
FITNESS_COHORT_RATIO = 0.6   # 코호트 쏠림 임계 — 이 이상이면 2위 대비 배수를 안 봐도 인정
FITNESS_COHORT_MIN = 0.4     # 배수 경로의 비율 하한 (난립하는 코호트 차단)
FITNESS_DOMINANCE = 2.0      # 2위 대비 배수 — 6:3:3처럼 비율은 낮아도 1위가 뚜렷한 경우
FITNESS_DOMINANCE_CNT = 3    # 배수 경로의 1위 최소 건수 (2:1도 '2배'가 되는 것 방지)
FITNESS_STALE_MONTHS = 3     # 검색결과 최신월 대비 이 개월 이상 뒤처지면 '미사용' 신호
FITNESS_KNN_K = 3            # 최근접 이웃 조각의 **판정 하한**. 문구에 이 값을 넣지 말 것 —
                             #   knn.head/tail은 연속 길이(knn_run), hold.party_one은 실제
                             #   이웃 수(len(knn))를 넘긴다. 둘 다 K로 고정하면 어떤 건을 봐도
                             #   같은 숫자가 나와 근거가 템플릿으로 읽힌다.
                             #   실측(lift +35%p)은 K=3에서만 재봤으므로 다른 K는 미검증.
                             #   K를 3 미만으로 내리면 문구 규칙("'모두'는 3건 이상에서만",
                             #   fit_messages 모듈 docstring)과 어긋난다 — knn.head가 '모두'를 쓴다.
                             # ponytail: 튜닝하려면 settings로 승격 (FITNESS_STRONG_SIM과 동일)

# FIT_FLAG 도메인 상수 — SAP DOMAIN 값과 1:1 대응
FIT_OK = "1"      # 추천
FIT_HOLD = "2"    # 검토
FIT_NG = "3"      # 미추천 — 추천 계정이 없을 때만. evaluate_fitness는 이 값을 내지 않는다

# 스코어링 이전 단계에서 끝나 evaluate_fitness를 못 타는 경로용 문구는
#   fit_messages.py의 `msg.no_result` / `msg.not_in_candidates`에 있다.
#   라우터도 반드시 fit_msg()로 읽을 것 — 문장을 직접 만들면 같은 상황에 다른 말이 나간다.
#   (상수로 import하면 관리자가 문구를 바꿔도 재시작 전까지 반영되지 않는 문제도 있다.)


def _fit(flag: str, reason: str) -> dict:
    # 조각은 온점 없이 만들고 ". "로 이어붙이므로, 마지막 문장 종결만 여기서 보장한다
    return {"FIT_FLAG": flag, "FIT_REASON": reason if reason.endswith(".") else reason + "."}


_FLOAT_TAIL = re.compile(r"\.0+$")


def _fnorm(v) -> str:
    """엑셀 float 잔재('1234.0') 정규화 — **꼬리만** 제거한다.

    위치 무관 치환(`replace(".0", "")`)을 쓰면 안 된다: 같은 함수가 코호트 키뿐 아니라
    표시용 텍스트(MERCH_NAME / HKONT_TXT)에도 걸려서 '차량유지비 3.0'이 툴팁에
    '차량유지비 3'으로 나갔다."""
    return _FLOAT_TAIL.sub("", str(v or "").strip())


def _base_form_type(form_type) -> str:
    """'CD_DEV_700' → 'CD'. 접미사만 떼고 폴백은 하지 않는다(호출부가 판단)."""
    return str(form_type or "").split("_")[0].upper()


def _fitness_cohort(filtered: list, field, q_val, hkont) -> tuple:
    """쿼리 코드값(q_val)과 같은 거래군 → (전체건수, 이 계정 건수, 그 point들).

    field/q_val에 같은 길이의 튜플을 주면 모든 필드가 일치해야 같은 코호트로 본다."""
    keys = list(zip(field, q_val)) if isinstance(field, tuple) else [(field, q_val)]
    pts = [p for p in filtered
           if all(_fnorm((p.payload or {}).get(f)) == v for f, v in keys)]
    same = sum(1 for p in pts if (p.payload or {}).get("HKONT") == hkont)
    return len(pts), same, pts


def _cohort_name(pts: list, name_field: str) -> str:
    return next((p.payload.get(name_field) for p in pts
                 if p.payload and p.payload.get(name_field)), "")


def _fit_share(label: str, n: int, same: int) -> tuple:
    """조각 문구 → (첫 문장용, 뒤 문장용).

    n은 조회 범위(Top-SEARCH_LIMIT → 유사도 컷) 안의 건수다. 비율(%)로 바꿔도
    분모가 같은 표본이라 정확해지지 않고 오히려 모집단 비율처럼 읽혀 더 강한
    주장이 되므로 건수를 그대로 쓴다. 범위는 첫 조각에 '검색된'으로 한 번만 밝힌다.
    '모두'는 3건 이상일 때만 — 2건에 '모두'는 근거보다 과신을 주고, 분모가 사라져
    '2건 중 일부'인지 '2건 전부'인지 구분되지 않는다.

    두 버전을 만드는 이유: 같은 종결('…처리했습니다')이 세 문장 연속되면 근거가
    아니라 집계 덤프로 읽힌다. 뒤 문장은 '…도 같은 계정입니다'로 받아 보조
    근거임을 드러내고, 계정명은 첫 문장({a} 자리)에만 넣는다.

    a="{a}"를 넘기는 것은 계정명을 조립 마지막에 치환하기 위한 자리 표시다."""
    if same == n and n >= 3:
        return (fit_msg("share.all.head", label=label, n=n, a="{a}"),
                fit_msg("share.all.tail", label=label, n=n))
    return (fit_msg("share.part.head", label=label, n=n, same=same, a="{a}"),
            fit_msg("share.part.tail", label=label, n=n, same=same))


def _fit_widen(label: str, n: int, same: int) -> str:
    """보조 근거(부서·업종)의 뒤 문장 — '범위를 넓혀 봐도'임을 밝힌다.

    부서·업종 코호트는 앞 조각(가맹점·카드)의 표본을 대개 통째로 품는다.
    "'A' 거래 15건 모두. 같은 부서 거래 21건도 모두"처럼 같은 형식으로 쓰면
    독립 근거가 하나 더 있는 것처럼 읽혀 36건짜리 증거로 착각하게 된다."""
    if same == n and n >= 3:
        return fit_msg("widen.all", label=label, n=n)
    return fit_msg("widen.part", label=label, n=n, same=same)


def _fit_dominant(n: int, same: int, rival: int) -> bool:
    """이 계정이 코호트를 지배하는가 — 근거로 인정할지 판단.

    비율 하나로 자르면 6:3:3(50%)처럼 1위가 2위의 2배인 분포가 통째로 탈락한다
    (실측: UBASE에서 '슈퍼마켓 281:66:64', '한식 38:18:16' 등이 이 구간). 반대로
    배수만 보면 2:1(표본 3건)도 통과하므로 비율 하한과 최소 건수를 함께 건다."""
    if same < 2:
        return False
    if same / n >= FITNESS_COHORT_RATIO:
        return True
    return (same / n >= FITNESS_COHORT_MIN
            and same >= FITNESS_DOMINANCE_CNT
            and same >= rival * FITNESS_DOMINANCE)


def _rival_count(pts: list, hkont) -> int:
    r = _fit_rival(pts, hkont)
    return r[1] if r else 0


def _scoped(item: tuple) -> str:
    """조각 ((첫문장, 뒷문장), 표본크기, 범위표시필요) → 첫 문장 텍스트.
    가맹점·카드 조각은 숫자가 전체 통계로 오해되므로 '검색된'을 앞에 단다.
    ('조회한'은 사용자가 뭔가 조회한 것처럼 읽혀 주체가 시스템임이 드러나지 않았다.)
    업종·유사거래 조각은 문구 자체가 범위를 설명하므로 붙이지 않는다."""
    (head, _tail), _n, needs_scope = item
    # head 안의 '{a}' 자리는 format()이 다시 훑지 않으므로 그대로 살아남는다
    return fit_msg("scope.prefix", head=head) if needs_scope else head


def _josa_ro(word: str) -> str:
    """계정명 뒤에 붙일 '(으)로' 선택 — 받침 없거나 'ㄹ'이면 '로'."""
    ch = (word or "").strip()[-1:]
    if not ch or not ("가" <= ch <= "힣"):
        return "로"
    return "로" if (ord(ch) - 0xAC00) % 28 in (0, 8) else "으로"


def _josa_ga(word: str) -> str:
    """주격 조사 '이/가' 선택 — 받침이 있으면 '이'. 계정 표기('{…}')의 끝 따옴표는 벗기고 본다."""
    ch = (word or "").strip().rstrip("'")[-1:]
    if not ch or not ("가" <= ch <= "힣"):
        return "가"
    return "이" if (ord(ch) - 0xAC00) % 28 else "가"


def _q(nm, alt_key: str = "word.other_account") -> str:
    """계정 표기 — 이름이 있으면 따옴표, 없으면 대체어(fit_messages).

    HKONT_TXT가 비는 컬렉션에서 계정 코드('61032399')가 툴팁에 그대로 노출되던
    것을 막는다. 사용자에게 코드는 근거가 아니라 노이즈다.

    표시용이라 `_fnorm`을 쓰지 않고 공백만 다듬는다 — '차량유지비 3.0'처럼
    계정명이 실제로 '.0'으로 끝나면 코드값 정규화가 이름을 깎아 먹는다."""
    nm = str(nm or "").strip()
    return f"'{nm}'" if nm else fit_msg(alt_key)


def _q_ro(nm, alt_key: str = "word.other_account") -> str:
    """`_q` + '(으)로' 조사."""
    nm = str(nm or "").strip()
    if nm:
        return f"'{nm}'{_josa_ro(nm)}"
    alt = fit_msg(alt_key)
    return f"{alt}{_josa_ro(alt)}"


def _fit_rival(pts: list, hkont) -> Optional[tuple]:
    """코호트 안에서 이 계정 다음으로 많이 쓰인 계정 → (표기명, 건수). 없으면 None.

    표기명은 이름이 없으면 빈 문자열 — 코드로 폴백하지 않는다(`_q` 참고)."""
    cnt: Dict[str, int] = {}
    for p in pts:
        h = (p.payload or {}).get("HKONT")
        if h and h != hkont:
            cnt[h] = cnt.get(h, 0) + 1
    if not cnt:
        return None
    h = max(cnt, key=cnt.get)
    nm = next((p.payload.get("HKONT_TXT") for p in pts
               if p.payload and p.payload.get("HKONT") == h and p.payload.get("HKONT_TXT")), "")
    return nm, cnt[h]


def _fitness_recent_ymd(points: list) -> str:
    """point들의 최근 승인일(YYYYMMDD). APPR_DATE 우선, CRD_SEQ[:8] 폴백. 없으면 ''.

    실 고객사 컬렉션엔 APPR_DATE가 없어 CRD_SEQ 폴백이 사실상 유일한 경로다."""
    best = ""
    for p in points:
        pl = p.payload or {}
        d = str(pl.get("APPR_DATE") or "").strip()
        ymd = d.replace("-", "")[:8] if d and not d.startswith("0000") else ""
        if not ymd:
            seq = str(pl.get("CRD_SEQ") or "").strip()
            ymd = seq[:8] if len(seq) >= 8 and seq[:8].isdigit() else ""
        if len(ymd) == 8 and ymd > best:
            best = ymd
    return best


def _ym_gap(a: str, b: str) -> int:
    """YYYYMMDD 두 값의 개월 차(b - a). 잘못된 값이면 0."""
    if len(a) < 6 or len(b) < 6:
        return 0
    return (int(b[:4]) - int(a[:4])) * 12 + (int(b[4:6]) - int(a[4:6]))


def evaluate_fitness(top: dict, form_type: str, filtered: list,
                     query_item: dict, total: int, runner_up: Optional[dict] = None) -> dict:
    """Top1 계정 적합성 판정 → {FIT_FLAG: "1"|"2"|"3", FIT_REASON: 근거 문장}.

    근거는 스코어링 결과 + 쿼리 코드값과 일치하는 검색결과 payload 집계만
    사용(추가 쿼리 0). 유사도(%)·점수차 등 내부 지표는 문구에 노출 안 함.
    query_item의 코드 필드가 없으면 해당 조각은 자동 생략(하위호환).
    strong(판별) 우선순위: 가맹점(#4) > 카드(#2) > 업종(#12,가맹점폴백)
    > 지배율(#3,가맹점폴백). 부서(#7)·미사용경고(#6)는 weak(문구 전용).
    runner_up: 2위 계정 결과(dict). 거래상대 근거가 없는 폴백 건의 접전 문구에만 사용.
    """
    qi = query_item or {}
    d = top.get("SCORE_DETAIL", {})
    max_sim = round(d.get("MAX_SIM", 0))
    hkont = top.get("HKONT")
    freq = top.get("FREQUENCY", 0)
    pct = round(top.get("PERCENTAGE", 0))
    low_conf = top.get("CONFIDENCE") == "LOW"
    # 접미사(CD_DEV_700)를 먼저 떼고 축을 찾는다. 이 정규화가 없으면 ET 컬렉션이
    # 조용히 CD 축으로 떨어져 SU_ID 근거를 잃고 '가맹점' 표현이 세금계산서 건에 나갔다.
    ft = _base_form_type(form_type)
    ft = ft if ft in _FIT_AXES else "CD"
    axes = _FIT_AXES[ft]
    sim_word = fit_msg(f"axis.{ft}.sim_word")
    none_word = fit_msg(f"axis.{ft}.none_word")
    p_word = fit_msg(f"axis.{ft}.party_word")

    # 계정명을 첫 문장에 한 번 쓴다 — 툴팁만 읽고도 무엇에 대한 근거인지 알아야 하고,
    # check-score 경로에서는 '이 계정'이 사용자가 고른 계정이라 특히 헷갈린다.
    acct_nm = _q(top.get("HKONT_TXT"), "word.this_account")
    acct_ro = _q_ro(top.get("HKONT_TXT"), "word.this_account")

    grp = [p for p in filtered if (p.payload or {}).get("HKONT") == hkont]
    strong, weak = [], []

    # 근거가 약한 경로에서 '그럼 왜 이 계정인가'에 답하기 위한 값 — 검색결과 안에서
    # 이 계정이 최다인가. SCORE 1위와 건수 1위는 다르므로 확인 없이 단정하면 거짓이 된다.
    _hcnt: Dict[str, int] = {}
    for p in filtered:
        h = (p.payload or {}).get("HKONT")
        if h:
            _hcnt[h] = _hcnt.get(h, 0) + 1
    freq_top = bool(_hcnt) and freq >= max(_hcnt.values())

    used_counts = set()   # 이미 서술한 (모수, 이 계정 건수) — 같은 숫자를 두 번 말하지 않는다

    def dup(n: int, same: int) -> bool:
        if (n, same) in used_counts:
            return True
        used_counts.add((n, same))
        return False

    # #4 거래 상대 일관성 (최강) — CD=가맹점(MERCH_BIZ_NO), ET=거래처(SU_ID)
    party_covered = False
    party_rival = None          # 같은 코호트를 나눠 쓰는 최다 경쟁 계정 → (표기명, 건수)
    party_ctx = None            # 보류 문구 재구성용 → (라벨, 코호트 건수, 이 계정 건수)
    p_code, p_name = axes["party"]
    q_party = _fnorm(qi.get(p_code))
    q_pname = _fnorm(qi.get(p_name))
    if q_party:
        # 코호트 키에 이름을 함께 건다 — 대행결제(PG/VAN)·해외건은 사업자번호가 대행사 번호나
        # 더미값(ZZZZZZZZZZ, 9999999999)이라 무관한 가맹점이 한 번호를 공유한다.
        # 실측(UBASE 31,800건): 전체의 53%가 이름이 섞인 번호, 최악의 번호 하나에 가맹점 1,377곳.
        # 번호만으로 잡으면 남의 가게 통계를 "'A' 거래 N건"이라 단정하게 된다.
        # (이름 추가 후 코호트 1위 쏠림 68.7%→77.0%, 근거가 1건뿐인 비율 7%→14%)
        ckey, cval = ((p_code, p_name), (q_party, q_pname)) if q_pname else (p_code, q_party)
        n, same, pts = _fitness_cohort(filtered, ckey, cval, hkont)
        if same >= 1:
            party_covered = True
            dup(n, same)
            nm_val = _cohort_name(pts, p_name)
            nm = (fit_msg("label.party.named", name=nm_val) if nm_val
                  else fit_msg("label.party.unnamed", party_word=p_word))
            if same >= 2:
                strong.append((_fit_share(nm, n, same), n, True))
            else:
                # party 조각은 항상 strong[0]이라 tail이 소비될 경로가 없다 — 빈 값
                strong.append(((fit_msg("party.one.head", label=nm, a="{a}"), ""), n, True))
            party_ctx = (nm, n, same)
            # 지배적이지 않으면 실제로 계정이 갈리는 거래상대 → 경쟁 계정을 근거로 보류
            if not _fit_dominant(n, same, _rival_count(pts, hkont)):
                party_rival = _fit_rival(pts, hkont)

    # #13 최근접 이웃 쏠림 — 검색결과에서 이 증빙과 가장 가까운 K건이 전부 이 계정인가.
    #   그룹별 스코어에는 없는 정보다(SCORE는 계정별로 나눠 계산해 전역 순위가 소실된다).
    #   실측(UBASE 4,000건 LOO): 충족 92.8%(64%) vs 미충족 57.8% → lift +35%p, 조각 중 최강.
    #   MAX_SIM을 쓰지 않는 이유는 조각이 이미 있는 구간에서 그것이 '같은 가맹점이냐'와
    #   같은 정보이기 때문(독점 구간 98%+ 76.9% vs 90~95% 60.0%로 단조성 없음). 게다가
    #   95~98% 구간은 37%가 다른 가맹점이라 '매우 비슷한 거래'로 서술하면 거짓이 섞인다.
    #   승격 전용으로만 쓴다 — 강등에 쓰면 다빈도 가맹점이 되레 보류되던 문제가 재발한다.
    ranked = sorted(filtered, key=lambda p: -p.score)
    knn = ranked[:FITNESS_KNN_K]
    knn_same = sum(1 for p in knn if (p.payload or {}).get("HKONT") == hkont)
    # 문구에 쓰는 건수는 K가 아니라 **이 계정이 1위부터 연속으로 이어지는 실제 길이**다.
    #   판정 기준은 그대로다 — '상위 K건이 전부 이 계정' ⟺ '연속 길이 >= K'.
    #   len(knn)을 넘겨도 이 경로에선 가드가 len(knn) >= K라 항상 정확히 K(=3)가 찍혔고,
    #   어떤 건을 봐도 '3건'이라 근거가 템플릿으로 읽혔다(사용자 피드백).
    #   연속 길이는 위조할 수 없는 실제 관측치이고 길수록 강한 근거라 숫자가 곧 정보가 된다.
    #   '모두'는 접두 구간이라 여전히 참이다.
    knn_run = 0
    for p in ranked:
        if (p.payload or {}).get("HKONT") != hkont:
            break
        knn_run += 1
    knn_pure = knn_run >= FITNESS_KNN_K
    # dup에도 실제 건수를 등록한다 — 출력한 숫자와 등록한 숫자가 달라지면 dedup이
    # 거짓말을 한다: (K, K)로 고정하면 '12건 모두'를 말하고도 (3,3)을 등록해
    # 같은 12건을 다른 조각이 또 말하고, 정작 진짜 (3,3) 코호트는 말한 적 없는
    # 숫자에 막혀 사라진다.
    # ponytail: dup은 건수만 비교한다 — 건수가 같고 레코드는 다른 축(예: 카드 4건 ≠
    #   최근접 4건)이 잘릴 수 있다. 다른 조각도 전부 같은 방식이라 맞춰둔 것이고,
    #   실제로 문제가 되면 dup 키를 point id 집합으로 올릴 것.
    if knn_pure and not dup(knn_run, knn_run):
        # 표본크기를 연속 길이가 아니라 total로 단다 — 이 조각의 근거는 'N건'이 아니라
        # '검색결과 전체를 정렬했을 때의 상위 N건'이다. N을 넣으면 두 번째 조각
        # 필터(sn*5 >= head_n)에 걸려 다빈도 가맹점에서 최강 조각이 문구에서 사라진다.
        strong.append(((fit_msg("knn.head", n=knn_run, a="{a}"),
                        fit_msg("knn.tail", n=knn_run)),
                       total, False))

    # #2 결제수단 (CD=같은 카드) — ET는 SU_ID가 party와 같은 신호라 생략.
    #   CARDNO는 운영 QUERY_COLUMNS에 없는 유일한 진짜 독립 축이지만, 카드 1장이
    #   평균 5.4개 계정을 쓴다(실측) → 1건 매칭을 근거로 쓰면 안 되므로 다른 조각과
    #   같은 코호트·임계로 통일. CONTEXT_DETAIL 대신 직접 집계해 MATCH_FEATURES 설정과 분리.
    if axes["pay"]:
        pay_field = axes["pay"]
        pay_word = fit_msg(f"axis.{ft}.pay_word")
        q_pay = _fnorm(qi.get(pay_field))
        if q_pay:
            n, same, _pts = _fitness_cohort(filtered, pay_field, q_pay, hkont)
            if _fit_dominant(n, same, _rival_count(_pts, hkont)) and not dup(n, same):
                strong.append((_fit_share(f"{pay_word} ", n, same), n, True))

    # #7 부서 쏠림 (조직 축) — weak. 운영 QUERY_COLUMNS에 KOSTL_TXT가 있어 임베딩과
    #   중복이고, 부서당 평균 6.9개 계정으로 코드필드 중 분산이 가장 크다(실측) →
    #   판별 근거가 못 되는 배경 정보.
    #   중복 서술 방어는 dup()이 하므로 party_covered로 또 막지 않는다
    #   (가맹점 조각이 94.7% 뜨는 탓에 이중 조건이 이 조각을 통째로 죽이고 있었다).
    q_kostl = _fnorm(qi.get("KOSTL"))
    if q_kostl:
        n, same, pts = _fitness_cohort(filtered, "KOSTL", q_kostl, hkont)
        if _fit_dominant(n, same, _rival_count(pts, hkont)) and not dup(n, same):
            dept = _cohort_name(pts, "KOSTL_TXT")
            dn = (fit_msg("label.dept.named", name=dept) if dept
                  else fit_msg("label.dept.unnamed"))
            weak.append(_fit_widen(dn, n, same))      # weak은 항상 뒤 문장

    # #12 업종 쏠림 — CD만 해당(ET는 업종코드 없음).
    #   거래 상대 근거가 있어도 죽이지 않는다. party 게이트는 `same >= 1`이라 사실상
    #   게이트가 없는데(가맹점 이력 1건이면 통과) 업종은 `_fit_dominant`를 넘긴 근거라
    #   강도가 역전돼 있었다. 실측(CD_DEV_700_1000 1,035건 LOO): 자격을 갖춘 514건 중
    #   415건(80%)이 `not party_covered` 하나로 사라져 근거가 한 문장에서 끝났다.
    #   중복 서술 방어는 dup()이 한다 — 같은 (모수, 건수)면 여기서도 걸러진다.
    if axes["industry"]:
        i_code, i_name = axes["industry"]
        q_ind = _fnorm(qi.get(i_code))
        if q_ind:
            n, same, pts = _fitness_cohort(filtered, i_code, q_ind, hkont)
            if _fit_dominant(n, same, _rival_count(pts, hkont)) and not dup(n, same):
                ind = _cohort_name(pts, i_name)
                inm = (fit_msg("label.industry.named", name=ind) if ind
                       else fit_msg("label.industry.unnamed"))
                # 업종은 '이 가게는 이렇다'가 아니라 '이런 가게는 보통 이렇다'는 일반론이다.
                # 가맹점 조각과 형식이 같으면 사용자가 같은 강도로 읽으므로 앞에 한정을 단다.
                # 단 뒤 문장으로 밀릴 땐 접두를 빼야 한다 — 긍정 근거 뒤에 '이력은
                # 없지만'이 따라붙으면 문맥이 튄다. 대신 '넓혀 봐도'로 일반론임을 남긴다.
                i_widen = (fit_msg("label.industry.widen.named", name=ind, josa=_josa_ro(ind))
                           if ind else fit_msg("label.industry.widen.unnamed"))
                i_tail = _fit_widen(i_widen, n, same)
                # party가 있으면 party가 항상 strong[0]이라 업종 head는 렌더될 경로가
                # 없다. 그래도 만들어 두면 조립 규칙이 바뀔 때 '이력은 없지만'이라는
                # 거짓 문장이 조용히 새어 나가므로, 애초에 그 경로에서는 짓지 않는다.
                i_head = (fit_msg("industry.prefix", party_word=p_word,
                                  head=_fit_share(inm, n, same)[0])
                          if not party_covered else i_tail)
                strong.append(((i_head, i_tail), n, False))

    # #3 지배율 (폴백) — 거래상대 근거가 없을 때만. PERCENTAGE는 FREQ_BONUS의
    #   입력값이라 SCORE에 이미 반영된 값이고, 코호트 조각과 같은 숫자가 되기 쉽다.
    #   `not strong`이던 조건을 `not party_covered`로 넓혔다 — 최근접 3건 조각만
    #   붙는 건(코드필드 없는 쿼리)이 한 문장으로 끝나 근거가 얇았다. 판정은 이미
    #   has_strong으로 결정되므로 이 완화는 문구만 두껍게 한다.
    if not party_covered and pct >= 60 and freq >= 2 and not dup(total, freq):
        strong.append(((_fit_share(fit_msg("label.overall.head", sim_word=sim_word),
                                   total, freq)[0],
                        _fit_widen(fit_msg("label.overall.widen", sim_word=sim_word),
                                   total, freq)),
                       total, False))

    # (#8 개인 조각 제거: CD payload 개인식별자는 EMPNO인데 쿼리는 PERNR이라
    #  항상 불일치 + weak 조각이라 판별 영향 없음. form_type별 EMPNO/PERNR 분기
    #  복잡도만 늘어 제거함.)

    # #6 최근성 (맥락) — '최근에 썼다'는 정보가 아니다. 실 데이터(UBASE 31.8k, 6개월)
    #   기준 다빈도 계정의 94%가 데이터 끝월로 같은 값이라 변별력이 없다.
    #   검색결과 전체의 최신일 대비 이 계정만 뒤처질 때(계약종료·조직개편·카드해지)만 신호.
    #   기준선을 오늘이 아닌 검색결과에서 잡으므로 배치 저장 후 조회해도 문구가 안 틀어진다.
    #   '다만'을 달지 않는다 — rival_note도 '다만'으로 시작해 둘이 함께 붙으면
    #   "다만 A. 다만 B."가 된다. 주어를 밝히면 역접 없이도 경고로 읽힌다
    #   (기존 "사용된 이력이 없습니다"는 가맹점을 안 갔다는 뜻으로도 읽혔다).
    grp_ymd = _fitness_recent_ymd(grp)
    all_ymd = _fitness_recent_ymd(filtered)
    stale = ([fit_msg("note.stale", ym=f"{grp_ymd[:4]}년 {int(grp_ymd[4:6])}월")]
             if grp_ymd and _ym_gap(grp_ymd, all_ymd) >= FITNESS_STALE_MONTHS else [])

    # (#11 시간대 조각 제거: APPR_TIME이 운영 QUERY_COLUMNS에 있어 시간대 단어가 이미
    #  임베딩에 들어간다. 실측으로도 계정 80%에 조각이 붙고 그중 64%가 '점심'인데
    #  전체 건수의 50%가 점심이라 기저율과 같은 값 → 정보량 0.)

    # ---- 판별 (색은 강한 근거 유무, 문구는 조각 조합) ----
    has_strong = bool(strong)

    # 근거가 약해도 계정은 추천한 상태이므로 '미추천'(3)을 주지 않는다 — 자기가 낸 답을
    # 자기가 부정하는 판정이 된다. 강도 차이는 FIT_REASON 문구가 설명한다.
    # 근거가 얇을수록 '그럼 왜 이 계정이냐'가 남는다 — 최다일 때만 그렇게 말한다
    why = (fit_msg("why.top", acct=acct_nm, josa=_josa_ga(acct_nm), freq=freq) if freq_top
           else fit_msg("why.plain", freq=freq, acct=acct_nm))

    if max_sim < FITNESS_STRONG_SIM and not has_strong:
        # 강등 사유는 '건수가 적다'가 아니라 '비슷한 정도가 낮다'다. total은 200까지
        # 가므로 "187건 중 12건이지만 이력이 부족합니다"는 앞 숫자와 모순됐다.
        return _fit(FIT_HOLD, fit_msg("hold.no_similar", sim_word=sim_word,
                                      total=total, why=why))

    if not has_strong:
        return _fit(FIT_HOLD, fit_msg("hold.no_strong", sim_word=sim_word, total=total,
                                      why=why, none_word=none_word))

    # 접전 판정 — 같은 거래상대 코호트를 다른 계정이 나눠 쓰면 보류.
    #   SCORE_GAP은 임베딩 축이라 독립 근거(코드필드)를 무효화하면 안 된다.
    #   다빈도 가맹점일수록 Top-N이 같은 가맹점 거래로 채워져 1·2위 점수가 붙는 탓에,
    #   가장 확신할 수 있는 건이 되레 보류되던 문제를 코호트 실측으로 대체.
    #   단 최근접 3건이 전부 이 계정이면(#13) 그쪽이 더 강한 근거라 강등하지 않고,
    #   경쟁 계정은 문구 뒤에 남겨 사실을 감추지 않는다.
    rival_note = []
    if party_rival:
        # 이 경로는 쏠림이 60% 미만일 때만 온다 → '이 계정입니다'는 과한 단정이라
        # 경쟁 계정 건수를 나란히 보여준다. 코호트 1위는 스코어링 Top1과 별개라
        # 이 계정이 최다가 아닐 수 있어(1:1 동률, 역전) '가장 많지만'은 최다일 때만 쓴다.
        rv_nm, rv_cnt = party_rival
        lbl, n_all, n_same = party_ctx
        if knn_pure:
            # '도'는 이 계정이 더 많다는 함의라 동률·역전에서는 '이'로 바꾼다
            josa = "도" if n_same > rv_cnt else "이"
            rival_note = [fit_msg("note.rival", rival=_q_ro(rv_nm),
                                  josa=josa, rival_n=rv_cnt)]
        else:
            # 동률·역전이면 '가장 많지만'을 쓸 수 없고 "N건인데"는 왜 이 계정을
            # 추천했는지 설명하지 못했다. 두 계정 건수를 나란히 놓으면 '갈린다'는
            # 사실 자체가 보류 사유로 읽힌다. 3개 이상으로 갈리면 '등'을 붙인다 —
            # 안 붙이면 두 건수의 합이 모수와 안 맞아 사용자가 셈을 못 맞춘다.
            etc = " 등" if n_all > n_same + rv_cnt else ""
            split = fit_msg("hold.rival_split", label=lbl, n=n_all, acct=acct_nm,
                            same=n_same, rival=_q(rv_nm), rival_n=rv_cnt, etc=etc)
            # 판정은 그대로 두고 남은 조각을 잇는다 — '갈리는데 왜 이 계정이냐'가
            #   설명되지 않아 159건(15.4%)이 전부 같은 한 문장으로 나가고 있었다.
            #   조건은 '계정명을 스스로 대는 조각'({a} 자리를 가진 head)뿐이라는 것.
            #   앞 문장이 계정을 둘 이상 나열한 직후라, '…도 같은 계정입니다' 류는
            #   어느 계정인지 지시가 깨진다. 업종은 party가 있으면 head마저 '넓혀 봐도
            #   …같은 계정입니다'라 여기서 걸러진다(실측 28건이 이 형태로 나갔다).
            #   같은 이유로 weak(부서)와 stale도 붙이지 않는다 — 둘 다 tail 형태뿐이다.
            more = [t[0].replace("{a}", acct_ro) for t, sn, _ in strong[1:2]
                    if sn * 5 >= strong[0][1] and "{a}" in t[0]]
            return _fit(FIT_HOLD, ". ".join([split] + more))

    # 거래상대 이력이 이 계정 1건뿐이면(경쟁은 없지만 표본도 없음) 최근접 이웃이 이 계정으로
    #   몰려 있을 때만 추천. 실측(UBASE 독점 176건): 최근접 3건 중 2건+ 90.6%/68.8% vs 1건 이하 53.5%.
    if party_ctx and party_ctx[1] == 1 and party_ctx[2] == 1 and knn_same < 2:
        # '대부분 다른 계정'은 표본(최근접 이웃)을 감춘 인상 서술이었다 — 다른 조각이
        # 전부 'N건 중 M건'을 지키는 사이 이 문장만 근거 없는 총평으로 읽힌다.
        # 분모와 실제 경쟁 계정을 드러내야 사용자가 스스로 판단할 수 있다.
        #   두 사실('이력 1건뿐' / '최근접 이웃도 이 계정이 아님')은 역접이 아니다 —
        #   같은 결론을 가리키는 두 신호라 '반면'을 달면 독자가 없는 대비를 찾는다.
        #   분모는 len(knn) — K로 고정하면 안 된다. 이 경로는 knn_pure와 달리
        #   len(knn) >= K 가드가 없어 검색결과가 K건 미만일 때도 들어오고, 그때
        #   'K건 중'은 없는 거래를 근거로 삼는 거짓 문장이 된다("이력은 1건뿐"과도 모순).
        #   rival_split/low_conf와 달리 여기엔 남은 조각을 잇지 않는다 — 문장이
        #   '근거로 삼기엔 부족합니다'로 끝나는데 뒤에 긍정 근거를 붙이면 판정을
        #   스스로 뒤집는다. (업종 조각 해제 후에도 해당 경로 이득은 4건뿐이다.)
        knn_rv = _fit_rival(knn, hkont)
        rv_disp = _q(knn_rv[0]) if knn_rv else ""
        rv_txt = (fit_msg("hold.party_one.rival", rival=rv_disp, josa=_josa_ga(rv_disp),
                          rival_n=knn_rv[1])
                  if knn_rv else "")
        return _fit(FIT_HOLD,
                    fit_msg("hold.party_one", label=party_ctx[0], a=acct_ro,
                            knn_n=len(knn), knn_same=knn_same, rival_txt=rv_txt))

    # 거래상대 근거가 없는 폴백(업종·지배율) 건에서만 점수 접전을 강등 신호로 사용
    if low_conf and not party_covered and not knn_pure:
        # 남은 조각은 '다만 …' **앞**에 넣는다. 뒤에 붙이면 마무리 유보 뒤에 긍정
        #   근거가 따라와 순서가 거꾸로 읽힌다. 여기서는 tail을 써도 안전하다 —
        #   {head} 첫 문장이 계정을 하나만 대므로 '같은 계정'의 지시가 흔들리지 않는다.
        more = [t[1] for t, sn, _ in strong[1:2] if sn * 5 >= strong[0][1]] + weak[:1]
        return _fit(FIT_HOLD,
                    fit_msg("hold.low_conf",
                            head=". ".join([_scoped(strong[0])] + more).replace("{a}", acct_ro),
                            rival=_q((runner_up or {}).get("HKONT_TXT"))))

    # stale(미사용 경고)은 weak보다 중요한 신호라 잘리지 않게 항상 뒤에 붙인다
    # 두 번째 조각은 표본이 첫 조각의 1/5 이상일 때만 — '94건 중 81건' 뒤에 '카드 2건'
    # 같은 잔챙이 근거는 앞 문장의 신뢰까지 깎는다. 다만 1/3은 과하게 빡빡해서
    # 근거 두 개를 보여줄 기회를 대부분 잘라내고 있었다(2문장 비율 13.6%).
    head_n = strong[0][1]
    extras = [t[1] for t, sn, _ in strong[1:2] if sn * 5 >= head_n]
    parts = [_scoped(strong[0])] + extras + weak[:1] + rival_note + stale
    # 계정명은 첫 문장에만 — 매 문장 반복하면 근거가 아니라 잡음이 된다
    return _fit(FIT_OK, ". ".join(parts).replace("{a}", acct_ro))


def get_hybrid_recommendation(points: list, query_item: Dict[str, Any], form_type: str,
                              limit: Optional[int] = None, fit_hkont: Optional[str] = None) -> list:
    """
    Adaptive Max-Weighted 스코어링 엔진

    1. 유사도 하한선(SIMILARITY_THRESHOLD) 이하 포인트 제거
    2. HKONT별 그룹핑 → 상위 3건 추출 + 피처 일치 카운트 수집
    3. Adaptive 가중 평균:
       - gap = MAX_SIM - AVG_REST (최고 유사도와 나머지 평균의 차이)
       - w_max = 0.5 + 0.5 × gap (gap이 클수록 MAX_SIM에 가중치 부여)
       - BASE_SCORE = MAX_SIM × w_max + AVG_REST × (1 - w_max)
    4. 빈도 보정: freq_bonus = min(빈도비율 × 100 × 0.05, MAX_FREQ_BONUS)
    5. 피처 매칭 보정: context_bonus = Σ(일치비율 × 피처가중치), max MAX_CONTEXT_BONUS
    6. SCORE = min(BASE_SCORE + freq_bonus + context_bonus, 99.99) → XX.XX%
    7. 동점 시 우선순위: MAX_SIM → CONTEXT_BONUS → FREQUENCY 순
    8. CONFIDENCE: 1위-2위 점수 차 기반 신뢰도 (HIGH/MEDIUM/LOW)
    """
    if not points:
        return []

    # 접미사 정규화를 여기서 한 번 — 모든 호출부가 이 함수를 지나므로 caller마다
    # 챙기지 않아도 된다(/search/text는 raw form_type을 넘겨 MATCH_FEATURES 조회가
    # 늘 빈 리스트였고, FIT 판정도 CD 축으로 떨어졌다).
    form_type = _base_form_type(form_type)

    # 유사도 하한선 적용
    import modules.recommend.config as cfg
    filtered = [p for p in points
                if hasattr(p, 'score') and p.score is not None and p.score >= cfg.SIMILARITY_THRESHOLD]
    if not filtered:
        return []

    total = len(filtered)

    # 피처 매칭 대상 쿼리값 추출
    features = cfg.MATCH_FEATURES.get(form_type, [])
    feature_weight_map = {f: w for f, w in features}  # O(n) 1회 변환 → 루프 내 O(1) 조회
    query_features = {}
    for field in feature_weight_map:
        val = _fnorm(query_item.get(field) or query_item.get(field.lower()))
        if val:
            query_features[field] = val

    # HKONT별 그룹핑
    groups: Dict[tuple, Dict[str, Any]] = {}

    for p in filtered:
        hkont = p.payload.get("HKONT")
        if not hkont:
            continue
        hkont_txt = p.payload.get("HKONT_TXT", "")
        key = (hkont, hkont_txt)

        if key not in groups:
            groups[key] = {"count": 0, "sim_scores": [], "feature_matches": {f: 0 for f in query_features}}

        groups[key]["count"] += 1
        groups[key]["sim_scores"].append(p.score)

        # 피처 일치 카운트
        for field, query_val in query_features.items():
            point_val = _fnorm(p.payload.get(field))
            if point_val == query_val:
                groups[key]["feature_matches"][field] += 1

    # 각 HKONT별 스코어 계산
    results = []
    for (hkont, hkont_txt), g in groups.items():
        top_sims = sorted(g["sim_scores"], reverse=True)[:3]
        max_sim = top_sims[0]

        if len(top_sims) == 1:
            # 단건 매칭: 해당 유사도가 곧 스코어
            base_score = max_sim * 100
            w_max = 1.0
        else:
            # 2건 이상: Adaptive Max-Weighted Average
            rest_sims = top_sims[1:]
            avg_rest = sum(rest_sims) / len(rest_sims)
            gap = max_sim - avg_rest
            w_max = cfg.MAX_WEIGHT_BASE + cfg.MAX_WEIGHT_SCALE * gap
            base_score = (max_sim * w_max + avg_rest * (1 - w_max)) * 100

        # 빈도 보정 (최대 MAX_FREQ_BONUS %p)
        freq_ratio = g["count"] / total
        freq_bonus = min(freq_ratio * 100 * 0.05, cfg.MAX_FREQ_BONUS)

        # 피처 매칭 보정 (최대 MAX_CONTEXT_BONUS %p)
        context_bonus = 0.0
        context_detail = {}
        for field, query_val in query_features.items():
            match_count = g["feature_matches"][field]
            if match_count > 0:
                match_ratio = match_count / total
                feature_weight = feature_weight_map.get(field, 0)
                bonus = match_ratio * feature_weight
                context_bonus += bonus
                context_detail[field] = {
                    "MATCHES": match_count,
                    "RATIO": round(match_ratio * 100, 1),
                    "BONUS": round(bonus, 2),
                }
        context_bonus = min(context_bonus, cfg.MAX_CONTEXT_BONUS)

        # 최종 스코어 (XX.XX%, 0~99.99 범위)
        score = max(min(base_score + freq_bonus + context_bonus, 99.99), 0.0)

        avg_sim = sum(g["sim_scores"]) / len(g["sim_scores"]) * 100

        results.append({
            "HKONT": hkont,
            "HKONT_TXT": hkont_txt,
            "SCORE": round(score, 2),
            "FREQUENCY": g["count"],
            "PERCENTAGE": round(freq_ratio * 100, 2),
            "AVG_SIMILARITY": round(avg_sim, 2),
            "SCORE_DETAIL": {
                "MAX_SIM": round(max_sim * 100, 2),
                "W_MAX": round(w_max, 4),
                "BASE_SCORE": round(base_score, 2),
                "FREQ_BONUS": round(freq_bonus, 2),
                "CONTEXT_BONUS": round(context_bonus, 2),
                "CONTEXT_DETAIL": context_detail if context_detail else None,
            }
        })

    # SCORE 내림차순 정렬 — 동점 시 MAX_SIM → CONTEXT_BONUS → FREQUENCY 순
    results.sort(key=lambda x: (
        x["SCORE"],
        x["SCORE_DETAIL"]["MAX_SIM"],
        x["SCORE_DETAIL"]["CONTEXT_BONUS"],
        x["FREQUENCY"],
    ), reverse=True)

    # 신뢰도 계산 (1위-2위 점수 차 기반)
    if results:
        score_gap = round(results[0]["SCORE"] - results[1]["SCORE"], 2) if len(results) >= 2 else 0.0
        if len(results) == 1 or score_gap >= 15.0:
            confidence = "HIGH"
        elif score_gap >= 5.0:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        results[0]["CONFIDENCE"] = confidence
        results[0]["SCORE_GAP"] = score_gap
        results[0].update(evaluate_fitness(results[0], form_type, filtered, query_item, total,
                                           results[1] if len(results) >= 2 else None))

        # check-score 용도 — 사용자가 지정한 계정(Top1이 아닐 수 있음)도 판정.
        # CONFIDENCE/SCORE_GAP은 Top1에만 붙으므로 '2위와 접전' 강등은 자동 미적용된다.
        # 지정 계정을 찾으면 무조건 멈춘다 — 판정 여부를 매칭 조건에 넣으면 그 계정이
        # Top1일 때(이미 판정됨) 루프가 안 멈추고, HKONT_TXT가 갈려 같은 HKONT가 두
        # 엔트리로 그룹핑된 경우(update-codes 부분 반영) 뒤쪽 엔트리를 헛되게 또 판정한다.
        if fit_hkont:
            for r in results:
                if str(r["HKONT"]) == str(fit_hkont):
                    if "FIT_FLAG" not in r:
                        r.update(evaluate_fitness(r, form_type, filtered, query_item, total))
                    break

    if limit:
        results = results[:limit]

    return results


# ============================================================
# 컬렉션 유틸리티
# ============================================================
_alias_cache: Dict[str, str] = {}   # alias_name → collection_name
_alias_cache_ts: float = 0.0
_ALIAS_CACHE_TTL = 60.0             # 60초마다 갱신
_alias_cache_lock = threading.Lock()


def _refresh_alias_cache():
    """Qdrant에서 전체 alias 목록을 가져와 캐시 갱신 (멀티스레드 race condition 방지)"""
    global _alias_cache, _alias_cache_ts
    with _alias_cache_lock:
        # 이중 체크: 다른 스레드가 이미 갱신했을 수 있음
        if time.monotonic() - _alias_cache_ts <= _ALIAS_CACHE_TTL:
            return
        aliases = client.get_aliases().aliases
        _alias_cache = {a.alias_name: a.collection_name for a in aliases}
        _alias_cache_ts = time.monotonic()
        logger.debug(f"🔄 Alias 캐시 갱신 ({len(_alias_cache)}개)")


def invalidate_alias_cache():
    """Alias 캐시 강제 무효화 (업로드/alias 변경 후 호출)"""
    global _alias_cache_ts
    _alias_cache_ts = 0.0


def _resolve_target_collection(alias_name: str, target_collection: Optional[str] = None) -> str:
    """Alias를 물리 컬렉션으로 해소 (캐시 TTL: 60초)"""
    if target_collection:
        return target_collection
    try:
        if time.monotonic() - _alias_cache_ts > _ALIAS_CACHE_TTL:
            _refresh_alias_cache()
        if alias_name in _alias_cache:
            return _alias_cache[alias_name]
        logger.warning(f"⚠️ Alias '{alias_name}' 미등록 — 컬렉션명으로 직접 시도합니다")
    except Exception as e:
        logger.warning(f"⚠️ Alias 조회 중 오류: {e}")
    return alias_name

def resolve_blue_green_collections(name: str) -> List[str]:
    """
    alias명 또는 물리 컬렉션명을 받아 Blue-Green 짝 중 실제 존재하는 물리 컬렉션 목록을 반환.

    네이밍 규칙(upload.py): alias `CD` → 물리 컬렉션 `CD_blue` / `CD_green`.
    - 입력이 alias든 물리명(`CD_blue`)이든 `_blue`/`_green` 접미사를 떼어 base를 구하고,
      `{base}_blue`, `{base}_green` 중 존재하는 것만 반환.
    - blue/green 짝이 하나도 없으면(접미사 규칙을 안 따르는 컬렉션) 입력명이 존재할 때 그대로 반환.
    - 어느 것도 존재하지 않으면 빈 목록 → 호출 측에서 검증·400 처리.
    """
    name = (name or "").strip()
    if not name:
        return []

    base = name
    for suffix in ("_blue", "_green"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break

    found = [c for c in (f"{base}_blue", f"{base}_green") if client.collection_exists(c)]
    if found:
        return found

    # blue/green 규칙 밖의 컬렉션 — 입력명이 그대로 존재하면 단독 처리
    if client.collection_exists(name):
        return [name]
    return []