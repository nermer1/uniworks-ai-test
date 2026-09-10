"""이미지 → 정형 JSON. 문서종류별 스키마/프롬프트(파일) + 자동분류(auto).

종류 추가 = DOC_TYPES 한 줄 + data/schemas/<type>.json + data/prompts/ocr_<type>.txt.
auto = 분류 LLM(enum)로 종류 판정 후 그 종류로 추출 (LLM 2콜: 분류+추출).
B 실측 함정: #1 response_format json_schema, #2 전 필드 required.
"""
import json
import time
import base64

from core.config import DATA_DIR
from core import model_gateway, prompt_store

SCHEMA_DIR = DATA_DIR / "schemas"

# 문서종류 레지스트리 — 값=프롬프트 파일명. 스키마는 data/schemas/<type>.json (규칙).
DOC_TYPES = {
    "card": {"prompt": "ocr_card"},
    "jiro": {"prompt": "ocr_jiro"},
    "tax":  {"prompt": "ocr_tax"},
}

# 분류 라벨(enum) → doc_type. '기타'는 추출 안 함(None).
# 분류 스키마 enum은 이 키들로 코드에서 생성 → DOC_TYPES/라우팅과 항상 동기(수동 sync 불필요).
CLASSIFY_MAP = {
    "카드현금영수증": "card",
    "지로영수증": "jiro",
    "세금계산서": "tax",
    "기타": None,
}
_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {"문서종류": {"type": "string", "enum": list(CLASSIFY_MAP.keys())}},
    "required": ["문서종류"],
}
_TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


def valid_doc_types() -> list[str]:
    return list(DOC_TYPES.keys())


def _load_schema(doc_type: str) -> dict:
    """data/schemas/<type>.json 을 호출 시점에 로드 (편집 즉시 반영)."""
    return json.loads((SCHEMA_DIR / f"{doc_type}.json").read_text(encoding="utf-8"))


def _messages(image_bytes: bytes, mime: str, prompt: str) -> list:
    data_uri = f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")
    return [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ],
    }]


def format_image(image_bytes: bytes, mime: str, alias: str, doc_type: str = "card"):
    """(result_dict, gateway_out) — 지정 doc_type 스키마로 추출."""
    spec = DOC_TYPES[doc_type]
    schema = _load_schema(doc_type)
    prompt = prompt_store.get(spec["prompt"])
    t0 = time.perf_counter()
    out = model_gateway.call(alias, _messages(image_bytes, mime, prompt),
                             json_schema=schema, schema_name=f"{doc_type}_result")
    out["ms"] = round((time.perf_counter() - t0) * 1000)
    content = out.get("content")
    try:
        result = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        result = {"_raw": content}
    return result, out


def classify(image_bytes: bytes, mime: str, alias: str):
    """이미지 → (doc_type|None, gateway_out). None은 '기타'(추출 안 함). 분류 LLM 1콜."""
    prompt = prompt_store.get("ocr_classify")
    t0 = time.perf_counter()
    out = model_gateway.call(alias, _messages(image_bytes, mime, prompt),
                             json_schema=_CLASSIFY_SCHEMA, schema_name="doc_classify")
    out["ms"] = round((time.perf_counter() - t0) * 1000)
    try:
        label = json.loads(out.get("content")).get("문서종류")
    except (json.JSONDecodeError, TypeError, AttributeError):
        label = None
    return CLASSIFY_MAP.get(label), out


def _merge_usage(a: dict, b: dict) -> dict:
    """두 콜(분류+추출)의 usage 합산. provider/model은 추출 쪽(b) 기준."""
    ua, ub = a.get("usage", {}), b.get("usage", {})
    usage = {k: (ua.get(k, 0) or 0) + (ub.get(k, 0) or 0) for k in _TOKEN_KEYS}
    return {
        "provider": b.get("provider"), "model": b.get("model"), "usage": usage,
        "ms": (a.get("ms", 0) or 0) + (b.get("ms", 0) or 0),   # 분류+추출 총시간
        "classify_ms": a.get("ms"), "extract_ms": b.get("ms"),
    }


def extract_one(image_bytes: bytes, mime: str, alias: str, doc_type: str):
    """(payload, gateway_out) 반환. payload = {doc_type, result}.

    doc_type='auto' → 분류 후 종류별 추출(2콜). '기타'면 result=None(사람 검토).
    """
    if doc_type == "auto":
        detected, c_out = classify(image_bytes, mime, alias)
        if detected is None:
            return {"doc_type": None, "result": None}, c_out       # 기타 → 추출 생략
        result, e_out = format_image(image_bytes, mime, alias, detected)
        return {"doc_type": detected, "result": result}, _merge_usage(c_out, e_out)

    result, out = format_image(image_bytes, mime, alias, doc_type)
    return {"doc_type": doc_type, "result": result}, out
