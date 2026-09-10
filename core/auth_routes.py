"""사내 화면 인증 라우트 — /auth/login · /auth/logout · /auth/me (세션 쿠키 기반).

API키 인증(프로그램)과 별개. 사람 유저가 사내 화면에 로그인할 때.
"""
from fastapi import APIRouter, Response, Form, Depends

from core import users, session
from core.envelope import success
from core.errors import ApiError
from core.user_auth import User, get_current_user
from core.permissions import user_permissions
from core.logging_setup import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
_log = get_logger("auth")


@router.post("/login")
def login(response: Response, username: str = Form(...), password: str = Form(...)):
    u = users.get_user_by_username(username)
    if u is None or not u["is_active"] or not users.verify_password(password, u["salt"], u["password_hash"]):
        _log.info("login failed", extra={"path": f"user={username}"})
        raise ApiError("LOGIN_FAILED", "아이디 또는 비밀번호가 올바르지 않습니다", status=401)
    cookie = session.create_session_cookie(u["id"], u["role"])
    response.set_cookie(
        session.COOKIE_NAME, cookie,
        httponly=True, samesite="lax", max_age=session.MAX_AGE_SEC,
        # secure=True,  # HTTPS 배포 시 켜기
    )
    _log.info("login ok", extra={"path": f"user={username} role={u['role']}"})
    return success({"username": u["username"], "role": u["role"]})


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(session.COOKIE_NAME)
    return success({"logged_out": True})


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return success({
        "username": user.username,
        "role": user.role,
        "permissions": sorted(user_permissions(user.role)),
    })
