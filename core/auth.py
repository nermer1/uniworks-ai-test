"""인증 — X-API-Key 헤더 → Principal(tenant, capabilities).

키는 평문 저장 안 함(sha256 해시 대조). 모듈은 이 Principal만 받고 재인증하지 않는다.
"""
import hashlib
import json
from dataclasses import dataclass

from fastapi import Header, HTTPException

from core.db import connect


@dataclass
class Principal:
    key_id: str
    tenant: str
    capabilities: dict   # {"features": [...], "models": [...]}


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_principal(x_api_key: str = Header(default=None, alias="X-API-Key")) -> Principal:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key 헤더가 필요합니다")
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_hash=? AND is_active=1",
            (hash_key(x_api_key),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=401, detail="유효하지 않은 API Key")
    return Principal(row["id"], row["tenant"], json.loads(row["capabilities"]))
