"""세션 쿠키 — hmac 서명(stdlib, 의존성 0). 무상태(서버에 세션 저장 안 함).

쿠키 값 = base64(payload).base64(hmac서명). 위변조 불가(서명), 만료 포함.
로그아웃 = 쿠키 삭제. (참고: 무상태라 만료 전 강제 무효화는 불가 — 필요해지면
서버측 세션 테이블로 전환. 지금은 is_active 재조회로 부분 무효화 커버)
"""
import time
import json
import hmac
import base64
import hashlib

from core.config import SECRET_KEY

COOKIE_NAME = "session"
MAX_AGE_SEC = 8 * 3600   # 8시간


def _sign(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(hmac.new(SECRET_KEY.encode(), raw, hashlib.sha256).digest())


def create_session_cookie(user_id: str, role: str) -> str:
    body = {"uid": user_id, "role": role, "exp": int(time.time()) + MAX_AGE_SEC}
    raw = base64.urlsafe_b64encode(json.dumps(body).encode())
    return raw.decode() + "." + _sign(raw).decode()


def read_session_cookie(value: str) -> dict | None:
    """유효하면 payload dict, 아니면 None (위변조/만료/형식오류)."""
    try:
        raw_s, sig_s = value.split(".", 1)
        raw = raw_s.encode()
        if not hmac.compare_digest(_sign(raw), sig_s.encode()):   # 서명 검증
            return None
        body = json.loads(base64.urlsafe_b64decode(raw))
        if body.get("exp", 0) < time.time():                      # 만료 검증
            return None
        return body
    except Exception:
        return None
