"""추천 엔진 — Stage 3는 mock. 실제 스코어링(Qdrant + 인프로세스 임베딩)은 이후 이식.

레퍼런스 A의 Adaptive Max-Weighted 스코어링이 여기로 들어올 자리.
OCR과 달리 model_gateway(litellm)를 안 거친다 — 추천은 LLM 호출이 아니라 벡터 검색이라
임베딩이 인프로세스에서 돈다(A가 torch/sentence-transformers를 프로세스에 물던 이유).
"""


def recommend(merchant_name: str, mcc_name: str | None = None, amount: int | None = None) -> list[dict]:
    """증빙(가맹점명 등) → 계정과목(HKONT) 추천. mock은 입력 무관 고정 3건.

    실제 이식 시: 쿼리 텍스트 임베딩 → Qdrant Top-K → HKONT별 그룹핑 → 가중 스코어링.
    """
    return [
        {"account": "82500", "account_name": "복리후생비", "score": 87.5, "confidence": "HIGH"},
        {"account": "81100", "account_name": "여비교통비", "score": 62.3, "confidence": "MEDIUM"},
        {"account": "83000", "account_name": "소모품비",   "score": 41.0, "confidence": "LOW"},
    ]
