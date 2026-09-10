"""모델 게이트웨이 — litellm로 provider 무관 호출. config 별칭 → litellm 모델 문자열.

모듈은 call() 하나만 쓴다(provider 무지). provider 교체 = config 별칭의 model 문자열만 변경.
mock provider는 litellm 없이 도는 오프라인 테스트용(pytest가 이걸로 네트워크 없이 통과).

config 별칭 예:
  card-mock:       {provider: mock}
  card-commercial: {provider: litellm, model: "gemini/gemini-2.5-flash", api_key_env: GEMINI_API_KEY}
  card-vertex:     {provider: litellm, model: "vertex_ai/gemini-2.5-flash", vertex_project:..., vertex_location:...}
  card-9b(자체):   {provider: litellm, model: "openai/qwen2.5-vl", base_url: "http://.../v1"}  # OpenAI 호환 vLLM
"""
import os
import json

from core.config import get_model_config


class ModelError(Exception):
    pass


def call(alias: str, messages: list, json_schema: dict | None = None,
         schema_name: str = "result", timeout: int = 120) -> dict:
    """{content, provider, model, usage} 반환. messages는 OpenAI chat 형식."""
    cfg = get_model_config(alias)
    provider = cfg.get("provider")
    if provider == "mock":
        return _mock(alias)
    if provider == "litellm":
        response_format = _build_response_format(cfg, json_schema, schema_name)
        return _litellm(cfg, messages, response_format, timeout)
    raise ModelError(f"알 수 없는 provider: {provider}")


def _build_response_format(cfg: dict, json_schema: dict | None, schema_name: str) -> dict | None:
    """구조화 출력 방식 — provider 차이는 config로 흡수(litellm이 provider별 매핑 처리).
    'json_schema'(기본) / 'json_object' / 'none'.
    """
    mode = cfg.get("structured_output", "json_schema")
    if mode == "json_schema" and json_schema:
        return {"type": "json_schema", "json_schema": {"name": schema_name, "schema": json_schema}}
    if mode == "json_object":
        return {"type": "json_object"}
    return None


def _litellm(cfg: dict, messages: list, response_format: dict | None, timeout: int) -> dict:
    try:
        import litellm
    except ImportError:
        raise ModelError("litellm 필요: uv pip install litellm")

    kwargs = {"model": cfg["model"], "messages": messages, "timeout": timeout}
    if response_format:
        kwargs["response_format"] = response_format
    if cfg.get("reasoning_effort") is not None:
        kwargs["reasoning_effort"] = cfg["reasoning_effort"]
    if cfg.get("base_url"):                       # 자체 vLLM 등 OpenAI 호환 엔드포인트
        kwargs["api_base"] = cfg["base_url"]
    if cfg.get("api_key_env"):                    # 없으면 litellm이 표준 env를 알아서 읽음
        key = os.environ.get(cfg["api_key_env"])
        if key:
            kwargs["api_key"] = key
    if cfg.get("vertex_project"):                 # vertex_ai 전용
        kwargs["vertex_project"] = cfg["vertex_project"]
    if cfg.get("vertex_location"):
        kwargs["vertex_location"] = cfg["vertex_location"]

    resp = litellm.completion(**kwargs)           # API 에러는 상위(라우터)에서 잡아 ApiError로

    content = resp.choices[0].message.content
    u = getattr(resp, "usage", None)
    usage = {
        "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
        "total_tokens": getattr(u, "total_tokens", 0) or 0,
    }
    model = cfg["model"]
    provider = model.split("/")[0] if "/" in model else "litellm"   # 원장 provider = 'gemini'/'vertex_ai'/'openai'...
    return {"content": content, "provider": provider, "model": model, "usage": usage}


def _mock(alias: str) -> dict:
    """모델 없이 뼈대를 돌리기 위한 목업 응답 (litellm 불필요)."""
    content = json.dumps(
        {"가맹점명": "목데이터상사", "사업자번호": "123-45-67890",
         "거래일자": "2026-09-07", "총액": 15000},
        ensure_ascii=False,
    )
    return {
        "content": content,
        "provider": "mock",
        "model": alias,
        "usage": {"prompt_tokens": 800, "completion_tokens": 60, "total_tokens": 860},
    }
