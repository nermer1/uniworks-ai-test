"""recommend 모듈이 코어에 요구하는 것 선언.

지금은 mock이라 실제 요구 없음. 실제 이식 시 vector_store·text_embedding을 코어(또는
모듈 전용 의존)로 요구 — 이때 requirements-recommend.txt(torch·qdrant)가 필요해진다.
"""
MANIFEST = {
    "name": "recommend",
    "feature": "recommend",
    "routes_prefix": "/recommend",
    "requires": {},              # Stage 실이식 때: {"vector_store": True, "text_embedding": True}
    "usage_unit": "request",
}
