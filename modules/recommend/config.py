"""recommend 모듈 설정 — A(unirec) app/config.py의 추천 관련 상수를 고스란히 이식.

engine.py·fit_messages.py가 `import ... config as cfg`로 이 모듈 속성을 런타임 참조한다
(상수 import 아님 → 나중에 Settings로 런타임 변경도 붙일 수 있음). 값은 A 기준 그대로.
RAG/매뉴얼/서버로그/스냅샷/settings.json 영속화는 이번 이식 범위 밖(추후).
"""
import os
import uuid

from core.logging_setup import get_logger

logger = get_logger("recommend")

# ── Qdrant 연결 (A 기본값: 192.168.11.17:6333) ──
QDRANT_HOST = os.environ.get("QDRANT_HOST", "192.168.11.17")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
QDRANT_GRPC_PORT = int(os.environ.get("QDRANT_GRPC_PORT", "6334"))

# ── 임베딩 모델 (계정추천 서비스 모델) ──
MODEL_NAME = "BM-K/KoSimCSE-roberta-multitask"
VECTOR_SIZE = 768
RAG_EMBED_MODEL = "dragonkue/BGE-m3-ko"   # 차원매핑/폴백 참조용(추천 서빙엔 미사용, 이식 충실성 위해 유지)

# 네임스페이스 (UUID5 비즈니스 키 생성용 — 업로드 시 포인트 id)
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "unidocu.ai.unirec")

# ── 검색/업로드 공용 상수 ──
SEARCH_LIMIT = 200
BATCH_SIZE = 256
INDEXING_THRESHOLD = 10000
HNSW_EF = int(os.environ.get("HNSW_EF", "64"))
MAX_BATCH_QUERIES = 0
ENCODE_CHUNK_SIZE = 256

# ── 스코어링 엔진 상수 (Adaptive Max-Weighted) ──
SIMILARITY_THRESHOLD = 0.55
MAX_FREQ_BONUS = 3.0
MAX_WEIGHT_BASE = 0.5
MAX_WEIGHT_SCALE = 0.5
MAX_CONTEXT_BONUS = 5.0

# ── 쿼리 텍스트 생성 컬럼 (ET에 정답 계정명 HKONT_TXT 절대 금지) ──
QUERY_COLUMNS = {
    "CD": ["MERCH_NAME", "MCC_NAME", "KOSTL_TXT", "SNAME", "APPR_TIME"],
    "ET": ["SU_NAME", "IP_PERSNAME1", "IP_DEPTNAME1", "IP_PERSNAME2", "IP_DEPTNAME2"],
}

# ── 불용어 (임베딩 텍스트 노이즈 제거) ──
STOPWORDS = ["주식회사", "(주)", "（주）", "㈜", "주)", "주）",
             "유한회사", "(유)", "（유）", "유)", "유）", "(유한)", "（유한）",
             "(자)", "（자）", "(명)", "（명）", "(사)", "（사）", "(재)", "（재）",
             "(의)", "（의）", "(학)", "（학）", "(복)", "（복）", "(영농)", "（영농）"]
STOPWORD_TARGETS = {
    "CD": ["MERCH_NAME"],
    "ET": ["SU_NAME"],
}

# ── 피처 매칭 (form_type별 (필드, 최대 보너스%p)) ──
MATCH_FEATURES = {
    "CD": [("CARDNO", 3.0)],       # 카드번호 — 같은 카드
    "ET": [("SU_ID", 3.0)],        # 공급자 사업자번호
}

# ── FIT_REASON 문구 오버라이드 (기본과 다른 것만; 기본은 fit_messages.py) ──
FIT_MESSAGES: dict = {}
