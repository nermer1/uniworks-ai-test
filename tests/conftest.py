"""pytest 공용 픽스처. 실제 app.db 안 건드리게 임시 DB로 격리.

주의: PLATFORM_DB_PATH를 app import '전에' 설정해야 함(core.db가 import 시점에 읽음).
"""
import os
import tempfile

# ── app import 전에 임시 DB 지정 (격리) ──
os.environ["PLATFORM_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

import json                       # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import pytest                     # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import app              # noqa: E402  (import 시 init_db가 임시 DB에 테이블 생성)
from core.db import connect      # noqa: E402
from core.auth import hash_key   # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)       # 인스턴스마다 쿠키 독립 (로그인 세션 격리)


@pytest.fixture
def api_key():
    """features=ocr/recommend/admin, models=mock 만 허용하는 테스트 키."""
    raw = "sk-test-key"
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO api_keys (id, key_hash, tenant, capabilities, is_active, created_at)"
        " VALUES (?, ?, ?, ?, 1, ?)",
        ("k-test", hash_key(raw), "test-corp",
         json.dumps({"features": ["ocr", "recommend", "admin"], "models": ["mock"]}),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit(); conn.close()
    return raw
