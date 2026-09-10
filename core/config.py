"""설정 로드 — config/app.config.json을 매 호출마다 읽어 hot-reload 지원.

파일이 작아 stat 비용이 미미하므로 캐시 없이 매번 읽는다(설정 바꾸면 다음 요청부터 반영).
provider의 실제 api_key는 코드/파일에 박지 않고 api_key_env(환경변수)에서 해석한다.
"""
import os
import json
import secrets
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_FILE = PROJECT_ROOT / "config" / "app.config.json"

# 세션 쿠키 서명 키. 프로덕션은 반드시 PLATFORM_SECRET_KEY 환경변수로 고정.
# 미설정 시 재시작마다 랜덤 → 기존 세션 무효(개발 편의). 고정해야 재시작해도 로그인 유지.
SECRET_KEY = os.environ.get("PLATFORM_SECRET_KEY") or secrets.token_hex(32)


def load_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def enabled_modules() -> list[str]:
    return load_config().get("enabled_modules", [])


def default_model() -> str:
    return load_config().get("default_model", "")


def get_model_config(alias: str) -> dict:
    """모델 별칭 → provider 설정. api_key_env가 있으면 환경변수에서 실제 키를 채운다."""
    models = load_config().get("models", {})
    if alias not in models:
        raise KeyError(f"모델 별칭 없음: {alias}")
    m = dict(models[alias])
    env = m.pop("api_key_env", None)
    if env and not m.get("api_key"):
        m["api_key"] = os.environ.get(env, "")
    return m
