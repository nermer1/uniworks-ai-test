"""모델 게이트웨이 — 자체 vLLM ↔ 상용 API ↔ mock 을 config로 스위치.

모듈은 이 call() 하나만 쓴다. provider 분기는 여기 한 곳에만 있어서
config의 default_model만 바꾸면 백엔드가 갈린다(= "옵션만 토글").
Stage 2에서 이 파일을 litellm 호출로 갈아끼우면 provider가 더 늘어난다(인터페이스 동일).
"""
import json
import httpx

from core.config import get_model_config


class ModelError(Exception):
    pass


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    """POST 후 4xx/5xx면 응답 본문까지 담아 에러 — 진짜 원인(어느 파라미터가 문제인지)을 보이게."""
    r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    if r.status_code >= 400:
        raise ModelError(f"{r.status_code} {r.reason_phrase}: {r.text[:800]}")
    return r.json()


def call(alias: str, messages: list, json_schema: dict | None = None,
         schema_name: str = "result", timeout: int = 120) -> dict:
    """{content, provider, model, usage} 반환. messages는 OpenAI chat 형식.

    구조화 출력 방식은 모델별 config의 structured_output이 결정한다(provider 차이를
    코드가 아니라 설정으로 흡수) — 'json_schema'(기본) / 'json_object' / 'none'.
    """
    cfg = get_model_config(alias)
    provider = cfg.get("provider")
    if provider == "mock":
        return _mock(alias)
    if provider == "openai_compat":
        response_format = _build_response_format(cfg, json_schema, schema_name)
        return _openai_compat(cfg, messages, response_format, timeout)
    if provider == "vertex":
        response_format = _build_response_format(cfg, json_schema, schema_name)
        return _vertex(cfg, messages, response_format, timeout)
    raise ModelError(f"알 수 없는 provider: {provider}")


def _build_response_format(cfg: dict, json_schema: dict | None, schema_name: str) -> dict | None:
    """provider별 구조화 출력 방식. vLLM은 json_schema를 먹지만 상용은 제각각이라
    config로 스위치한다. json_schema가 안 먹는 provider면 'json_object'나 'none'으로.
    """
    mode = cfg.get("structured_output", "json_schema")
    if mode == "json_schema" and json_schema:
        return {"type": "json_schema", "json_schema": {"name": schema_name, "schema": json_schema}}
    if mode == "json_object":
        return {"type": "json_object"}
    return None


def _build_payload(cfg: dict, messages: list, response_format: dict | None) -> dict:
    """chat/completions payload 공통 조립 (openai_compat·vertex 공유).

    reasoning_effort: config에 있으면 실음 — 'none'이면 thinking OFF(추출은 생각 불필요 →
    비용·지연 절감. 레퍼런스 univision도 추출 노선은 thinking OFF로 수렴).
    """
    payload = {"model": cfg["model"], "messages": messages}
    if response_format:
        # B 함정 #1: guided_json 아님. OpenAI 표준 response_format(json_schema)만 강제됨.
        payload["response_format"] = response_format
    effort = cfg.get("reasoning_effort")
    if effort is not None:
        payload["reasoning_effort"] = effort
    return payload


def _openai_compat(cfg: dict, messages: list, response_format: dict | None, timeout: int) -> dict:
    base = cfg["base_url"].rstrip("/")
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    payload = _build_payload(cfg, messages, response_format)
    data = _post_json(f"{base}/chat/completions", payload, headers, timeout)
    return {
        "content": data["choices"][0]["message"]["content"],
        "provider": cfg["provider"],
        "model": cfg["model"],
        "usage": data.get("usage", {}),
    }


def _vertex(cfg: dict, messages: list, response_format: dict | None, timeout: int) -> dict:
    """Vertex AI (GCP) — OpenAI 호환 엔드포인트. 인증은 ADC로 토큰 자동 발급·갱신.

    사전 준비:
      1) uv pip install google-auth
      2) gcloud auth application-default login   (또는 GOOGLE_APPLICATION_CREDENTIALS=서비스계정.json)
      3) config에 project_id / location 설정, model은 'google/gemini-2.5-flash' 형태
    """
    try:
        import google.auth
        import google.auth.transport.requests  # 이 모듈은 requests 패키지도 필요
    except ImportError as e:
        raise ModelError(f"Vertex 의존성 누락({e}). uv pip install google-auth requests")

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())  # 만료됐으면 자동 갱신

    project = cfg["project_id"]
    location = cfg.get("location", "global")
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    base = f"https://{host}/v1/projects/{project}/locations/{location}/endpoints/openapi"

    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    payload = _build_payload(cfg, messages, response_format)
    data = _post_json(f"{base}/chat/completions", payload, headers, timeout)
    return {
        "content": data["choices"][0]["message"]["content"],
        "provider": "vertex",
        "model": cfg["model"],
        "usage": data.get("usage", {}),
    }


def _mock(alias: str) -> dict:
    """모델 없이 뼈대를 돌리기 위한 목업 응답."""
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
