"""approval(전결규정 RAG) 설정 — A(unirec) config.py의 RAG 상수 고스란히 이식.

검색은 recommend.engine의 client·모델 로더를 재사용(공용 vector 인프라). 임베딩=BGE-m3-ko 1024d.
업로드/구조화(LLM)는 이번 범위 밖(추후, model_gateway 경유).
"""
from core.logging_setup import get_logger

logger = get_logger("approval")

RAG_COLLECTION = "APPROVAL_RULE"              # 전결규정 규칙 컬렉션 (단일)
RAG_EMBED_MODEL = "dragonkue/BGE-m3-ko"       # 1024d — recommend.engine이 컬렉션 차원으로 자동감지
RAG_TOP_K_DEFAULT = 5
RAG_CANDIDATE_LIMIT = 30                       # 후처리 필터(기안자·금액) 시 후보 확보 수
RAG_MIN_SCORE = 0.55

DOCUMENT_TYPES = ("approval_policy", "travel_policy")                  # 전결규정 / 출장규정
RULE_TYPES = ("approval_line", "amount_limit", "evidence", "general")  # 결재선/금액한도/증빙요건/일반
