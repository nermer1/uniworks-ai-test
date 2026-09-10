"""권한 — capability 매트릭스로 기능/모델 접근을 코어에서 한 곳에 강제.

모듈에 권한 로직을 흩뿌리지 않는다. 라우터는 Depends(require_capability("ocr"))만 걸면 됨.
"""
from fastapi import Depends, HTTPException

from core.auth import Principal, get_principal
from core.user_auth import User, get_current_user
from core.errors import ApiError


def require_capability(feature: str):
    """해당 기능 capability가 있는 Principal을 반환하는 FastAPI 의존성 생성기."""
    def dep(principal: Principal = Depends(get_principal)) -> Principal:
        if feature not in principal.capabilities.get("features", []):
            raise HTTPException(status_code=403, detail=f"권한 없음: {feature}")
        return principal
    return dep


def check_model(principal: Principal, alias: str) -> None:
    """이 키가 해당 모델 별칭을 쓸 수 있는지. 위반 시 403."""
    if alias not in principal.capabilities.get("models", []):
        raise HTTPException(status_code=403, detail=f"허용되지 않은 모델: {alias}")


# ─────────────────────────────────────────────────────────
# 사람 유저 RBAC — role → permission 매핑 (API키 capability와 대칭)
# 접근 규칙을 여기 한 곳에서 관리. 엔드포인트는 role이 아니라 permission을 체크.
# ─────────────────────────────────────────────────────────
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "개발자": {"logs:read", "monitoring:read"},
    "회계":   {"usage:read", "usage:export", "billing:read"},
    "관리자": {"*"},   # 전체
}


def user_permissions(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(role: str, perm: str) -> bool:
    perms = user_permissions(role)
    return "*" in perms or perm in perms


def require_permission(perm: str):
    """해당 permission을 가진 유저를 반환하는 의존성 생성기 (RBAC)."""
    def dep(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, perm):
            raise ApiError("FORBIDDEN", f"권한 없음: {perm}", status=403)
        return user
    return dep
