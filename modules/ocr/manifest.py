"""OCR 모듈이 코어에 요구하는 것 선언 — 모듈 계약(contract)의 명세부.

지금은 문서/참고용. Stage 2+에서 코어가 이걸 읽어 요구 검증(예: 멀티모달 모델인지)에 쓴다.
"""
MANIFEST = {
    "name": "ocr",
    "feature": "ocr",            # capability 이름
    "routes_prefix": "/ocr",
    "requires": {
        "model_kind": "multimodal",   # 상용도 반드시 비전 모델이어야 함 (이미지 직독)
    },
    "usage_unit": "page",        # 원장에 남길 단위
}
