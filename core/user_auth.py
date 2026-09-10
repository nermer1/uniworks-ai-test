"""사람 유저 인증 — 세션 쿠키 → 현재 유저. (API키 인증 auth.py와 별개 경로)

get_current_user: 쿠키 검증 → DB 재조회(최신 role + is_active) → User 반환.
DB 재조회라 유저를 비활성화하면 다음 요청부터 차단됨(부분 무효화).
"""
from dataclasses import dataclass

from fastapi import Request

from core.session import read_session_cookie, COOKIE_NAME
from core.users import get_user_by_id
from core.errors import ApiError


@dataclass
class User:
    id: str
    username: str
    role: str


def get_current_user(request: Request) -> User:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise ApiError("UNAUTHENTICATED", "로그인이 필요합니다", status=401)
    data = read_session_cookie(raw)
    if data is None:
        raise ApiError("SESSION_INVALID", "세션이 만료되었거나 유효하지 않습니다", status=401)
    u = get_user_by_id(data["uid"])
    if u is None or not u["is_active"]:
        raise ApiError("UNAUTHENTICATED", "유효하지 않은 사용자입니다", status=401)
    return User(u["id"], u["username"], u["role"])
