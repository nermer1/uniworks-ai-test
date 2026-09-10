"""프롬프트 스토어 — data/prompts/{name}.txt 를 호출 시점에 읽어 hot-reload.

파일을 고치면 다음 요청부터 반영(재기동 불필요). A·B가 검증한 패턴.
Stage 2+에서 Langfuse 등을 붙이면 이 함수 뒤(어댑터)로 숨기고, 검증 경계도 여기에 둔다.
"""
from core.config import DATA_DIR

PROMPT_DIR = DATA_DIR / "prompts"

_FALLBACK = "이미지를 읽고 지정된 JSON 스키마 형식으로만 출력하세요. 보이는 값만 채우고 없으면 null."


def get(name: str) -> str:
    path = PROMPT_DIR / f"{name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return _FALLBACK
