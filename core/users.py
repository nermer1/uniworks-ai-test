"""유저 저장소 — 사람 계정(사내 화면 로그인). API키(프로그램)와 별개.

비번은 pbkdf2(stdlib, salt+반복) — 느린 해시라 무차별 대입 방어. bcrypt/argon2 안 깔아도 됨.
"""
import hmac
import uuid
import secrets
import hashlib
from datetime import datetime, timezone

from core.db import connect

_ITERATIONS = 200_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """(salt, hash_hex) 반환. salt 없으면 새로 생성."""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _ITERATIONS)
    return salt, dk.hex()


def verify_password(password: str, salt: str, expected_hex: str) -> bool:
    _, actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected_hex)   # 타이밍 공격 방어 비교


def create_user(username: str, password: str, role: str) -> str:
    salt, phash = hash_password(password)
    uid = uuid.uuid4().hex[:12]
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, salt, role, is_active, created_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?)",
            (uid, username, phash, salt, role, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return uid


def get_user_by_username(username: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_user_by_id(uid: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_users() -> list[dict]:
    """안전 필드만 (password_hash·salt 제외)."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, username, role, is_active, created_at FROM users ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def update_user(uid: str, *, role: str | None = None,
                is_active: bool | None = None, password: str | None = None) -> bool:
    """role·is_active·password 중 준 것만 수정. 반영된 행 있으면 True."""
    fields, vals = [], []            # 컬럼명은 코드 상수(안전), 값만 ? 바인딩
    if role is not None:
        fields.append("role=?"); vals.append(role)
    if is_active is not None:
        fields.append("is_active=?"); vals.append(1 if is_active else 0)
    if password is not None:
        salt, phash = hash_password(password)
        fields += ["salt=?", "password_hash=?"]; vals += [salt, phash]
    if not fields:
        return False
    vals.append(uid)
    conn = connect()
    try:
        cur = conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0
