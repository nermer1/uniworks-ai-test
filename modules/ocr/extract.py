"""이미지 → 정형 JSON. 모델 호출은 반드시 core.model_gateway를 통한다(provider 무지).

B의 실측 함정 반영:
 #1 response_format json_schema로 강제 (guided_json 아님)
 #2 모든 필드를 required 에 (빠지면 값이 있어도 LLM이 생략)
"""
import base64
import json

from core import model_gateway, prompt_store

# B 함정 #2: 전 필드 required (없으면 null로라도 항상 출력하게 강제).
# 숫자 코드성 필드(사업자번호·승인번호·가맹점번호 등)는 string — 앞자리 0·하이픈·마스킹 보존.
# 금액은 integer.
CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "가맹점명":   {"type": ["string", "null"]},
        "사업자번호": {"type": ["string", "null"]},
        "대표자명":   {"type": ["string", "null"]},
        "가맹점번호": {"type": ["string", "null"]},   # 앞자리 0 있음 → 문자열
        "사업자주소": {"type": ["string", "null"]},
        "전화번호":   {"type": ["string", "null"]},
        "거래일시":   {"type": ["string", "null"]},   # 날짜+시각
        "승인상태":   {"type": ["string", "null"]},
        "결제방법":   {"type": ["string", "null"]},   # 일시불/할부
        "승인번호":   {"type": ["string", "null"]},
        "공급가액":   {"type": ["integer", "null"]},
        "부가세":     {"type": ["integer", "null"]},
        "봉사료":     {"type": ["integer", "null"]},
        "총액":       {"type": ["integer", "null"]},
    },
    "required": [
        "가맹점명", "사업자번호", "대표자명", "가맹점번호", "사업자주소", "전화번호",
        "거래일시", "승인상태", "결제방법", "승인번호",
        "공급가액", "부가세", "봉사료", "총액",
    ],
}


def format_image(image_bytes: bytes, mime: str, alias: str, prompt_name: str = "ocr_card"):
    """(result_dict, gateway_out) 반환. gateway_out엔 provider/model/usage 포함."""
    data_uri = f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")
    prompt = prompt_store.get(prompt_name)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ],
    }]
    # 스키마만 넘기고, 실제 response_format 구성은 gateway가 모델 config에 맞춰 결정.
    out = model_gateway.call(alias, messages, json_schema=CARD_SCHEMA, schema_name="card_receipt")
    content = out.get("content")
    try:
        result = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        result = {"_raw": content}   # 평문이면 감싸서 반환 (B와 동일)
    return result, out
