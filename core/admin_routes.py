"""관리자 유저 관리 — /admin/users (생성·목록·수정). users:manage 권한(관리자) 필요.

DB 손편집 대신 여기로 유저를 안전하게 CRUD(비번은 pbkdf2로 해싱돼 저장).
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import users
from core.envelope import success
from core.errors import ApiError
from core.permissions import require_permission, ROLE_PERMISSIONS
from core.user_auth import User

router = APIRouter(prefix="/admin", tags=["admin"])

_VALID_ROLES = set(ROLE_PERMISSIONS.keys())


class CreateUserReq(BaseModel):
    username: str
    password: str
    role: str


class UpdateUserReq(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


@router.post("/users")
def create_user_ep(req: CreateUserReq, admin: User = Depends(require_permission("users:manage"))):
    if req.role not in _VALID_ROLES:
        raise ApiError("INVALID_ROLE", f"role은 {sorted(_VALID_ROLES)} 중 하나여야 합니다", status=400)
    if users.get_user_by_username(req.username):
        raise ApiError("USER_EXISTS", "이미 존재하는 username입니다", status=409)
    uid = users.create_user(req.username, req.password, req.role)
    return success({"id": uid, "username": req.username, "role": req.role})


@router.get("/users")
def list_users_ep(admin: User = Depends(require_permission("users:manage"))):
    return success({"users": users.list_users()})


@router.patch("/users/{uid}")
def update_user_ep(uid: str, req: UpdateUserReq,
                   admin: User = Depends(require_permission("users:manage"))):
    if req.role is not None and req.role not in _VALID_ROLES:
        raise ApiError("INVALID_ROLE", f"role은 {sorted(_VALID_ROLES)} 중 하나여야 합니다", status=400)
    if users.get_user_by_id(uid) is None:
        raise ApiError("USER_NOT_FOUND", "없는 유저입니다", status=404)
    users.update_user(uid, role=req.role, is_active=req.is_active, password=req.password)
    return success({"id": uid, "updated": True})
